import re

AWARENESS_LEVELS = [
    ('high', 'High awareness'),
    ('mid', 'Middle awareness'),
    ('low', 'Low awareness'),
]

TONE_KEYWORDS = {
    'urgent': ['now', 'urgent', 'limited', 'today', 'hurry'],
    'friendly': ['you', 'we', 'friendly', 'easy', 'help'],
    'authoritative': ['proven', 'guaranteed', 'results', 'expert'],
    'emotional': ['love', 'feel', 'heart', 'emotion', 'story'],
}

STYLE_KEYWORDS = {
    'short & punchy': ['quick', 'easy', 'fast', 'simple', 'bold'],
    'story-driven': ['story', 'behind', 'because', 'journey', 'tale'],
    'educational': ['learn', 'how to', 'discover', 'guide', 'tips'],
    'direct-response': ['buy', 'order', 'sign up', 'call now', 'click'],
}

AWARENESS_PHRASES = {
    'low': ['new', 'never heard', 'discover', 'introducing', 'first time'],
    'mid': ['learn more', 'compare', 'better than', 'why', 'trusted'],
    'high': ['join now', 'sale', 'offer', 'don\'t miss', 'best'],
}

KEYWORD_POOL = ['free', 'now', 'discover', 'limited', 'proven', 'easy', 'best', 'new', 'today', 'results']


def analyze_ad_text(script: str):
    text = script.strip().lower()
    length = len(text.split())
    tone = detect_category(text, TONE_KEYWORDS, default='balanced')
    style = detect_category(text, STYLE_KEYWORDS, default='classic')
    awareness_level = detect_category(text, AWARENESS_PHRASES, default='mid')
    keywords = ', '.join([kw for kw in KEYWORD_POOL if kw in text])
    best_hook = find_best_hook(script)
    score = round((length / 10.0) + len(keywords.split(',')) * 2 + 5, 1)
    return {
        'length': length,
        'tone': tone,
        'style': style,
        'awareness_level': awareness_level,
        'score': score,
        'keywords': keywords,
        'best_hook': best_hook,
    }


def detect_category(text: str, map_data, default='neutral'):
    counts = {name: 0 for name in map_data}
    for category, words in map_data.items():
        for word in words:
            if word in text:
                counts[category] += 1
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else default


def find_best_hook(script: str):
    sentences = re.split(r'[.!?]\s*', script.strip())
    for sentence in sentences:
        if len(sentence.split()) <= 12 and sentence:
            return sentence.strip()
    return sentences[0].strip() if sentences else ''


def build_account_insights(accounts):
    summary = []
    for account in accounts:
        ads = account.ads
        total_spend = sum(ad.spend for ad in ads)
        total_revenue = sum(ad.revenue for ad in ads)
        total_roi = round(((total_revenue - total_spend) / total_spend * 100), 1) if total_spend else 0.0
        awareness_counts = {}
        for ad in ads:
            if ad.analysis:
                awareness_counts[ad.analysis.awareness_level] = awareness_counts.get(ad.analysis.awareness_level, 0) + 1
        summary.append({
            'account': account,
            'ads': ads,
            'total_spend': total_spend,
            'total_revenue': total_revenue,
            'roi': total_roi,
            'awareness_counts': awareness_counts,
            'best_hooks': [ad.analysis.best_hook for ad in ads if ad.analysis and ad.analysis.best_hook],
        })
    return summary


def build_recommendations(accounts):
    recommendations = []
    for account in accounts:
        ads = account.ads
        if not ads:
            continue
        highest_roi = max((ad.roi() for ad in ads), default=0)
        low_roi = min((ad.roi() for ad in ads), default=0)
        recommendations.append({
            'account': account,
            'best_tag': 'Keep testing hooks similar to the best performers.' if highest_roi >= 10 else 'Review headline clarity and emotional direction.',
            'avoid_tag': 'Cut ads with low CTR and unclear calls to action.' if low_roi < 0 else 'Reallocate spend from steady but weak performers.',
            'next_test': 'Try a stronger opening question or a short story hook.'
        })
    return recommendations
