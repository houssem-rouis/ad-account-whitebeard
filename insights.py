"""Analytics aggregations for the /analytics page.

Phase 1 helpers operate on already-synced ad data (no API calls).
Phase 2 helpers wrap account-level Meta insights with breakdown parameters —
those are fetched in services/ad_provider.fetch_meta_account_insights and
combined here across accounts.
"""

import re
from collections import defaultdict
from statistics import median
from urllib.parse import urlparse

from treatment import fx_rate, extract_purchases


# Editor attribution: ad names containing | <token> | are credited to that
# editor. Add new editors here.
EDITORS = [
    ("Katrina", "kat"),
    ("Anthony", "anthony"),
    ("Moiez", "moiez"),
    ("Fasih", "fasih"),
]

EDITOR_PATTERNS = [
    (name, re.compile(r"\|\s*" + re.escape(token) + r"\s*\|", re.IGNORECASE))
    for name, token in EDITORS
]


def detect_editor(ad_name):
    if not ad_name:
        return None
    for name, pattern in EDITOR_PATTERNS:
        if pattern.search(ad_name):
            return name
    return None


# ---------------------------------------------------------------------------
# Date range presets
# ---------------------------------------------------------------------------

DATE_RANGES = [
    ("today", "Today"),
    ("yesterday", "Yesterday"),
    ("last_7d", "Last 7 days"),
    ("last_28d", "Last 28 days"),
    ("last_90d", "Last 90 days"),
    ("this_month", "This month"),
    ("last_month", "Last month"),
    ("maximum", "All time"),
]

DEFAULT_RANGE = "last_28d"


def resolve_range(value):
    keys = {k for k, _ in DATE_RANGES}
    return value if value in keys else DEFAULT_RANGE


# ---------------------------------------------------------------------------
# Phase 1 — aggregations from already-synced ad data
# ---------------------------------------------------------------------------


def account_scorecard(ads, accounts):
    by_account = defaultdict(lambda: {
        "spend": 0.0, "revenue": 0.0, "clicks": 0, "impressions": 0,
        "purchases": 0, "ads_count": 0, "active_ads": 0,
    })
    for ad in ads:
        bucket = by_account[ad.get("account_id")]
        bucket["spend"] += ad.get("spend_usd", 0)
        bucket["revenue"] += ad.get("revenue_usd", 0)
        bucket["clicks"] += int(ad.get("clicks", 0) or 0)
        bucket["impressions"] += int(ad.get("impressions", 0) or 0)
        bucket["purchases"] += ad.get("purchases", 0)
        bucket["ads_count"] += 1
        if str(ad.get("status", "")).lower() == "running":
            bucket["active_ads"] += 1

    rows = []
    for account_id, bucket in by_account.items():
        account = accounts.get(account_id, {})
        spend = bucket["spend"]
        revenue = bucket["revenue"]
        rows.append({
            "account_id": account_id,
            "name": account.get("name", "Unknown"),
            "spend": spend,
            "revenue": revenue,
            "roas": round(revenue / spend, 2) if spend else 0,
            "ctr": round(bucket["clicks"] / bucket["impressions"] * 100, 2) if bucket["impressions"] else 0,
            "cpa": round(spend / bucket["purchases"], 2) if bucket["purchases"] else 0,
            "purchases": bucket["purchases"],
            "ads_count": bucket["ads_count"],
            "active_ads": bucket["active_ads"],
        })
    rows.sort(key=lambda r: r["spend"], reverse=True)
    return rows


def campaign_leaderboard(ads, accounts):
    by_campaign = defaultdict(lambda: {
        "spend": 0.0, "revenue": 0.0, "clicks": 0, "impressions": 0,
        "purchases": 0, "ads_count": 0,
    })
    meta = {}
    for ad in ads:
        cid = ad.get("campaign_id") or "uncategorized"
        bucket = by_campaign[cid]
        bucket["spend"] += ad.get("spend_usd", 0)
        bucket["revenue"] += ad.get("revenue_usd", 0)
        bucket["clicks"] += int(ad.get("clicks", 0) or 0)
        bucket["impressions"] += int(ad.get("impressions", 0) or 0)
        bucket["purchases"] += ad.get("purchases", 0)
        bucket["ads_count"] += 1
        if cid not in meta:
            meta[cid] = {
                "id": cid,
                "name": ad.get("campaign_name") or "Unknown campaign",
                "account_id": ad.get("account_id"),
            }

    rows = []
    for cid, bucket in by_campaign.items():
        spend = bucket["spend"]
        revenue = bucket["revenue"]
        info = meta[cid]
        rows.append({
            **info,
            "account_name": accounts.get(info["account_id"], {}).get("name", "Unknown"),
            "spend": spend,
            "revenue": revenue,
            "roas": round(revenue / spend, 2) if spend else 0,
            "ctr": round(bucket["clicks"] / bucket["impressions"] * 100, 2) if bucket["impressions"] else 0,
            "cpa": round(spend / bucket["purchases"], 2) if bucket["purchases"] else 0,
            "purchases": bucket["purchases"],
            "ads_count": bucket["ads_count"],
        })
    rows.sort(key=lambda r: r["spend"], reverse=True)
    return rows


def creative_leaderboard(ads, accounts, sort_by="spend_usd", top_n=12):
    enriched = []
    for ad in ads:
        account = accounts.get(ad.get("account_id"), {})
        enriched.append({
            **ad,
            "account_name": account.get("name", "Unknown"),
        })
    enriched.sort(key=lambda a: a.get(sort_by, 0) or 0, reverse=True)
    return enriched[:top_n]


def funnel_metrics(ads):
    impressions = sum(int(ad.get("impressions", 0) or 0) for ad in ads)
    clicks = sum(int(ad.get("clicks", 0) or 0) for ad in ads)
    purchases = sum(ad.get("purchases", 0) for ad in ads)
    return {
        "impressions": impressions,
        "clicks": clicks,
        "purchases": purchases,
        "click_rate": round(clicks / impressions * 100, 2) if impressions else 0,
        "conversion_rate": round(purchases / clicks * 100, 2) if clicks else 0,
        "purchase_rate": round(purchases / impressions * 100, 4) if impressions else 0,
    }


def spend_distribution(ads, accounts):
    """Spend rolled up account → campaign → adset for the stacked chart."""
    levels = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for ad in ads:
        account_id = ad.get("account_id") or "unknown"
        campaign = ad.get("campaign_name") or "Uncategorized"
        adset = ad.get("adset_name") or "Uncategorized"
        levels[account_id][campaign][adset] += ad.get("spend_usd", 0)

    result = []
    for account_id, campaigns in levels.items():
        name = accounts.get(account_id, {}).get("name", "Unknown")
        campaigns_list = []
        for camp_name, adsets in campaigns.items():
            adsets_list = [{"name": k, "spend": v} for k, v in adsets.items()]
            adsets_list.sort(key=lambda a: a["spend"], reverse=True)
            campaigns_list.append({
                "name": camp_name,
                "spend": sum(a["spend"] for a in adsets_list),
                "adsets": adsets_list,
            })
        campaigns_list.sort(key=lambda c: c["spend"], reverse=True)
        result.append({
            "account_id": account_id,
            "name": name,
            "spend": sum(c["spend"] for c in campaigns_list),
            "campaigns": campaigns_list,
        })
    result.sort(key=lambda r: r["spend"], reverse=True)
    return result


def status_mix(ads):
    mix = defaultdict(int)
    for ad in ads:
        status = str(ad.get("status", "unknown")).lower() or "unknown"
        mix[status] += 1
    return dict(mix)


def editor_breakdown(ads):
    """Attribute ads to editors via `| token |` markers in the ad name.

    Ads whose name doesn't carry an editor token are excluded — that's the
    point: this stat answers "how is each editor performing on what they own".
    """
    buckets = defaultdict(lambda: {
        "spend": 0.0, "revenue": 0.0, "clicks": 0, "impressions": 0,
        "purchases": 0, "ads_count": 0, "ads": [],
    })
    for ad in ads:
        editor = detect_editor(ad.get("name", ""))
        if not editor:
            continue
        bucket = buckets[editor]
        bucket["spend"] += ad.get("spend_usd", 0)
        bucket["revenue"] += ad.get("revenue_usd", 0)
        bucket["clicks"] += int(ad.get("clicks", 0) or 0)
        bucket["impressions"] += int(ad.get("impressions", 0) or 0)
        bucket["purchases"] += ad.get("purchases", 0)
        bucket["ads_count"] += 1
        bucket["ads"].append(ad)

    rows = []
    for editor, b in buckets.items():
        spend = b["spend"]
        revenue = b["revenue"]
        impressions = b["impressions"]
        clicks = b["clicks"]
        purchases = b["purchases"]
        rows.append({
            "editor": editor,
            "ads_count": b["ads_count"],
            "spend": spend,
            "revenue": revenue,
            "roas": round(revenue / spend, 2) if spend else 0,
            "purchases": purchases,
            "cpa": round(spend / purchases, 2) if purchases else 0,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
            "cpm": round(spend / impressions * 1000, 2) if impressions else 0,
            "clicks": clicks,
            "impressions": impressions,
        })
    rows.sort(key=lambda r: r["spend"], reverse=True)
    return rows


def editor_breakdown_from_insight_rows(rows):
    """Like `editor_breakdown` but built from Meta `level=ad` insights rows.

    Each row carries `ad_name` and metrics for the chosen `date_preset`, so
    the result respects the analytics date filter. Used when at least one ad
    account is connected; falls back to the snapshot variant otherwise.
    """
    buckets = defaultdict(lambda: {
        "spend": 0.0, "revenue": 0.0, "clicks": 0, "impressions": 0,
        "purchases": 0, "ad_ids": set(),
    })
    for row in rows:
        editor = detect_editor(row.get("ad_name", ""))
        if not editor:
            continue
        metrics = _row_metrics(row)
        bucket = buckets[editor]
        bucket["spend"] += metrics["spend"]
        bucket["revenue"] += metrics["revenue"]
        bucket["clicks"] += metrics["clicks"]
        bucket["impressions"] += metrics["impressions"]
        bucket["purchases"] += metrics["purchases"]
        if row.get("ad_id"):
            bucket["ad_ids"].add(row["ad_id"])

    out = []
    for editor, b in buckets.items():
        spend = b["spend"]
        revenue = b["revenue"]
        impressions = b["impressions"]
        clicks = b["clicks"]
        purchases = b["purchases"]
        out.append({
            "editor": editor,
            "ads_count": len(b["ad_ids"]),
            "spend": spend,
            "revenue": revenue,
            "roas": round(revenue / spend, 2) if spend else 0,
            "purchases": purchases,
            "cpa": round(spend / purchases, 2) if purchases else 0,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
            "cpm": round(spend / impressions * 1000, 2) if impressions else 0,
            "clicks": clicks,
            "impressions": impressions,
        })
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


def creative_type_mix(ads):
    mix = defaultdict(int)
    for ad in ads:
        kind = (ad.get("creative_type") or "").upper()
        if kind == "VIDEO":
            label = "Video"
        elif kind == "IMAGE":
            label = "Image"
        elif kind:
            label = kind.title()
        else:
            label = "Unknown"
        mix[label] += 1
    return dict(mix)


# ---------------------------------------------------------------------------
# Phase 3 — outlier detection (still no API calls)
# ---------------------------------------------------------------------------

OUTLIER_MIN_IMPRESSIONS = 1000
OUTLIER_MIN_SPEND = 25.0


def detect_outliers(ads, accounts, account_rows):
    insights = []

    eligible_ctr = [a for a in ads if int(a.get("impressions", 0) or 0) >= OUTLIER_MIN_IMPRESSIONS]
    if eligible_ctr:
        med = median(a.get("ctr", 0) for a in eligible_ctr) or 0
        top = max(eligible_ctr, key=lambda a: a.get("ctr", 0))
        if med and top.get("ctr", 0) >= med * 2:
            insights.append({
                "kind": "positive",
                "title": "Standout CTR",
                "body": f"<strong>{top.get('name')}</strong> has a CTR of {top['ctr']}% — about {round(top['ctr']/med, 1)}× the median of your other creatives. Consider amplifying it.",
                "ad_id": top.get("id"),
            })

    eligible_roas = [a for a in ads if a.get("spend_usd", 0) >= OUTLIER_MIN_SPEND]
    if eligible_roas:
        top_roas = max(eligible_roas, key=lambda a: a.get("roas", 0))
        if top_roas.get("roas", 0) >= 3:
            insights.append({
                "kind": "positive",
                "title": "Top ROAS",
                "body": f"<strong>{top_roas.get('name')}</strong> is returning {top_roas['roas']}× spend. Lean into this creative or audience.",
                "ad_id": top_roas.get("id"),
            })

    trap = max(
        (a for a in ads if a.get("spend_usd", 0) >= OUTLIER_MIN_SPEND and (a.get("purchases", 0) or 0) == 0),
        key=lambda a: a.get("spend_usd", 0),
        default=None,
    )
    if trap and trap.get("spend_usd", 0) >= OUTLIER_MIN_SPEND * 2:
        insights.append({
            "kind": "negative",
            "title": "Spend without conversions",
            "body": f"<strong>{trap.get('name')}</strong> has spent ${round(trap['spend_usd'], 2)} with 0 purchases. Pause or rework before more budget burns.",
            "ad_id": trap.get("id"),
        })

    if account_rows:
        roas_values = [r["roas"] for r in account_rows if r["spend"] >= OUTLIER_MIN_SPEND]
        if roas_values:
            best = max(account_rows, key=lambda r: r["roas"])
            worst = min((r for r in account_rows if r["spend"] >= OUTLIER_MIN_SPEND), key=lambda r: r["roas"], default=None)
            if best and best["roas"] >= 2:
                insights.append({
                    "kind": "positive",
                    "title": "Account leader",
                    "body": f"<strong>{best['name']}</strong> leads with {best['roas']}× ROAS. Worth shifting budget toward it.",
                    "ad_id": None,
                })
            if worst and worst["roas"] < 1 and worst["spend"] >= OUTLIER_MIN_SPEND * 2:
                insights.append({
                    "kind": "negative",
                    "title": "Account drag",
                    "body": f"<strong>{worst['name']}</strong> is returning {worst['roas']}× spend — review creative or audience before continuing.",
                    "ad_id": None,
                })

    if len(ads) >= 5:
        active_only = [a for a in ads if str(a.get("status", "")).lower() == "running" and a.get("spend_usd", 0) >= 5]
        if active_only:
            spends = [a["spend_usd"] for a in active_only]
            total = sum(spends)
            top_one = max(active_only, key=lambda a: a["spend_usd"])
            share = top_one["spend_usd"] / total if total else 0
            if share >= 0.4 and total >= 100:
                insights.append({
                    "kind": "neutral",
                    "title": "Concentration risk",
                    "body": f"One ad — <strong>{top_one.get('name')}</strong> — accounts for {round(share * 100)}% of active spend. A failure here would hit results hard.",
                    "ad_id": top_one.get("id"),
                })

    return insights


# ---------------------------------------------------------------------------
# Phase 2 — breakdown aggregation
# Inputs are already FX-converted rows from ad_provider.
# Each row carries a "spend_usd" field plus the breakdown columns.
# ---------------------------------------------------------------------------


def _row_metrics(row):
    spend = float(row.get("spend_usd", 0) or 0)
    clicks = int(float(row.get("clicks", 0) or 0))
    impressions = int(float(row.get("impressions", 0) or 0))
    purchases = extract_purchases(row.get("actions"))
    roas = 0.0
    purchase_roas = row.get("purchase_roas")
    if isinstance(purchase_roas, list) and purchase_roas:
        try:
            roas = float(purchase_roas[0].get("value") or 0)
        except (TypeError, ValueError):
            roas = 0.0
    revenue = round(spend * roas, 2)
    return {
        "spend": spend,
        "revenue": revenue,
        "roas": roas,
        "clicks": clicks,
        "impressions": impressions,
        "purchases": purchases,
        "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
        "cpa": round(spend / purchases, 2) if purchases else 0,
    }


def _aggregate(rows, keys):
    """Group breakdown rows by the given key tuple, summing metrics."""
    grouped = defaultdict(lambda: {
        "spend": 0.0, "revenue": 0.0, "clicks": 0, "impressions": 0,
        "purchases": 0,
    })
    for row in rows:
        metrics = _row_metrics(row)
        key = tuple(row.get(k, "") for k in keys)
        bucket = grouped[key]
        bucket["spend"] += metrics["spend"]
        bucket["revenue"] += metrics["revenue"]
        bucket["clicks"] += metrics["clicks"]
        bucket["impressions"] += metrics["impressions"]
        bucket["purchases"] += metrics["purchases"]

    out = []
    for key, bucket in grouped.items():
        spend = bucket["spend"]
        revenue = bucket["revenue"]
        impressions = bucket["impressions"]
        clicks = bucket["clicks"]
        purchases = bucket["purchases"]
        record = {keys[i]: key[i] for i in range(len(keys))}
        record.update({
            "spend": spend,
            "revenue": revenue,
            "roas": round(revenue / spend, 2) if spend else 0,
            "clicks": clicks,
            "impressions": impressions,
            "purchases": purchases,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
            "cpa": round(spend / purchases, 2) if purchases else 0,
        })
        out.append(record)
    return out


def aggregate_country(rows):
    return sorted(_aggregate(rows, ("country",)), key=lambda r: r["spend"], reverse=True)


def aggregate_placement(rows):
    combined = _aggregate(rows, ("publisher_platform", "platform_position"))
    for row in combined:
        platform = (row.get("publisher_platform") or "?").title()
        position = (row.get("platform_position") or "?").replace("_", " ").title()
        row["label"] = f"{platform} · {position}"
    return sorted(combined, key=lambda r: r["spend"], reverse=True)


def aggregate_device(rows):
    combined = _aggregate(rows, ("impression_device",))
    for row in combined:
        row["label"] = (row.get("impression_device") or "Unknown").replace("_", " ").title()
    return sorted(combined, key=lambda r: r["spend"], reverse=True)


def aggregate_demographics(rows):
    return _aggregate(rows, ("age", "gender"))


def aggregate_timeseries(rows):
    series = _aggregate(rows, ("date_start",))
    series.sort(key=lambda r: r["date_start"])
    return series


def aggregate_hourly(rows):
    series = _aggregate(rows, ("hourly_stats_aggregated_by_advertiser_time_zone",))
    for row in series:
        row["hour"] = row.pop("hourly_stats_aggregated_by_advertiser_time_zone", "")
    series.sort(key=lambda r: r.get("hour", ""))
    return series


def normalize_landing_path(url):
    """Reduce a full destination URL to just its path, dropping host and params.

    e.g. ``https://gentlepawsupplies.com/pages/gpcollars-v1?utm_source=fb``
    becomes ``/pages/gpcollars-v1``. Returns None when there's no usable URL so
    callers can bucket those rows separately.
    """
    if not url:
        return None
    try:
        path = urlparse(url.strip()).path or "/"
    except ValueError:
        return None
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return path


def aggregate_landing_pages(rows, url_map):
    """Group level=ad insight rows by landing-page path.

    ``rows`` are FX-converted ad-level insight rows (one per ad) that respect
    the selected date range. ``url_map`` maps ad_id -> destination URL. Rows
    whose ad has no resolvable URL are bucketed under "(unknown)". Returns rows
    carrying spend, cpc, cpm, ctr and roas per path, sorted by spend.
    """
    grouped = defaultdict(lambda: {
        "spend": 0.0, "revenue": 0.0, "clicks": 0, "impressions": 0,
        "purchases": 0,
    })
    for row in rows:
        path = normalize_landing_path(url_map.get(row.get("ad_id"))) or "(unknown)"
        metrics = _row_metrics(row)
        bucket = grouped[path]
        bucket["spend"] += metrics["spend"]
        bucket["revenue"] += metrics["revenue"]
        bucket["clicks"] += metrics["clicks"]
        bucket["impressions"] += metrics["impressions"]
        bucket["purchases"] += metrics["purchases"]

    out = []
    for path, bucket in grouped.items():
        spend = bucket["spend"]
        revenue = bucket["revenue"]
        clicks = bucket["clicks"]
        impressions = bucket["impressions"]
        out.append({
            "path": path,
            "label": path,
            "spend": spend,
            "revenue": revenue,
            "roas": round(revenue / spend, 2) if spend else 0,
            "cpc": round(spend / clicks, 2) if clicks else 0,
            "cpm": round(spend / impressions * 1000, 2) if impressions else 0,
            "ctr": round(clicks / impressions * 100, 2) if impressions else 0,
            "clicks": clicks,
            "impressions": impressions,
            "purchases": bucket["purchases"],
        })
    out.sort(key=lambda r: r["spend"], reverse=True)
    return out


# Convenience for the demographic heatmap: turn flat rows into a matrix.
def demographics_matrix(rows):
    ages = []
    genders = []
    cells = {}
    for row in rows:
        age = row.get("age") or "unknown"
        gender = row.get("gender") or "unknown"
        if age not in ages:
            ages.append(age)
        if gender not in genders:
            genders.append(gender)
        cells[(age, gender)] = row

    age_order = ["13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+", "unknown"]
    ages.sort(key=lambda a: age_order.index(a) if a in age_order else 99)
    gender_order = ["female", "male", "unknown"]
    genders.sort(key=lambda g: gender_order.index(g) if g in gender_order else 99)

    matrix = []
    for age in ages:
        row = []
        for gender in genders:
            cell = cells.get((age, gender))
            row.append({
                "age": age,
                "gender": gender,
                "spend": cell["spend"] if cell else 0,
                "purchases": cell["purchases"] if cell else 0,
                "cpa": cell["cpa"] if cell else 0,
                "roas": cell["roas"] if cell else 0,
            })
        matrix.append({"age": age, "cells": row})
    return {"ages": ages, "genders": genders, "rows": matrix}


def hourly_matrix(rows):
    """Returns hours 0-23 with metrics, ready for a bar chart."""
    by_hour = {}
    for row in rows:
        hour_str = row.get("hour", "")
        try:
            hour = int(hour_str.split(":")[0])
        except (ValueError, AttributeError):
            continue
        by_hour[hour] = row
    out = []
    for h in range(24):
        row = by_hour.get(h)
        out.append({
            "hour": h,
            "label": f"{h:02d}:00",
            "spend": row["spend"] if row else 0,
            "purchases": row["purchases"] if row else 0,
            "cpa": row["cpa"] if row else 0,
        })
    return out


def timeseries_chart(series):
    return {
        "labels": [row["date_start"] for row in series],
        "spend": [row["spend"] for row in series],
        "revenue": [row["revenue"] for row in series],
        "purchases": [row["purchases"] for row in series],
        "roas": [row["roas"] for row in series],
    }


# ---------------------------------------------------------------------------
# Phase 3 — creative frequency scatter
# ---------------------------------------------------------------------------


def frequency_scatter(ads):
    points = []
    for ad in ads:
        impressions = int(ad.get("impressions", 0) or 0)
        if impressions < 200:
            continue
        ctr = ad.get("ctr", 0)
        freq = ad.get("frequency")
        if freq is None:
            continue
        try:
            freq = float(freq)
        except (TypeError, ValueError):
            continue
        if freq <= 0:
            continue
        points.append({
            "x": freq,
            "y": ctr,
            "label": ad.get("name") or "",
            "ad_id": ad.get("id"),
            "spend": ad.get("spend_usd", 0),
        })
    return points
