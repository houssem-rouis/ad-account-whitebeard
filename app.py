from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from storage import FileStore
from services.ad_provider import connect_meta_account, fetch_meta_ads
from analysis import analyze_ad_text

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-change-in-production'

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User model
class User(UserMixin):
    def __init__(self, id, username, password_hash, is_admin=False):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.is_admin = is_admin
    
    @staticmethod
    def get(user_id):
        users = FileStore.load("users", {})
        user_data = users.get(str(user_id))
        if user_data:
            return User(user_data['id'], user_data['username'], user_data['password_hash'], user_data.get('is_admin', False))
        return None
    
    @staticmethod
    def get_by_username(username):
        users = FileStore.load("users", {})
        for user_id, user_data in users.items():
            if user_data['username'] == username:
                return User(user_data['id'], user_data['username'], user_data['password_hash'], user_data.get('is_admin', False))
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.get_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    accounts = FileStore.load("accounts", {})
    ads_data = FileStore.load("ads", {})
    all_ads = list(ads_data.values())

    stats = []
    total_spend = 0.0
    total_clicks = 0.0
    total_impressions = 0.0
    active_ads = 0

    for account_id, account in accounts.items():
        account_ads = [ad for ad in all_ads if ad.get('account_id') == account_id]
        account_spend = sum(float(ad.get('spend', 0) or 0) for ad in account_ads)
        account_revenue = sum(float(ad.get('revenue', 0) or 0) for ad in account_ads)
        account_clicks = sum(float(ad.get('clicks', 0) or 0) for ad in account_ads)
        account_impressions = sum(float(ad.get('impressions', 0) or 0) for ad in account_ads)
        account_roi = round(((account_revenue - account_spend) / account_spend * 100), 1) if account_spend else 0
        account_ctr = round((account_clicks / account_impressions * 100), 1) if account_impressions else 0
        account_cpc = round((account_spend / account_clicks), 2) if account_clicks else 0

        stats.append({
            'account': account,
            'ads': account_ads,
            'spend': account_spend,
            'revenue': account_revenue,
            'roi': account_roi,
            'ctr': account_ctr,
            'avg_cpc': account_cpc,
        })

        total_spend += account_spend
        total_clicks += account_clicks
        total_impressions += account_impressions
        active_ads += sum(1 for ad in account_ads if ad.get('status') == 'running')

    recent_ads = sorted(all_ads, key=lambda x: x.get('updated_at', ''), reverse=True)[:6]
    for ad in recent_ads:
        ad['account_name'] = accounts.get(ad.get('account_id'), {}).get('name', 'Unknown')

    top_ads = sorted(all_ads, key=lambda x: float(x.get('spend', 0) or 0), reverse=True)[:5]
    summary_metrics = {
        'accounts': len(accounts),
        'ads': len(all_ads),
        'spend': total_spend,
        'active_ads': active_ads,
        'ctr': round((total_clicks / total_impressions * 100), 1) if total_impressions else 0,
    }
    chart_labels = [stat['account']['name'] for stat in stats]
    chart_spend = [stat['spend'] for stat in stats]
    chart_revenue = [stat['revenue'] for stat in stats]

    return render_template(
        'dashboard.html',
        stats=stats,
        recent_ads=recent_ads,
        top_ads=top_ads,
        summary=summary_metrics,
        chart_labels=chart_labels,
        chart_spend=chart_spend,
        chart_revenue=chart_revenue,
        accounts=accounts,
    )

@app.route('/accounts/<account_id>/connect-meta', methods=['GET', 'POST'])
@login_required
def connect_meta(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account:
        return redirect(url_for('accounts'))

    if request.method == 'POST':
        access_token = request.form.get('access_token')
        ad_account_id = request.form.get('ad_account_id')
        try:
            connection = connect_meta_account(access_token, ad_account_id)
            account['meta_connected'] = True
            account['meta_access_token'] = access_token
            account['meta_account_id'] = connection.get('account_id')
            account['meta_account_name'] = connection.get('account_name')
            account['meta_last_connected'] = datetime.utcnow().isoformat()
            all_accounts = FileStore.load("accounts", {})
            all_accounts[account_id] = account
            FileStore.save("accounts", all_accounts)
            flash('Meta Ads account connected successfully.', 'success')
            return redirect(url_for('account_detail', account_id=account_id))
        except Exception as exc:
            flash(str(exc), 'danger')

    return render_template('connect_meta.html', account=account)

@app.route('/accounts/<account_id>/sync-meta')
@login_required
def sync_meta(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account or not account.get('meta_connected'):
        flash('Account is not connected to Meta Ads.', 'warning')
        return redirect(url_for('account_detail', account_id=account_id))

    try:
        ads = fetch_meta_ads(account.get('meta_access_token'), account.get('meta_account_id'))
        all_ads = FileStore.load("ads", {})
        for ad in ads:
            all_ads[ad['id']] = {
                'id': ad['id'],
                'account_id': account_id,
                'name': ad['name'],
                'script': ad['script'],
                'impressions': ad['impressions'],
                'clicks': ad['clicks'],
                'spend': ad['spend'],
                'revenue': ad.get('revenue', 0.0),
                'status': ad['status'],
                'created_at': ad.get('created_at', datetime.utcnow().isoformat()),
                'updated_at': datetime.utcnow().isoformat(),
                'external_id': ad.get('external_id')
            }
        FileStore.save("ads", all_ads)
        account['meta_last_synced'] = datetime.utcnow().isoformat()
        FileStore.save("accounts", accounts_data)
        flash(f'Synced {len(ads)} Meta Ads into this account.', 'success')
    except Exception as exc:
        flash(str(exc), 'danger')

    return redirect(url_for('account_detail', account_id=account_id))

@app.route('/ads/<ad_id>')
@login_required
def ad_detail(ad_id):
    ads_data = FileStore.load("ads", {})
    accounts = FileStore.load("accounts", {})
    ad = ads_data.get(ad_id)
    if not ad:
        return redirect(url_for('dashboard'))

    account = accounts.get(ad.get('account_id'), {})
    analysis = analyze_ad_text(ad.get('script', '') or ad.get('name', ''))
    spend = float(ad.get('spend', 0) or 0)
    clicks = float(ad.get('clicks', 0) or 0)
    impressions = float(ad.get('impressions', 0) or 0)
    revenue = float(ad.get('revenue', 0) or 0)
    ctr = round((clicks / impressions * 100), 2) if impressions else 0
    cpc = round((spend / clicks), 2) if clicks else 0

    recommendations = []
    if analysis['awareness_level'] == 'low':
        recommendations.append('This ad is in awareness mode — try adding more clear context for new audiences.')
    elif analysis['awareness_level'] == 'mid':
        recommendations.append('Mid-funnel viewers are ready for comparison and proof; add clarity around value.')
    else:
        recommendations.append('High-awareness creatives convert best with urgency and a strong CTA.')
    if analysis['tone'] == 'urgent':
        recommendations.append('Urgent tone can perform well if you back it with real scarcity or a deadline.')
    if analysis['tone'] == 'friendly':
        recommendations.append('Friendly tone is good for engagement; tighten the CTA to convert more viewers.')
    if not analysis['keywords']:
        recommendations.append('Add a few direct benefit keywords to improve search and social relevance.')

    return render_template(
        'ad_detail.html',
        ad=ad,
        account=account,
        analysis=analysis,
        performance={
            'spend': spend,
            'revenue': revenue,
            'clicks': clicks,
            'impressions': impressions,
            'ctr': ctr,
            'cpc': cpc,
        },
        recommendations=recommendations,
    )

@app.route('/accounts', methods=['GET', 'POST'])
@login_required
def accounts():
    if request.method == 'POST':
        account_data = {
            'id': str(len(FileStore.load("accounts", {})) + 1),
            'name': request.form.get('name'),
            'provider': request.form.get('provider'),
            'created_at': datetime.utcnow().isoformat()
        }
        all_accounts = FileStore.load("accounts", {})
        all_accounts[account_data['id']] = account_data
        FileStore.save("accounts", all_accounts)
        flash('Ad account added.', 'success')
        return redirect(url_for('accounts'))
    
    accounts_data = FileStore.load("accounts", {})
    return render_template('accounts.html', accounts=accounts_data.values())

@app.route('/accounts/<account_id>', methods=['GET', 'POST'])
@login_required
def account_detail(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account:
        return redirect(url_for('accounts'))
    
    if request.method == 'POST':
        ad_data = {
            'id': str(len(FileStore.load("ads", {})) + 1),
            'account_id': account_id,
            'name': request.form.get('name'),
            'script': request.form.get('script'),
            'impressions': request.form.get('impressions', 0),
            'clicks': request.form.get('clicks', 0),
            'spend': request.form.get('spend', 0),
            'revenue': request.form.get('revenue', 0),
            'status': request.form.get('status', 'running'),
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }
        all_ads = FileStore.load("ads", {})
        all_ads[ad_data['id']] = ad_data
        FileStore.save("ads", all_ads)
        flash('Ad saved.', 'success')
        return redirect(url_for('account_detail', account_id=account_id))
    
    def parse_numeric(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    status_filter = request.args.get('status', '')
    search_query = request.args.get('search', '').strip().lower()
    min_spend = parse_numeric(request.args.get('min_spend'), 0.0)
    max_spend = parse_numeric(request.args.get('max_spend'), 99999999.0)

    ads_data = FileStore.load("ads", {})
    account_ads = [ad for ad in ads_data.values() if ad.get('account_id') == account_id]
    filtered_ads = []

    def is_active(ad):
        return str(ad.get('status', '')).lower() == 'running' or str(ad.get('facebook_status', '')).upper() == 'ACTIVE'

    for ad in account_ads:
        if status_filter and ad.get('status') != status_filter:
            continue
        text = f"{ad.get('name', '')} {ad.get('script', '')}".lower()
        if search_query and search_query not in text:
            continue
        spend = parse_numeric(ad.get('spend_usd', ad.get('spend', 0)), 0.0)
        if spend < min_spend or spend > max_spend:
            continue
        filtered_ads.append(ad)

    active_ads = [ad for ad in filtered_ads if is_active(ad)]

    campaign_groups = {}
    country_roas = {}
    total_spend = 0.0
    total_revenue = 0.0
    total_clicks = 0.0
    total_impressions = 0.0

    for ad in active_ads:
        campaign_id = ad.get('campaign_id') or 'uncategorized'
        adset_id = ad.get('adset_id') or f"adset-{ad.get('id')}"
        campaign = campaign_groups.setdefault(campaign_id, {
            'id': campaign_id,
            'name': ad.get('campaign_name', 'Unknown campaign'),
            'budget_usd': ad.get('campaign_budget_usd', 0.0),
            'status': ad.get('facebook_status', ''),
            'adsets': {},
            'spend': 0.0,
            'revenue': 0.0,
            'roas': 0.0,
            'ads_count': 0,
        })

        adset = campaign['adsets'].setdefault(adset_id, {
            'id': adset_id,
            'name': ad.get('adset_name', 'Unknown ad set'),
            'budget_usd': ad.get('adset_budget_usd', 0.0),
            'status': ad.get('facebook_status', ''),
            'ads': [],
            'spend': 0.0,
            'revenue': 0.0,
            'roas': 0.0,
            'ads_count': 0,
        })

        ad_spend = parse_numeric(ad.get('spend_usd', ad.get('spend', 0)), 0.0)
        ad_revenue = parse_numeric(ad.get('revenue', 0), 0.0)
        ad_clicks = parse_numeric(ad.get('clicks', 0), 0.0)
        ad_impressions = parse_numeric(ad.get('impressions', 0), 0.0)
        ad_roas = parse_numeric(ad.get('roas', 0), 0.0)

        ad_record = {
            **ad,
            'spend_usd': ad_spend,
            'ctr': round((ad_clicks / ad_impressions * 100), 2) if ad_impressions else 0,
            'cpc': round((ad_spend / ad_clicks), 2) if ad_clicks else 0,
            'roas': ad_roas,
            'budget_usd': ad.get('adset_budget_usd', 0.0)
        }

        adset['ads'].append(ad_record)
        adset['spend'] += ad_spend
        adset['revenue'] += ad_revenue
        adset['ads_count'] += 1
        if adset['spend']:
            adset['roas'] = round(adset['revenue'] / adset['spend'], 2)

        campaign['spend'] += ad_spend
        campaign['revenue'] += ad_revenue
        campaign['ads_count'] += 1
        if campaign['spend']:
            campaign['roas'] = round(campaign['revenue'] / campaign['spend'], 2)

        total_spend += ad_spend
        total_revenue += ad_revenue
        total_clicks += ad_clicks
        total_impressions += ad_impressions

        for country, value in (ad.get('roas_by_country') or {}).items():
            country_roas.setdefault(country, []).append(parse_numeric(value, 0.0))

    summary = {
        'count': len(active_ads),
        'spend': total_spend,
        'revenue': total_revenue,
        'ctr': round((total_clicks / total_impressions * 100), 1) if total_impressions else 0,
        'cpc': round((total_spend / total_clicks), 2) if total_clicks else 0,
        'roas': round((total_revenue / total_spend), 2) if total_spend else 0,
        'roas_tooltip': ' | '.join([f'{country}: {round(sum(values)/len(values),2)}x' for country, values in country_roas.items()]) or 'ROAS by country unavailable',
        'campaigns': list(campaign_groups.values()),
    }

    return render_template(
        'account_detail.html',
        account=account,
        ads=filtered_ads,
        competitors=account_competitors,
        summary=summary,
        filters={
            'status': status_filter,
            'search': request.args.get('search', ''),
            'min_spend': request.args.get('min_spend', ''),
            'max_spend': request.args.get('max_spend', ''),
        }
    )

@app.route('/accounts/<account_id>/competitors', methods=['GET', 'POST'])
@login_required
def competitors(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account:
        return redirect(url_for('accounts'))
    
    if request.method == 'POST':
        comp_data = {
            'id': str(len(FileStore.load("competitors", {})) + 1),
            'account_id': account_id,
            'name': request.form.get('name'),
            'script': request.form.get('script'),
            'status': request.form.get('status', 'running'),
            'source': request.form.get('source', ''),
            'created_at': datetime.utcnow().isoformat()
        }
        all_competitors = FileStore.load("competitors", {})
        all_competitors[comp_data['id']] = comp_data
        FileStore.save("competitors", all_competitors)
        flash('Competitor ad added.', 'success')
        return redirect(url_for('competitors', account_id=account_id))
    
    competitors_data = FileStore.load("competitors", {})
    account_competitors = [comp for comp in competitors_data.values() if comp.get('account_id') == account_id]
    
    return render_template('competitors.html', account=account, competitors=account_competitors)

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('Admin access required.', 'warning')
        return redirect(url_for('dashboard'))
    users_data = FileStore.load("users", {})
    return render_template('admin_users.html', users=users_data.values())

@app.route('/admin/users/create', methods=['GET', 'POST'])
@login_required
def admin_create_user():
    if not current_user.is_admin:
        flash('Admin access required.', 'warning')
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = request.form.get('is_admin') == 'on'
        
        users_data = FileStore.load("users", {})
        new_id = str(max([int(k) for k in users_data.keys()], default=0) + 1)
        
        users_data[new_id] = {
            'id': new_id,
            'username': username,
            'password_hash': generate_password_hash(password),
            'is_admin': is_admin
        }
        FileStore.save("users", users_data)
        flash('User created successfully.', 'success')
        return redirect(url_for('admin_users'))
    
    return render_template('admin_user_form.html')

@app.route('/admin/users/<user_id>/delete', methods=['POST'])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        flash('Admin access required.', 'warning')
        return redirect(url_for('dashboard'))
    
    if str(user_id) == str(current_user.id):
        flash('You cannot delete your own account.', 'danger')
        return redirect(url_for('admin_users'))
    
    users_data = FileStore.load("users", {})
    if str(user_id) in users_data:
        del users_data[str(user_id)]
        FileStore.save("users", users_data)
        flash('User deleted successfully.', 'success')
    
    return redirect(url_for('admin_users'))

if __name__ == '__main__':
    # Create default admin if needed
    users = FileStore.load("users", {})
    if not users or not any(u.get('username') == 'admin' for u in users.values()):
        users['1'] = {
            'id': '1',
            'username': 'admin',
            'password_hash': generate_password_hash('admin123'),
            'is_admin': True
        }
        FileStore.save("users", users)
    
    app.run(debug=True, host='0.0.0.0', port=5000)
