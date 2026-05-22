from concurrent.futures import ThreadPoolExecutor

from flask import Flask, render_template, redirect, url_for, flash, request, jsonify
from flask_login import (
    LoginManager,
    login_user,
    logout_user,
    login_required,
    current_user,
    UserMixin,
)
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from storage import FileStore
from services.ad_provider import (
    connect_meta_account,
    fetch_meta_ads,
    fetch_meta_account_insights,
    fetch_meta_video_media,
)
from analysis import analyze_ad_text
from treatment import enrich_ad, enrich_ads, fx_rate, FX_RATES_TO_USD
import insights as insights_mod

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key-change-in-production"

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"


@app.context_processor
def inject_display_currencies():
    cad_to_usd = FX_RATES_TO_USD.get("CAD") or 1.0
    return {
        "display_currencies": {
            "USD": {"symbol": "$", "rate_from_usd": 1.0},
            "CAD": {"symbol": "C$", "rate_from_usd": round(1.0 / cad_to_usd, 6)},
        },
        "default_display_currency": "USD",
    }


def needs_sync(account, minutes=30):
    if not account or not account.get("meta_connected"):
        return False
    last_synced = account.get("meta_last_synced")
    if not last_synced:
        return True
    try:
        last_synced_dt = datetime.fromisoformat(last_synced)
    except (TypeError, ValueError):
        return True
    return (datetime.utcnow() - last_synced_dt).total_seconds() > minutes * 60


def build_meta_ad_record(account_id, ad):
    """Persist only raw provider data. Currency conversion and derived metrics
    are computed at page-render time by `treatment.enrich_ad`, so fixing a bug
    in that layer doesn't require re-syncing."""
    return {
        "id": ad["id"],
        "external_id": ad.get("external_id"),
        "account_id": account_id,
        "name": ad.get("name", ""),
        "script": ad.get("script", ""),
        "impressions": ad.get("impressions", 0),
        "clicks": ad.get("clicks", 0),
        "spend": ad.get("spend", 0),
        "currency": ad.get("currency", "USD"),
        "roas": ad.get("roas", 0.0),
        "actions": ad.get("actions") or [],
        "frequency": ad.get("frequency"),
        "status": ad.get("status", ""),
        "facebook_status": ad.get("facebook_status", ad.get("status", "")),
        "campaign_id": ad.get("campaign_id"),
        "campaign_name": ad.get("campaign_name"),
        "campaign_budget": ad.get("campaign_budget", 0),
        "adset_id": ad.get("adset_id"),
        "adset_name": ad.get("adset_name"),
        "adset_budget": ad.get("adset_budget", 0),
        "creative_type": ad.get("creative_type", ""),
        "image_url": ad.get("image_url"),
        "thumbnail_url": ad.get("thumbnail_url"),
        "video_id": ad.get("video_id"),
        "roas_by_country": ad.get("roas_by_country", {}),
        "created_at": ad.get("created_at", datetime.utcnow().isoformat()),
        "updated_at": datetime.utcnow().isoformat(),
    }


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
            return User(
                user_data["id"],
                user_data["username"],
                user_data["password_hash"],
                user_data.get("is_admin", False),
            )
        return None

    @staticmethod
    def get_by_username(username):
        users = FileStore.load("users", {})
        for user_id, user_data in users.items():
            if user_data["username"] == username:
                return User(
                    user_data["id"],
                    user_data["username"],
                    user_data["password_hash"],
                    user_data.get("is_admin", False),
                )
        return None


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        user = User.get_by_username(username)
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    accounts = FileStore.load("accounts", {})
    ads_data = FileStore.load("ads", {})
    all_ads = enrich_ads(ads_data.values())

    for account in accounts.values():
        account["sync_due"] = needs_sync(account)

    stats = []
    total_spend = 0.0
    total_clicks = 0.0
    total_impressions = 0.0
    active_ads = 0

    for account_id, account in accounts.items():
        account_ads = [ad for ad in all_ads if ad.get("account_id") == account_id]
        account_spend = sum(ad["spend_usd"] for ad in account_ads)
        account_revenue = sum(ad["revenue_usd"] for ad in account_ads)
        account_clicks = sum(ad["clicks"] for ad in account_ads)
        account_impressions = sum(ad["impressions"] for ad in account_ads)
        account_roi = (
            round(((account_revenue - account_spend) / account_spend * 100), 1)
            if account_spend
            else 0
        )
        account_ctr = (
            round((account_clicks / account_impressions * 100), 1)
            if account_impressions
            else 0
        )
        account_cpc = (
            round((account_spend / account_clicks), 2) if account_clicks else 0
        )

        stats.append(
            {
                "account": account,
                "ads": account_ads,
                "spend": account_spend,
                "revenue": account_revenue,
                "roi": account_roi,
                "ctr": account_ctr,
                "avg_cpc": account_cpc,
            }
        )

        total_spend += account_spend
        total_clicks += account_clicks
        total_impressions += account_impressions
        active_ads += sum(1 for ad in account_ads if ad.get("status") == "running")

    recent_ads = sorted(all_ads, key=lambda x: x.get("updated_at", ""), reverse=True)[
        :6
    ]
    for ad in recent_ads:
        ad["account_name"] = accounts.get(ad.get("account_id"), {}).get(
            "name", "Unknown"
        )

    top_ads = sorted(all_ads, key=lambda ad: ad["spend_usd"], reverse=True)[:5]
    summary_metrics = {
        "accounts": len(accounts),
        "ads": len(all_ads),
        "spend": total_spend,
        "active_ads": active_ads,
        "ctr": round((total_clicks / total_impressions * 100), 1)
        if total_impressions
        else 0,
    }
    chart_labels = [stat["account"]["name"] for stat in stats]
    chart_spend = [stat["spend"] for stat in stats]
    chart_revenue = [stat["revenue"] for stat in stats]

    return render_template(
        "dashboard.html",
        stats=stats,
        recent_ads=recent_ads,
        top_ads=top_ads,
        summary=summary_metrics,
        chart_labels=chart_labels,
        chart_spend=chart_spend,
        chart_revenue=chart_revenue,
        accounts=accounts,
        dashboard_sync_url=url_for("dashboard_sync_meta"),
        dashboard_auto_sync=any(
            account.get("sync_due") for account in accounts.values()
        ),
    )


@app.route("/dashboard-sync-meta")
@login_required
def dashboard_sync_meta():
    accounts = FileStore.load("accounts", {})
    ads_data = FileStore.load("ads", {})
    synced_accounts = []
    errors = []
    auto = request.args.get("auto") == "1"

    for account_id, account in accounts.items():
        if not account.get("meta_connected"):
            continue
        if auto and not needs_sync(account):
            continue
        try:
            ads = fetch_meta_ads(
                account.get("meta_access_token"), account.get("meta_account_id")
            )
            for ad in ads:
                ads_data[ad["id"]] = build_meta_ad_record(account_id, ad)
            if ads:
                account["meta_currency"] = ads[0].get("currency", "USD")
            account["meta_last_synced"] = datetime.utcnow().isoformat()
            synced_accounts.append({"account_id": account_id, "count": len(ads)})
        except Exception as exc:
            errors.append({"account_id": account_id, "message": str(exc)})

    FileStore.save("ads", ads_data)
    FileStore.save("accounts", accounts)

    if request.args.get("ajax") == "1":
        return jsonify(
            success=len(errors) == 0,
            synced_accounts=synced_accounts,
            errors=errors,
            last_synced=datetime.utcnow().isoformat(),
        )

    if errors:
        flash(
            "Some accounts failed to sync: "
            + "; ".join([err["message"] for err in errors]),
            "danger",
        )
    elif synced_accounts:
        flash(
            f'Synced {sum(item["count"] for item in synced_accounts)} Meta Ads across {len(synced_accounts)} account(s).',
            "success",
        )
    else:
        flash("No accounts required sync.", "info")

    return redirect(url_for("dashboard"))


@app.route("/accounts/<account_id>/connect-meta", methods=["GET", "POST"])
@login_required
def connect_meta(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account:
        return redirect(url_for("accounts"))

    form_token = account.get("meta_access_token", "")
    form_account_id = account.get("meta_account_id", "")

    if request.method == "POST":
        access_token = request.form.get("access_token")
        ad_account_id = request.form.get("ad_account_id")
        form_token = access_token or form_token
        form_account_id = ad_account_id or form_account_id
        try:
            connection = connect_meta_account(access_token, ad_account_id)
            account["meta_connected"] = True
            account["meta_access_token"] = access_token
            account["meta_account_id"] = connection.get("account_id")
            account["meta_account_name"] = connection.get("account_name")
            account["meta_currency"] = connection.get("currency", "USD")
            account["meta_last_connected"] = datetime.utcnow().isoformat()
            all_accounts = FileStore.load("accounts", {})
            all_accounts[account_id] = account
            FileStore.save("accounts", all_accounts)
            flash("Meta Ads account connected successfully.", "success")
            return redirect(url_for("account_detail", account_id=account_id))
        except Exception as exc:
            flash(str(exc), "danger")

    return render_template(
        "connect_meta.html",
        account=account,
        form_token=form_token,
        form_account_id=form_account_id,
    )


@app.route("/accounts/<account_id>/sync-meta")
@login_required
def sync_meta(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account or not account.get("meta_connected"):
        message = "Account is not connected to Meta Ads."
        if request.args.get("ajax") == "1":
            return jsonify(success=False, message=message), 400
        flash(message, "warning")
        return redirect(url_for("account_detail", account_id=account_id))

    try:
        ads = fetch_meta_ads(
            account.get("meta_access_token"), account.get("meta_account_id")
        )
        all_ads = FileStore.load("ads", {})
        for ad in ads:
            all_ads[ad["id"]] = build_meta_ad_record(account_id, ad)
        if ads:
            account["meta_currency"] = ads[0].get("currency", "USD")
        FileStore.save("ads", all_ads)
        account["meta_last_synced"] = datetime.utcnow().isoformat()
        accounts_data[account_id] = account
        FileStore.save("accounts", accounts_data)
        message = f"Synced {len(ads)} Meta Ads into this account."
        if request.args.get("ajax") == "1":
            return jsonify(
                success=True,
                message=message,
                synced_count=len(ads),
                last_synced=account["meta_last_synced"],
            )
        flash(message, "success")
    except Exception as exc:
        if request.args.get("ajax") == "1":
            return jsonify(success=False, message=str(exc)), 500
        flash(str(exc), "danger")

    return redirect(url_for("account_detail", account_id=account_id))


@app.route("/ads/<ad_id>")
@login_required
def ad_detail(ad_id):
    ads_data = FileStore.load("ads", {})
    accounts = FileStore.load("accounts", {})
    raw_ad = ads_data.get(ad_id)
    if not raw_ad:
        return redirect(url_for("dashboard"))

    ad = enrich_ad(raw_ad)
    account = accounts.get(ad.get("account_id"), {})

    if ad.get("video_id") and account.get("meta_access_token"):
        video_media = fetch_meta_video_media(
            ad["video_id"], account["meta_access_token"]
        )
        ad["video_source_url"] = video_media.get("source")
        if not ad.get("thumbnail_url"):
            ad["thumbnail_url"] = video_media.get("picture")

    analysis = analyze_ad_text(ad.get("script", "") or ad.get("name", ""))

    recommendations = []
    if analysis["awareness_level"] == "low":
        recommendations.append(
            "This ad is in awareness mode — try adding more clear context for new audiences."
        )
    elif analysis["awareness_level"] == "mid":
        recommendations.append(
            "Mid-funnel viewers are ready for comparison and proof; add clarity around value."
        )
    else:
        recommendations.append(
            "High-awareness creatives convert best with urgency and a strong CTA."
        )
    if analysis["tone"] == "urgent":
        recommendations.append(
            "Urgent tone can perform well if you back it with real scarcity or a deadline."
        )
    if analysis["tone"] == "friendly":
        recommendations.append(
            "Friendly tone is good for engagement; tighten the CTA to convert more viewers."
        )
    if not analysis["keywords"]:
        recommendations.append(
            "Add a few direct benefit keywords to improve search and social relevance."
        )

    return render_template(
        "ad_detail.html",
        ad=ad,
        account=account,
        analysis=analysis,
        performance={
            "spend": ad["spend_usd"],
            "revenue": ad["revenue_usd"],
            "clicks": ad["clicks"],
            "impressions": ad["impressions"],
            "ctr": ad["ctr"],
            "cpc": ad["cpc_usd"],
            "purchases": ad.get("purchases", 0),
            "roas": ad.get("roas", 0.0),
        },
        recommendations=recommendations,
    )


@app.route("/accounts", methods=["GET", "POST"])
@login_required
def accounts():
    if request.method == "POST":
        account_data = {
            "id": str(len(FileStore.load("accounts", {})) + 1),
            "name": request.form.get("name"),
            "provider": request.form.get("provider"),
            "created_at": datetime.utcnow().isoformat(),
        }
        all_accounts = FileStore.load("accounts", {})
        all_accounts[account_data["id"]] = account_data
        FileStore.save("accounts", all_accounts)
        flash("Ad account added.", "success")
        return redirect(url_for("accounts"))

    accounts_data = FileStore.load("accounts", {})
    return render_template("accounts.html", accounts=accounts_data.values())


@app.route("/accounts/<account_id>", methods=["GET"])
@login_required
def account_detail(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account:
        return redirect(url_for("accounts"))

    account["sync_due"] = needs_sync(account)
    account_sync_url = url_for("sync_meta", account_id=account_id)

    def parse_numeric(value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    status_filter = request.args.get("status", "")
    search_query = request.args.get("search", "").strip().lower()
    min_spend = parse_numeric(request.args.get("min_spend"), 0.0)
    max_spend = parse_numeric(request.args.get("max_spend"), 99999999.0)

    ads_data = FileStore.load("ads", {})
    account_ads = enrich_ads(
        ad for ad in ads_data.values() if ad.get("account_id") == account_id
    )
    filtered_ads = []

    def is_active(ad):
        return (
            str(ad.get("status", "")).lower() == "running"
            or str(ad.get("facebook_status", "")).upper() == "ACTIVE"
        )

    for ad in account_ads:
        if status_filter and ad.get("status") != status_filter:
            continue
        text = f"{ad.get('name', '')} {ad.get('script', '')}".lower()
        if search_query and search_query not in text:
            continue
        if ad["spend_usd"] < min_spend or ad["spend_usd"] > max_spend:
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
        campaign_id = ad.get("campaign_id") or "uncategorized"
        adset_id = ad.get("adset_id") or f"adset-{ad.get('id')}"
        campaign = campaign_groups.setdefault(
            campaign_id,
            {
                "id": campaign_id,
                "name": ad.get("campaign_name", "Unknown campaign"),
                "budget_usd": ad.get("campaign_budget_usd", 0.0),
                "status": ad.get("facebook_status", ""),
                "adsets": {},
                "spend": 0.0,
                "revenue": 0.0,
                "roas": 0.0,
                "purchases": 0,
                "ads_count": 0,
            },
        )

        adset = campaign["adsets"].setdefault(
            adset_id,
            {
                "id": adset_id,
                "name": ad.get("adset_name", "Unknown ad set"),
                "budget_usd": ad.get("adset_budget_usd", 0.0),
                "status": ad.get("facebook_status", ""),
                "ads": [],
                "spend": 0.0,
                "revenue": 0.0,
                "roas": 0.0,
                "purchases": 0,
                "ads_count": 0,
            },
        )

        ad_record = {**ad, "budget_usd": ad.get("adset_budget_usd", 0.0)}

        adset["ads"].append(ad_record)
        adset["spend"] += ad["spend_usd"]
        adset["revenue"] += ad["revenue_usd"]
        adset["purchases"] += ad.get("purchases", 0)
        adset["ads_count"] += 1
        if adset["spend"]:
            adset["roas"] = round(adset["revenue"] / adset["spend"], 2)

        campaign["spend"] += ad["spend_usd"]
        campaign["revenue"] += ad["revenue_usd"]
        campaign["purchases"] += ad.get("purchases", 0)
        campaign["ads_count"] += 1
        if campaign["spend"]:
            campaign["roas"] = round(campaign["revenue"] / campaign["spend"], 2)

        total_spend += ad["spend_usd"]
        total_revenue += ad["revenue_usd"]
        total_clicks += ad["clicks"]
        total_impressions += ad["impressions"]

        for country, value in (ad.get("roas_by_country") or {}).items():
            country_roas.setdefault(country, []).append(parse_numeric(value, 0.0))

    summary = {
        "count": len(active_ads),
        "spend": total_spend,
        "revenue": total_revenue,
        "ctr": round((total_clicks / total_impressions * 100), 1)
        if total_impressions
        else 0,
        "cpc": round((total_spend / total_clicks), 2) if total_clicks else 0,
        "roas": round((total_revenue / total_spend), 2) if total_spend else 0,
        "roas_tooltip": " | ".join(
            [
                f"{country}: {round(sum(values)/len(values),2)}x"
                for country, values in country_roas.items()
            ]
        )
        or "ROAS by country unavailable",
        "campaigns": list(campaign_groups.values()),
    }

    competitors_data = FileStore.load("competitors", {})
    account_competitors = [
        comp
        for comp in competitors_data.values()
        if comp.get("account_id") == account_id
    ]

    return render_template(
        "account_detail.html",
        account=account,
        ads=filtered_ads,
        competitors=account_competitors,
        summary=summary,
        filters={
            "status": status_filter,
            "search": request.args.get("search", ""),
            "min_spend": request.args.get("min_spend", ""),
            "max_spend": request.args.get("max_spend", ""),
        },
        account_sync_url=account_sync_url,
        account_auto_sync=account["sync_due"],
    )


@app.route("/accounts/<account_id>/competitors", methods=["GET", "POST"])
@login_required
def competitors(account_id):
    accounts_data = FileStore.load("accounts", {})
    account = accounts_data.get(account_id)
    if not account:
        return redirect(url_for("accounts"))

    if request.method == "POST":
        comp_data = {
            "id": str(len(FileStore.load("competitors", {})) + 1),
            "account_id": account_id,
            "name": request.form.get("name"),
            "script": request.form.get("script"),
            "status": request.form.get("status", "running"),
            "source": request.form.get("source", ""),
            "created_at": datetime.utcnow().isoformat(),
        }
        all_competitors = FileStore.load("competitors", {})
        all_competitors[comp_data["id"]] = comp_data
        FileStore.save("competitors", all_competitors)
        flash("Competitor ad added.", "success")
        return redirect(url_for("competitors", account_id=account_id))

    competitors_data = FileStore.load("competitors", {})
    account_competitors = [
        comp
        for comp in competitors_data.values()
        if comp.get("account_id") == account_id
    ]

    return render_template(
        "competitors.html", account=account, competitors=account_competitors
    )


@app.route("/admin/users")
@login_required
def admin_users():
    if not current_user.is_admin:
        flash("Admin access required.", "warning")
        return redirect(url_for("dashboard"))
    users_data = FileStore.load("users", {})
    return render_template("admin_users.html", users=users_data.values())


@app.route("/admin/users/create", methods=["GET", "POST"])
@login_required
def admin_create_user():
    if not current_user.is_admin:
        flash("Admin access required.", "warning")
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        is_admin = request.form.get("is_admin") == "on"

        users_data = FileStore.load("users", {})
        new_id = str(max([int(k) for k in users_data.keys()], default=0) + 1)

        users_data[new_id] = {
            "id": new_id,
            "username": username,
            "password_hash": generate_password_hash(password),
            "is_admin": is_admin,
        }
        FileStore.save("users", users_data)
        flash("User created successfully.", "success")
        return redirect(url_for("admin_users"))

    return render_template("admin_user_form.html")


@app.route("/admin/users/<user_id>/delete", methods=["POST"])
@login_required
def admin_delete_user(user_id):
    if not current_user.is_admin:
        flash("Admin access required.", "warning")
        return redirect(url_for("dashboard"))

    if str(user_id) == str(current_user.id):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_users"))

    users_data = FileStore.load("users", {})
    if str(user_id) in users_data:
        del users_data[str(user_id)]
        FileStore.save("users", users_data)
        flash("User deleted successfully.", "success")

    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

BREAKDOWN_SPECS = [
    ("country", ("country",), None),
    ("placement", ("publisher_platform", "platform_position"), None),
    ("device", ("impression_device",), None),
    ("demographics", ("age", "gender"), None),
    ("timeseries", (), "1"),
    ("hourly", ("hourly_stats_aggregated_by_advertiser_time_zone",), None),
]


def _connected_accounts(accounts, scope_account_id=None):
    if scope_account_id:
        account = accounts.get(scope_account_id)
        if account and account.get("meta_connected") and account.get("meta_access_token"):
            return {scope_account_id: account}
        return {}
    return {
        aid: a for aid, a in accounts.items()
        if a.get("meta_connected") and a.get("meta_access_token")
    }


def _fetch_breakdowns_parallel(accounts_map, date_preset):
    """Run all breakdown fetches for all connected accounts in parallel.

    Returns dict keyed by breakdown name (country, placement, ...) holding the
    concatenated raw rows from every account.
    """
    by_breakdown = {name: [] for name, _, _ in BREAKDOWN_SPECS}
    if not accounts_map:
        return by_breakdown

    jobs = []
    for account_id, account in accounts_map.items():
        token = account.get("meta_access_token")
        meta_account_id = account.get("meta_account_id") or account_id
        currency = (account.get("meta_currency") or "USD").upper()
        usd_rate = fx_rate(currency)
        for name, breakdowns, time_increment in BREAKDOWN_SPECS:
            jobs.append((name, token, meta_account_id, breakdowns, time_increment, currency, usd_rate))

    def run(job):
        name, token, meta_account_id, breakdowns, time_increment, currency, usd_rate = job
        rows = fetch_meta_account_insights(
            access_token=token,
            account_id=meta_account_id,
            breakdowns=list(breakdowns) if breakdowns else None,
            time_increment=time_increment,
            date_preset=date_preset,
            currency=currency,
            usd_rate=usd_rate,
        )
        return name, rows

    with ThreadPoolExecutor(max_workers=min(8, len(jobs) or 1)) as ex:
        for name, rows in ex.map(run, jobs):
            by_breakdown[name].extend(rows)

    return by_breakdown


def _build_analytics_context(scope_account_id=None):
    accounts = FileStore.load("accounts", {})
    ads_data = FileStore.load("ads", {})

    if scope_account_id:
        scope_account = accounts.get(scope_account_id)
        if not scope_account:
            return None
        ads_iterable = (a for a in ads_data.values() if a.get("account_id") == scope_account_id)
    else:
        scope_account = None
        ads_iterable = ads_data.values()

    ads = enrich_ads(ads_iterable)
    date_preset = insights_mod.resolve_range(request.args.get("range", insights_mod.DEFAULT_RANGE))
    connected = _connected_accounts(accounts, scope_account_id)
    breakdowns = _fetch_breakdowns_parallel(connected, date_preset)

    account_rows = insights_mod.account_scorecard(ads, accounts)
    campaign_rows = insights_mod.campaign_leaderboard(ads, accounts)
    creative_rows = insights_mod.creative_leaderboard(ads, accounts)
    funnel = insights_mod.funnel_metrics(ads)
    distribution = insights_mod.spend_distribution(ads, accounts)
    status_data = insights_mod.status_mix(ads)
    creative_type_data = insights_mod.creative_type_mix(ads)
    editor_rows = insights_mod.editor_breakdown(ads)
    outliers = insights_mod.detect_outliers(ads, accounts, account_rows)

    country = insights_mod.aggregate_country(breakdowns["country"])
    placement = insights_mod.aggregate_placement(breakdowns["placement"])
    device = insights_mod.aggregate_device(breakdowns["device"])
    demographics = insights_mod.demographics_matrix(
        insights_mod.aggregate_demographics(breakdowns["demographics"])
    )
    timeseries = insights_mod.timeseries_chart(
        insights_mod.aggregate_timeseries(breakdowns["timeseries"])
    )
    hourly = insights_mod.hourly_matrix(insights_mod.aggregate_hourly(breakdowns["hourly"]))
    scatter = insights_mod.frequency_scatter(ads)

    return {
        "scope_account": scope_account,
        "accounts": accounts,
        "connected_count": len(connected),
        "date_ranges": insights_mod.DATE_RANGES,
        "date_preset": date_preset,
        "totals": {
            "ad_accounts": len({ad.get("account_id") for ad in ads}),
            "ads": len(ads),
            "spend": sum(a.get("spend_usd", 0) for a in ads),
            "revenue": sum(a.get("revenue_usd", 0) for a in ads),
            "purchases": sum(a.get("purchases", 0) for a in ads),
            "clicks": sum(int(a.get("clicks", 0) or 0) for a in ads),
            "impressions": sum(int(a.get("impressions", 0) or 0) for a in ads),
        },
        "account_rows": account_rows,
        "campaign_rows": campaign_rows,
        "creative_rows": creative_rows,
        "funnel": funnel,
        "distribution": distribution,
        "status_mix": status_data,
        "creative_type_mix": creative_type_data,
        "editor_rows": editor_rows,
        "outliers": outliers,
        "country": country,
        "placement": placement,
        "device": device,
        "demographics": demographics,
        "timeseries": timeseries,
        "hourly": hourly,
        "scatter": scatter,
    }


@app.route("/analytics")
@login_required
def analytics():
    context = _build_analytics_context()
    if context is None:
        return redirect(url_for("dashboard"))
    return render_template("analytics.html", **context)


@app.route("/accounts/<account_id>/analytics")
@login_required
def account_analytics(account_id):
    context = _build_analytics_context(scope_account_id=account_id)
    if context is None:
        return redirect(url_for("accounts"))
    return render_template("analytics.html", **context)


@app.route("/analytics/compare")
@login_required
def analytics_compare():
    ad_ids = [aid for aid in request.args.getlist("ad") if aid]
    ads_data = FileStore.load("ads", {})
    accounts = FileStore.load("accounts", {})

    selected = []
    for aid in ad_ids[:4]:
        raw = ads_data.get(aid)
        if not raw:
            continue
        ad = enrich_ad(raw)
        ad["account_name"] = accounts.get(ad.get("account_id"), {}).get("name", "Unknown")
        selected.append(ad)

    all_ads_enriched = enrich_ads(ads_data.values())
    pickable = [
        {
            "id": ad["id"],
            "name": ad.get("name", ""),
            "account_name": accounts.get(ad.get("account_id"), {}).get("name", "Unknown"),
            "thumbnail_url": ad.get("thumbnail_url") or ad.get("image_url"),
            "spend_usd": ad.get("spend_usd", 0),
            "roas": ad.get("roas", 0),
            "purchases": ad.get("purchases", 0),
        }
        for ad in sorted(all_ads_enriched, key=lambda a: a.get("spend_usd", 0), reverse=True)[:40]
    ]

    return render_template(
        "analytics_compare.html",
        selected=selected,
        pickable=pickable,
    )


if __name__ == "__main__":
    # Create default admin if needed
    users = FileStore.load("users", {})
    if not users or not any(u.get("username") == "admin" for u in users.values()):
        users["1"] = {
            "id": "1",
            "username": "admin",
            "password_hash": generate_password_hash("admin123"),
            "is_admin": True,
        }
        FileStore.save("users", users)

    app.run(debug=True, host="0.0.0.0", port=5000)
