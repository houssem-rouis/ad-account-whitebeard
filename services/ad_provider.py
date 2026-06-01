import time

import requests

from crypto import get_account_token

GRAPH_VERSION = "v16.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Simple in-memory TTL cache for analytics breakdowns. Keyed by a deterministic
# tuple derived from the request parameters; entries expire after CACHE_TTL.
_INSIGHTS_CACHE = {}
CACHE_TTL_SECONDS = 600  # 10 minutes


def _cache_get(key):
    entry = _INSIGHTS_CACHE.get(key)
    if not entry:
        return None
    ts, data = entry
    if time.time() - ts > CACHE_TTL_SECONDS:
        _INSIGHTS_CACHE.pop(key, None)
        return None
    return data


def _cache_set(key, data):
    _INSIGHTS_CACHE[key] = (time.time(), data)


def clear_insights_cache():
    _INSIGHTS_CACHE.clear()


def connect_account(provider: str, credentials: dict):
    if provider.lower() == "facebook":
        return connect_meta_account(
            credentials.get("access_token"), credentials.get("account_id")
        )
    raise ValueError("Provider not supported yet.")


def connect_meta_account(access_token: str, account_id: str):
    if not access_token or not account_id:
        raise ValueError("Meta access token and account ID are required.")

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    url = f"{GRAPH_BASE}/{account_id}"
    params = {"access_token": access_token, "fields": "name,account_id,currency"}
    response = requests.get(url, params=params, timeout=15)
    data = response.json()

    if response.status_code != 200 or "error" in data:
        raise ValueError(
            data.get("error", {}).get("message", "Failed to connect to Meta Ads.")
        )

    return {
        "connected": True,
        "account_id": account_id,
        "account_name": data.get("name", account_id),
        "currency": data.get("currency", "USD") or "USD",
    }


def fetch_meta_ads(access_token: str, account_id: str):
    """Fetch ads from Meta. Returns raw native-currency data only.

    No currency conversion or derived metric math happens here — all of that
    runs at page-render time via `treatment.enrich_ad`.
    """
    if not access_token or not account_id:
        raise ValueError("Meta access token and account ID are required.")

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    account_url = f"{GRAPH_BASE}/{account_id}"
    account_params = {
        "access_token": access_token,
        "fields": "name,account_id,currency",
    }
    account_resp = requests.get(account_url, params=account_params, timeout=15)
    account_data = account_resp.json()
    if account_resp.status_code != 200 or "error" in account_data:
        raise ValueError(
            account_data.get("error", {}).get(
                "message", "Failed to fetch Meta account info."
            )
        )

    currency = account_data.get("currency", "USD") or "USD"

    ads = []
    url = f"{GRAPH_BASE}/{account_id}/ads"
    params = {
        "access_token": access_token,
        "fields": (
            "name,effective_status,campaign{name,daily_budget,lifetime_budget},"
            "adset{name,daily_budget,lifetime_budget},"
            "creative{body,image_url,thumbnail_url,video_id,object_type},"
            "insights.date_preset(today){spend,impressions,clicks,ctr,purchase_roas,actions,frequency}"
        ),
        "limit": 100,
    }

    while url:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        if response.status_code != 200 or "error" in data:
            raise ValueError(
                data.get("error", {}).get("message", "Failed to fetch Meta ads.")
            )

        for item in data.get("data", []):
            insights = item.get("insights", {}).get("data", [])
            insight = insights[0] if insights else {}
            creative = item.get("creative", {})
            script = creative.get("body") or item.get("name", "")
            purchase_roas = insight.get("purchase_roas", [])
            roas_value = 0.0
            if isinstance(purchase_roas, list) and purchase_roas:
                roas_value = float(purchase_roas[0].get("value") or 0)
            elif isinstance(purchase_roas, dict):
                roas_value = float(purchase_roas.get("value") or 0)

            campaign = item.get("campaign", {})
            adset = item.get("adset", {})
            campaign_budget = float(
                campaign.get("daily_budget") or campaign.get("lifetime_budget") or 0
            )
            adset_budget = float(
                adset.get("daily_budget") or adset.get("lifetime_budget") or 0
            )
            effective_status = item.get("effective_status", "") or ""

            video_id = creative.get("video_id")
            object_type = (creative.get("object_type") or "").upper()
            if video_id:
                creative_type = "VIDEO"
            elif creative.get("image_url"):
                creative_type = "IMAGE"
            else:
                creative_type = object_type or ""

            ads.append(
                {
                    "id": f'fb-{item.get("id")}',
                    "external_id": item.get("id"),
                    "name": item.get("name", ""),
                    "script": script,
                    "impressions": int(insight.get("impressions", 0) or 0),
                    "clicks": int(insight.get("clicks", 0) or 0),
                    "spend": float(insight.get("spend", 0) or 0),
                    "roas": roas_value,
                    "actions": insight.get("actions") or [],
                    "frequency": insight.get("frequency"),
                    "currency": currency,
                    "status": "running"
                    if effective_status.upper() == "ACTIVE"
                    else "paused",
                    "facebook_status": effective_status,
                    "created_at": item.get("created_time", ""),
                    "campaign_id": campaign.get("id"),
                    "campaign_name": campaign.get("name", "Unknown campaign"),
                    "campaign_budget": campaign_budget,
                    "adset_id": adset.get("id"),
                    "adset_name": adset.get("name", "Unknown ad set"),
                    "adset_budget": adset_budget,
                    "creative_type": creative_type,
                    "image_url": creative.get("image_url"),
                    "thumbnail_url": creative.get("thumbnail_url"),
                    "video_id": video_id,
                }
            )

        paging = data.get("paging", {})
        url = paging.get("next")
        params = None

    return ads


def fetch_meta_account_insights(
    access_token,
    account_id,
    breakdowns=None,
    time_increment=None,
    date_preset="last_28d",
    currency="USD",
    usd_rate=1.0,
    level="account",
):
    """Fetch breakdown-aware insights for an ad account.

    Results are cached for CACHE_TTL_SECONDS so toggling charts/currency on
    the analytics page doesn't re-hit the API. Each row is enriched with
    `spend_usd` (FX-converted using the supplied rate) so callers don't need
    to know currency math.
    """
    if not access_token or not account_id:
        return []

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    cache_key = (
        account_id,
        date_preset,
        time_increment or "",
        ",".join(breakdowns) if breakdowns else "",
        level,
    )
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    fields = "spend,impressions,clicks,ctr,purchase_roas,actions,frequency,reach,cpm,cpc"
    if level == "ad":
        # Meta needs `ad_name` explicit so the editor regex can match `| kat |`
        # markers; `ad_id` lets us count unique ads per editor.
        fields += ",ad_id,ad_name"
    elif level == "campaign":
        fields += ",campaign_id,campaign_name"
    params = {
        "access_token": access_token,
        "fields": fields,
        "date_preset": date_preset,
        "level": level,
        "limit": 500,
    }
    if breakdowns:
        params["breakdowns"] = ",".join(breakdowns)
    if time_increment:
        params["time_increment"] = time_increment

    rows = []
    url = f"{GRAPH_BASE}/{account_id}/insights"
    try:
        while url:
            response = requests.get(url, params=params, timeout=25)
            if response.status_code != 200:
                break
            data = response.json() or {}
            if "error" in data:
                break
            for item in data.get("data", []):
                try:
                    raw_spend = float(item.get("spend", 0) or 0)
                except (TypeError, ValueError):
                    raw_spend = 0.0
                item["spend_native"] = raw_spend
                item["spend_usd"] = round(raw_spend * usd_rate, 4)
                item["currency"] = currency
                rows.append(item)
            paging = data.get("paging", {})
            url = paging.get("next")
            params = None
    except requests.RequestException:
        pass

    _cache_set(cache_key, rows)
    return rows


def _extract_creative_link(creative):
    """Pull the destination (landing page) URL out of a creative.

    Meta stores the link in different places depending on the ad format, so we
    probe each known location in priority order. Returns None if none carry a
    URL (e.g. lead/engagement ads with no website destination).
    """
    for spec_key in ("object_story_spec", "effective_object_story_spec"):
        spec = creative.get(spec_key) or {}
        link_data = spec.get("link_data") or {}
        if link_data.get("link"):
            return link_data["link"]
        video_data = spec.get("video_data") or {}
        cta_value = (video_data.get("call_to_action") or {}).get("value") or {}
        if cta_value.get("link"):
            return cta_value["link"]
        template_data = spec.get("template_data") or {}
        if template_data.get("link"):
            return template_data["link"]
    feed = creative.get("asset_feed_spec") or {}
    for link_url in feed.get("link_urls") or []:
        if link_url.get("website_url"):
            return link_url["website_url"]
    return None


def fetch_meta_ad_landing_pages(access_token, account_id):
    """Return a map of ``ad_id -> landing page URL`` for an ad account.

    Landing page is a property of the ad's creative, not an insights breakdown,
    so we fetch it separately and let callers join it onto level=ad insight
    rows. Cached for CACHE_TTL_SECONDS like the insights calls.
    """
    if not access_token or not account_id:
        return {}

    if not account_id.startswith("act_"):
        account_id = f"act_{account_id}"

    cache_key = ("landing_pages", account_id)
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    url_map = {}
    url = f"{GRAPH_BASE}/{account_id}/ads"
    params = {
        "access_token": access_token,
        "fields": "id,creative{object_story_spec,effective_object_story_spec,asset_feed_spec}",
        "limit": 200,
    }
    try:
        while url:
            response = requests.get(url, params=params, timeout=25)
            if response.status_code != 200:
                break
            data = response.json() or {}
            if "error" in data:
                break
            for item in data.get("data", []):
                link = _extract_creative_link(item.get("creative") or {})
                if link and item.get("id"):
                    url_map[item["id"]] = link
            paging = data.get("paging", {})
            url = paging.get("next")
            params = None
    except requests.RequestException:
        pass

    _cache_set(cache_key, url_map)
    return url_map


def fetch_meta_video_media(video_id: str, access_token: str):
    """Resolve a Meta video's playable source URL and poster picture.

    Called lazily from the ad-detail page so it isn't part of the sync path.
    Returns an empty dict on any failure — caller should fall back gracefully.
    """
    if not video_id or not access_token:
        return {}
    try:
        resp = requests.get(
            f"{GRAPH_BASE}/{video_id}",
            params={"access_token": access_token, "fields": "source,picture,permalink_url"},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json() or {}
    except requests.RequestException:
        pass
    return {}


def fetch_ads(account_config: dict):
    if account_config.get("provider", "").lower().startswith("facebook"):
        return fetch_meta_ads(
            get_account_token(account_config),
            account_config.get("meta_account_id"),
        )
    return []


def group_ads_by_account(ad_records):
    grouped = {}
    for item in ad_records:
        key = item.get("account_name", item.get("account_id", "unknown"))
        grouped.setdefault(key, []).append(item)
    return grouped
