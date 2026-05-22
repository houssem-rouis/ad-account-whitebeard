import requests

GRAPH_VERSION = 'v16.0'
GRAPH_BASE = f'https://graph.facebook.com/{GRAPH_VERSION}'

CURRENCY_RATES_TO_USD = {
    'USD': 1.0,
    'EUR': 1.08,
    'GBP': 1.25,
    'CAD': 0.74,
    'AUD': 0.65,
    'JPY': 0.0072,
    'CHF': 1.10,
    'MXN': 0.055,
}


def connect_account(provider: str, credentials: dict):
    if provider.lower() == 'facebook':
        return connect_meta_account(credentials.get('access_token'), credentials.get('account_id'))
    raise ValueError('Provider not supported yet.')


def connect_meta_account(access_token: str, account_id: str):
    if not access_token or not account_id:
        raise ValueError('Meta access token and account ID are required.')

    if not account_id.startswith('act_'):
        account_id = f'act_{account_id}'

    url = f'{GRAPH_BASE}/{account_id}'
    params = {
        'access_token': access_token,
        'fields': 'name,account_id'
    }
    response = requests.get(url, params=params, timeout=15)
    data = response.json()

    if response.status_code != 200 or 'error' in data:
        raise ValueError(data.get('error', {}).get('message', 'Failed to connect to Meta Ads.'))

    return {
        'connected': True,
        'account_id': account_id,
        'account_name': data.get('name', account_id)
    }


def fetch_meta_ads(access_token: str, account_id: str):
    if not access_token or not account_id:
        raise ValueError('Meta access token and account ID are required.')

    if not account_id.startswith('act_'):
        account_id = f'act_{account_id}'

    account_url = f'{GRAPH_BASE}/{account_id}'
    account_params = {
        'access_token': access_token,
        'fields': 'name,account_id,currency'
    }
    account_resp = requests.get(account_url, params=account_params, timeout=15)
    account_data = account_resp.json()
    if account_resp.status_code != 200 or 'error' in account_data:
        raise ValueError(account_data.get('error', {}).get('message', 'Failed to fetch Meta account info.'))

    currency = account_data.get('currency', 'USD') or 'USD'
    usd_rate = float(CURRENCY_RATES_TO_USD.get(currency.upper(), 1.0))

    ads = []
    url = f'{GRAPH_BASE}/{account_id}/ads'
    params = {
        'access_token': access_token,
        'fields': (
            'name,effective_status,campaign{name,daily_budget,lifetime_budget},'
            'adset{name,daily_budget,lifetime_budget},creative{body},'
            'insights.date_preset(today){spend,impressions,clicks,ctr,purchase_roas}'
        ),
        'limit': 100
    }

    while url:
        response = requests.get(url, params=params, timeout=20)
        data = response.json()
        if response.status_code != 200 or 'error' in data:
            raise ValueError(data.get('error', {}).get('message', 'Failed to fetch Meta ads.'))

        for item in data.get('data', []):
            insights = item.get('insights', {}).get('data', [])
            insight = insights[0] if insights else {}
            creative = item.get('creative', {})
            script = creative.get('body') or item.get('name', '')
            raw_spend = float(insight.get('spend', 0) or 0)
            spend_usd = round(raw_spend * usd_rate, 2)
            purchase_roas = insight.get('purchase_roas', [])
            roas_value = 0.0
            if isinstance(purchase_roas, list) and purchase_roas:
                roas_value = float(purchase_roas[0].get('value') or 0)
            elif isinstance(purchase_roas, dict):
                roas_value = float(purchase_roas.get('value') or 0)

            revenue = round(spend_usd * roas_value, 2) if roas_value else 0.0
            campaign = item.get('campaign', {})
            adset = item.get('adset', {})
            campaign_budget = float(campaign.get('daily_budget') or campaign.get('lifetime_budget') or 0)
            adset_budget = float(adset.get('daily_budget') or adset.get('lifetime_budget') or 0)

            ads.append({
                'id': f'fb-{item.get("id")}',
                'external_id': item.get('id'),
                'facebook_status': item.get('effective_status'),
                'name': item.get('name', ''),
                'script': script,
                'impressions': int(insight.get('impressions', 0) or 0),
                'clicks': int(insight.get('clicks', 0) or 0),
                'spend': raw_spend,
                'spend_usd': spend_usd,
                'revenue': revenue,
                'roas': roas_value,
                'status': 'running' if item.get('effective_status', '').upper() == 'ACTIVE' else 'paused',
                'currency': 'USD',
                'created_at': item.get('created_time', ''),
                'updated_at': datetime_now_iso(),
                'campaign_id': campaign.get('id'),
                'campaign_name': campaign.get('name', 'Unknown campaign'),
                'campaign_budget_usd': round(campaign_budget * usd_rate, 2),
                'adset_id': adset.get('id'),
                'adset_name': adset.get('name', 'Unknown ad set'),
                'adset_budget_usd': round(adset_budget * usd_rate, 2),
            })

        paging = data.get('paging', {})
        url = paging.get('next')
        params = None

    return ads


def datetime_now_iso():
    from datetime import datetime
    return datetime.utcnow().isoformat()


def fetch_ads(account_config: dict):
    if account_config.get('provider', '').lower().startswith('facebook'):
        return fetch_meta_ads(account_config.get('meta_access_token'), account_config.get('meta_account_id'))
    return []


def group_ads_by_account(ad_records):
    grouped = {}
    for item in ad_records:
        key = item.get('account_name', item.get('account_id', 'unknown'))
        grouped.setdefault(key, []).append(item)
    return grouped
