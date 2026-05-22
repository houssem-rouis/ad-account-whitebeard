"""Read-time treatment for stored ad data.

Storage holds only what the provider returned. Every page load runs ads through
`enrich_ad` to derive USD values and computed metrics, so a bug in conversion or
metric logic can be fixed and reloaded without re-syncing.
"""

FX_RATES_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.25,
    "CAD": 0.74,
    "AUD": 0.65,
    "JPY": 0.0072,
    "CHF": 1.10,
    "MXN": 0.055,
}


def fx_rate(currency):
    return float(FX_RATES_TO_USD.get((currency or "USD").upper(), 1.0))


def _num(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default


# Meta returns multiple purchase-like action types per ad. Prefer the most
# aggregated one available; fall back to specific ones.
PURCHASE_ACTION_TYPES = (
    "omni_purchase",
    "purchase",
    "offsite_conversion.fb_pixel_purchase",
)


def extract_purchases(actions):
    if not actions:
        return 0
    if isinstance(actions, dict):
        actions = [actions]
    by_type = {}
    for entry in actions:
        if not isinstance(entry, dict):
            continue
        action_type = entry.get("action_type")
        if not action_type:
            continue
        try:
            by_type[action_type] = int(float(entry.get("value") or 0))
        except (TypeError, ValueError):
            continue
    for key in PURCHASE_ACTION_TYPES:
        if key in by_type:
            return by_type[key]
    return 0


def enrich_ad(ad):
    if not ad:
        return ad

    out = dict(ad)
    currency = out.get("currency") or "USD"
    rate = fx_rate(currency)

    spend = _num(out.get("spend"))
    clicks = _num(out.get("clicks"))
    impressions = _num(out.get("impressions"))
    roas = _num(out.get("roas"))

    spend_usd = round(spend * rate, 2)
    revenue = round(spend * roas, 2)
    revenue_usd = round(spend_usd * roas, 2)

    out["currency"] = currency
    out["spend"] = spend
    out["spend_usd"] = spend_usd
    out["roas"] = roas
    out["revenue"] = revenue
    out["revenue_usd"] = revenue_usd
    out["purchases"] = extract_purchases(out.get("actions"))
    out["ctr"] = round(clicks / impressions * 100, 2) if impressions else 0.0
    out["cpc"] = round(spend / clicks, 2) if clicks else 0.0
    out["cpc_usd"] = round(spend_usd / clicks, 2) if clicks else 0.0
    out["roi"] = round((roas - 1) * 100, 1) if roas else 0.0

    # Meta returns daily_budget / lifetime_budget in the account currency's
    # minor unit (e.g. cents), so convert to the major unit before applying FX.
    campaign_budget = _num(out.get("campaign_budget")) / 100
    adset_budget = _num(out.get("adset_budget")) / 100
    out["campaign_budget"] = campaign_budget
    out["campaign_budget_usd"] = round(campaign_budget * rate, 2)
    out["adset_budget"] = adset_budget
    out["adset_budget_usd"] = round(adset_budget * rate, 2)

    return out


def enrich_ads(ads):
    return [enrich_ad(ad) for ad in ads]
