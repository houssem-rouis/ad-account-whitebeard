"""AD provider connector stubs.

This module contains example helper functions to connect external ad accounts.
Extend these methods to support Facebook Ads, Google Ads, TikTok Ads, or any other API.
"""


def connect_account(provider: str, credentials: dict):
    """Stub: Connect an ad provider account.
    Return a dictionary with account data or raise an exception.
    """
    if provider.lower() == 'facebook':
        # Implement Facebook Marketing API connection here
        return {'connected': True, 'account_id': credentials.get('account_id')}
    if provider.lower() == 'google':
        # Implement Google Ads API connection here
        return {'connected': True, 'account_id': credentials.get('account_id')}
    raise ValueError('Provider not supported yet.')


def fetch_ads(account_config: dict):
    """Stub: Fetch ads for a connected account.
    Replace with live API calls and normalize returned ads.
    """
    return []


def group_ads_by_account(ad_records):
    """Group a set of ads by account name or id."""
    grouped = {}
    for item in ad_records:
        key = item.get('account_name', item.get('account_id', 'unknown'))
        grouped.setdefault(key, []).append(item)
    return grouped
