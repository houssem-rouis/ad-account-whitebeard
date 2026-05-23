import os
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv

load_dotenv()

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
from crypto import encrypt_token, get_account_token
from services.ad_provider import (
    connect_meta_account,
    fetch_meta_ads,
    fetch_meta_account_insights,
    fetch_meta_video_media,
)
from analysis import analyze_ad_text
from services.transcribe import transcribe_video
from services.copywriter import analyze_copy
from services.strategist import build_strategist_report
from treatment import enrich_ad, enrich_ads, fx_rate, FX_RATES_TO_USD
import insights as insights_mod

# Background workers for video transcription (slow: 10s–2min per ad). Keep
# small so a burst of transcribe clicks doesn't exhaust the web dyno.
_TRANSCRIBE_EXECUTOR = ThreadPoolExecutor(max_workers=2)
_TRANSCRIBE_LOCK = threading.Lock()
# Single-worker pool for the account-wide strategist report so two clicks
# can't kick off duplicate Whisper + Claude bills.
_REPORT_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_REPORT_LOCK = threading.Lock()

app = Flask(__name__)
# In production, SECRET_KEY must be set via env var. For local dev we fall back
# to an ephemeral key (sessions don't survive restarts, which is fine locally).
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

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


def build_meta_ad_record(account_id, ad, existing=None):
    """Persist only raw provider data. Currency conversion and derived metrics
    are computed at page-render time by `treatment.enrich_ad`, so fixing a bug
    in that layer doesn't require re-syncing.

    `existing` is the previously stored record (if any). Transcript fields are
    carried over so a re-sync doesn't erase work the user already paid Whisper
    for.
    """
    existing = existing or {}
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
        "transcript": existing.get("transcript"),
        "transcript_status": existing.get("transcript_status"),
        "transcript_error": existing.get("transcript_error"),
        "copy_analysis": existing.get("copy_analysis"),
        "copy_analysis_status": existing.get("copy_analysis_status"),
        "copy_analysis_error": existing.get("copy_analysis_error"),
        "created_at": ad.get("created_at", datetime.utcnow().isoformat()),
        "updated_at": datetime.utcnow().isoformat(),
    }


# User model
class User(UserMixin):
    def __init__(self, id, username, password_hash, is_admin=False,
                 can_launch_analysis=False, can_view_tokens=False,
                 allowed_account_ids=None):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.is_admin = is_admin
        # Permissions. Admins implicitly have all three regardless of the
        # stored flag, so a misconfiguration never locks the owner out.
        self.can_launch_analysis = bool(can_launch_analysis) or bool(is_admin)
        self.can_view_tokens = bool(can_view_tokens) or bool(is_admin)
        # Empty list = no accounts (for non-admins). Admins see everything
        # regardless of this list. `None`/missing is treated as empty.
        self.allowed_account_ids = list(allowed_account_ids or [])

    def can_access_account(self, account_id):
        if self.is_admin:
            return True
        return str(account_id) in {str(a) for a in self.allowed_account_ids}

    def allowed_accounts(self, accounts_dict):
        """Filter the global accounts dict down to the ones this user may
        see. Admins get the whole dict back unchanged."""
        if self.is_admin:
            return accounts_dict
        allowed = {str(a) for a in self.allowed_account_ids}
        return {aid: acc for aid, acc in accounts_dict.items() if str(aid) in allowed}

    @staticmethod
    def _build(data):
        return User(
            data["id"],
            data["username"],
            data["password_hash"],
            data.get("is_admin", False),
            data.get("can_launch_analysis", False),
            data.get("can_view_tokens", False),
            data.get("allowed_account_ids", []),
        )

    @staticmethod
    def get(user_id):
        users = FileStore.load("users", {})
        user_data = users.get(str(user_id))
        return User._build(user_data) if user_data else None

    @staticmethod
    def get_by_username(username):
        users = FileStore.load("users", {})
        for user_data in users.values():
            if user_data["username"] == username:
                return User._build(user_data)
        return None


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


def _require_account_html(account_id):
    """For HTML routes: returns (account_dict, None) on success, or
    (None, redirect) on missing-account / forbidden so the caller can just
    `return redirect_response`."""
    accounts = FileStore.load("accounts", {})
    account = accounts.get(account_id)
    if not account:
        return None, redirect(url_for("accounts"))
    if not current_user.can_access_account(account_id):
        flash("You don't have access to that account.", "danger")
        return None, redirect(url_for("dashboard"))
    return account, None


def _require_account_json(account_id):
    """For JSON routes: returns (account_dict, None) or (None, response)."""
    accounts = FileStore.load("accounts", {})
    account = accounts.get(account_id)
    if not account:
        return None, (jsonify(success=False, message="Account not found."), 404)
    if not current_user.can_access_account(account_id):
        return None, (jsonify(success=False, message="Forbidden."), 403)
    return account, None


@app.context_processor
def inject_user_permissions():
    """Make permission flags available in every template without each route
    having to pass them."""
    if current_user.is_authenticated:
        return {
            "user_can_launch_analysis": current_user.can_launch_analysis,
            "user_can_view_tokens": current_user.can_view_tokens,
        }
    return {"user_can_launch_analysis": False, "user_can_view_tokens": False}


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
    accounts = current_user.allowed_accounts(FileStore.load("accounts", {}))
    ads_data = FileStore.load("ads", {})
    if not current_user.is_admin:
        # Hide ads from accounts the user can't see.
        ads_data = {aid: ad for aid, ad in ads_data.items() if ad.get("account_id") in accounts}
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
        if not current_user.can_access_account(account_id):
            continue
        if auto and not needs_sync(account):
            continue
        try:
            ads = fetch_meta_ads(
                get_account_token(account), account.get("meta_account_id")
            )
            for ad in ads:
                ads_data[ad["id"]] = build_meta_ad_record(
                    account_id, ad, existing=ads_data.get(ad["id"])
                )
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
    account, err = _require_account_html(account_id)
    if err:
        return err
    accounts_data = FileStore.load("accounts", {})

    form_token = get_account_token(account) if current_user.can_view_tokens else ""
    form_account_id = account.get("meta_account_id", "")

    if request.method == "POST":
        if not current_user.can_view_tokens:
            flash("You don't have permission to edit Meta credentials.", "danger")
            return redirect(url_for("connect_meta", account_id=account_id))
        access_token = request.form.get("access_token")
        ad_account_id = request.form.get("ad_account_id")
        form_token = access_token or form_token
        form_account_id = ad_account_id or form_account_id
        try:
            connection = connect_meta_account(access_token, ad_account_id)
            account["meta_connected"] = True
            account["meta_access_token"] = encrypt_token(access_token)
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


@app.route("/accounts/<account_id>/rename", methods=["POST"])
@login_required
def rename_account(account_id):
    if not current_user.is_admin:
        return jsonify(success=False, message="Admin access required."), 403
    payload = request.get_json(silent=True) or {}
    new_name = (request.form.get("name") or payload.get("name") or "").strip()
    if not new_name:
        return jsonify(success=False, message="Name cannot be empty."), 400
    if len(new_name) > 200:
        return jsonify(success=False, message="Name too long (max 200 chars)."), 400
    accounts = FileStore.load("accounts", {})
    if account_id not in accounts:
        return jsonify(success=False, message="Account not found."), 404
    accounts[account_id]["name"] = new_name
    FileStore.save("accounts", accounts)
    return jsonify(success=True, name=new_name)


@app.route("/accounts/<account_id>/sync-meta")
@login_required
def sync_meta(account_id):
    if not current_user.can_access_account(account_id):
        if request.args.get("ajax") == "1":
            return jsonify(success=False, message="Forbidden."), 403
        flash("You don't have access to that account.", "danger")
        return redirect(url_for("dashboard"))
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
            get_account_token(account), account.get("meta_account_id")
        )
        all_ads = FileStore.load("ads", {})
        for ad in ads:
            all_ads[ad["id"]] = build_meta_ad_record(
                account_id, ad, existing=all_ads.get(ad["id"])
            )
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


def _update_ad_fields(ad_id, fields):
    """Read-modify-write a single ad record under a lock to avoid losing
    concurrent updates from the transcription worker thread."""
    with _TRANSCRIBE_LOCK:
        ads_data = FileStore.load("ads", {})
        record = ads_data.get(ad_id)
        if not record:
            return None
        record.update(fields)
        record["updated_at"] = datetime.utcnow().isoformat()
        ads_data[ad_id] = record
        FileStore.save("ads", ads_data)
        return record


def _run_copy_analysis_job(ad_id):
    """Pull the latest text for the ad and run the Claude copywriting audit."""
    ads_data = FileStore.load("ads", {})
    ad = ads_data.get(ad_id)
    if not ad:
        return
    text = (ad.get("transcript") or ad.get("script") or "").strip()
    if not text:
        _update_ad_fields(
            ad_id,
            {
                "copy_analysis_status": "no_text",
                "copy_analysis_error": "No transcript or script available to analyze.",
            },
        )
        return
    _update_ad_fields(
        ad_id, {"copy_analysis_status": "pending", "copy_analysis_error": None}
    )
    try:
        result = analyze_copy(
            text,
            ad_context={
                "name": ad.get("name"),
                "campaign_name": ad.get("campaign_name"),
                "creative_type": ad.get("creative_type"),
                "roas": ad.get("roas"),
            },
        )
        _update_ad_fields(
            ad_id,
            {
                "copy_analysis": result,
                "copy_analysis_status": "done",
                "copy_analysis_error": None,
            },
        )
    except Exception as exc:
        _update_ad_fields(
            ad_id,
            {
                "copy_analysis_status": "failed",
                "copy_analysis_error": str(exc)[:500],
            },
        )


def _run_transcription_job(ad_id, video_url):
    try:
        transcript = transcribe_video(video_url)
        if transcript:
            _update_ad_fields(
                ad_id,
                {
                    "transcript": transcript,
                    "transcript_status": "done",
                    "transcript_error": None,
                },
            )
            # Chain the copywriting audit on the fresh transcript so the user
            # doesn't have to click twice.
            _TRANSCRIBE_EXECUTOR.submit(_run_copy_analysis_job, ad_id)
        else:
            _update_ad_fields(
                ad_id,
                {
                    "transcript": None,
                    "transcript_status": "no_audio",
                    "transcript_error": None,
                },
            )
    except Exception as exc:
        _update_ad_fields(
            ad_id,
            {
                "transcript_status": "failed",
                "transcript_error": str(exc)[:500],
            },
        )


@app.route("/ads/<ad_id>/analyze-copy", methods=["POST"])
@login_required
def analyze_copy_route(ad_id):
    if not current_user.can_launch_analysis:
        return jsonify(success=False, message="You don't have permission to launch analysis."), 403
    ads_data = FileStore.load("ads", {})
    ad = ads_data.get(ad_id)
    if not ad:
        return jsonify(success=False, message="Ad not found."), 404
    if not current_user.can_access_account(ad.get("account_id")):
        return jsonify(success=False, message="Forbidden."), 403
    if not (ad.get("transcript") or ad.get("script")):
        return jsonify(
            success=False,
            message="No transcript or script available. Transcribe the video first.",
        ), 400
    _update_ad_fields(
        ad_id, {"copy_analysis_status": "pending", "copy_analysis_error": None}
    )
    _TRANSCRIBE_EXECUTOR.submit(_run_copy_analysis_job, ad_id)
    return jsonify(success=True, status="pending")


@app.route("/ads/<ad_id>/copy-analysis-status")
@login_required
def copy_analysis_status(ad_id):
    ads_data = FileStore.load("ads", {})
    ad = ads_data.get(ad_id)
    if not ad:
        return jsonify(success=False, message="Ad not found."), 404
    return jsonify(
        success=True,
        status=ad.get("copy_analysis_status"),
        analysis=ad.get("copy_analysis"),
        error=ad.get("copy_analysis_error"),
    )


# ---------------------------------------------------------------------------
# Account-wide strategist report
# Pipeline (per click):  transcribe all open videos missing transcripts →
# Claude copywriting audit on every open ad missing one → one final Claude
# strategist summary that ties metrics + copy_analysis + country breakdown
# into action-grade recommendations.
# ---------------------------------------------------------------------------


def _is_open_ad(ad):
    """`Open` = currently delivering. Matches the same logic as the account
    detail page so the report scope = ads the user is actually paying for."""
    return (
        str(ad.get("status", "")).lower() == "running"
        or str(ad.get("facebook_status", "")).upper() == "ACTIVE"
    )


def _eligible_report_ads(account_id):
    ads_data = FileStore.load("ads", {})
    return [
        ad for ad in ads_data.values()
        if ad.get("account_id") == account_id and _is_open_ad(ad)
    ]


def _estimate_report_calls(account_id):
    eligible = _eligible_report_ads(account_id)
    video_ads = [
        a for a in eligible if (a.get("creative_type") or "").upper() == "VIDEO"
    ]
    # Whisper only fires for videos that don't already have a transcript.
    needs_transcript = [
        a for a in video_ads
        if a.get("video_id") and not a.get("transcript")
        and a.get("transcript_status") != "no_audio"
    ]
    # Claude audit fires for every ad that ends up with text but no audit yet.
    # That includes videos that WILL get a transcript from this run.
    needs_analysis = []
    for a in eligible:
        already_audited = bool(a.get("copy_analysis"))
        if already_audited:
            continue
        will_have_text = (
            (a.get("transcript") or a.get("script") or "").strip()
            or a in needs_transcript
        )
        if will_have_text:
            needs_analysis.append(a)

    whisper_calls = len(needs_transcript)
    claude_audit_calls = len(needs_analysis)
    # +1 for the final strategist summary call.
    claude_summary_calls = 1
    total_claude = claude_audit_calls + claude_summary_calls

    # Cost model: Whisper $0.006/min (~30s avg = $0.003) + Sonnet
    # ~$0.005/audit + ~$0.05 for the summary (longer output).
    est_cost = round(
        whisper_calls * 0.003
        + claude_audit_calls * 0.005
        + claude_summary_calls * 0.05,
        3,
    )

    return {
        "eligible_ads_total": len(eligible),
        "video_ads": len(video_ads),
        "whisper_calls": whisper_calls,
        "claude_audit_calls": claude_audit_calls,
        "claude_summary_calls": claude_summary_calls,
        "total_claude_calls": total_claude,
        "estimated_cost_usd": est_cost,
    }


def _update_account_fields(account_id, fields):
    with _REPORT_LOCK:
        accounts = FileStore.load("accounts", {})
        if account_id not in accounts:
            return
        accounts[account_id].update(fields)
        FileStore.save("accounts", accounts)


def _resolve_report_video_url(ad, token):
    if not ad.get("video_id") or not token:
        return None
    media = fetch_meta_video_media(ad["video_id"], token)
    return (
        media.get("source")
        or ("https://www.facebook.com" + media["permalink_url"] if media.get("permalink_url") else None)
        or f"https://www.facebook.com/watch/?v={ad['video_id']}"
    )


def _build_report_account_context(account_id, account):
    """Pull last-28d metrics from Meta + merge with our cached transcripts
    and copy_analyses, then add a country rollup. Feed the result to the
    strategist."""
    token = get_account_token(account)
    meta_account_id = account.get("meta_account_id") or account_id
    currency = (account.get("meta_currency") or "USD").upper()
    usd_rate = fx_rate(currency)

    ad_rows = fetch_meta_account_insights(
        access_token=token,
        account_id=meta_account_id,
        breakdowns=None,
        time_increment=None,
        date_preset="last_28d",
        currency=currency,
        usd_rate=usd_rate,
        level="ad",
    )

    country_rows = fetch_meta_account_insights(
        access_token=token,
        account_id=meta_account_id,
        breakdowns=["country"],
        time_increment=None,
        date_preset="last_28d",
        currency=currency,
        usd_rate=usd_rate,
        level="account",
    )

    ads_data = FileStore.load("ads", {})
    by_external = {}
    for ad in ads_data.values():
        if ad.get("account_id") != account_id:
            continue
        ext = ad.get("external_id") or ad.get("id", "").replace("fb-", "")
        if ext:
            by_external[str(ext)] = ad

    per_ad = []
    for row in ad_rows:
        ext = str(row.get("ad_id") or "")
        matched = by_external.get(ext)
        if not matched or not _is_open_ad(matched):
            continue
        m = insights_mod._row_metrics(row)
        text = (matched.get("transcript") or matched.get("script") or "").strip()
        per_ad.append({
            "ad_id": matched["id"],
            "ad_name": matched.get("name") or row.get("ad_name", ""),
            "creative_type": matched.get("creative_type"),
            "spend": round(m["spend"], 2),
            "revenue": round(m["revenue"], 2),
            "roas": m["roas"],
            "clicks": m["clicks"],
            "impressions": m["impressions"],
            "purchases": m["purchases"],
            "ctr": m["ctr"],
            "cpa": m["cpa"],
            "cpm": round(m["spend"] / m["impressions"] * 1000, 2) if m["impressions"] else 0,
            "cpc": round(m["spend"] / m["clicks"], 2) if m["clicks"] else 0,
            "text": text[:1500],
            "copy_analysis": matched.get("copy_analysis"),
        })

    country_summary = insights_mod.aggregate_country(country_rows)[:15]

    total_spend = sum(a["spend"] for a in per_ad)
    total_revenue = sum(a["revenue"] for a in per_ad)
    total_purchases = sum(a["purchases"] for a in per_ad)
    total_clicks = sum(a["clicks"] for a in per_ad)
    total_impressions = sum(a["impressions"] for a in per_ad)

    return {
        "account_name": account.get("name"),
        "date_range": "last_28d",
        "totals": {
            "spend": round(total_spend, 2),
            "revenue": round(total_revenue, 2),
            "roas": round(total_revenue / total_spend, 2) if total_spend else 0,
            "purchases": total_purchases,
            "clicks": total_clicks,
            "impressions": total_impressions,
            "ctr": round(total_clicks / total_impressions * 100, 2) if total_impressions else 0,
            "cpc": round(total_spend / total_clicks, 2) if total_clicks else 0,
            "cpm": round(total_spend / total_impressions * 1000, 2) if total_impressions else 0,
            "cpa": round(total_spend / total_purchases, 2) if total_purchases else 0,
        },
        "ads": per_ad,
        "countries": [
            {
                "country": r["country"],
                "spend": r["spend"],
                "purchases": r["purchases"],
                "roas": r["roas"],
                "ctr": r["ctr"],
            }
            for r in country_summary
        ],
    }


def _run_account_report_job(account_id):
    try:
        accounts = FileStore.load("accounts", {})
        account = accounts.get(account_id)
        if not account:
            return
        token = get_account_token(account)

        # PHASE 1: Transcribe videos that don't yet have a transcript.
        videos_to_transcribe = [
            a for a in _eligible_report_ads(account_id)
            if (a.get("creative_type") or "").upper() == "VIDEO"
            and a.get("video_id")
            and not a.get("transcript")
            and a.get("transcript_status") != "no_audio"
        ]
        _update_account_fields(account_id, {
            "report_progress": {
                "phase": "transcribing",
                "done": 0,
                "total": len(videos_to_transcribe),
            }
        })
        for i, ad in enumerate(videos_to_transcribe):
            try:
                video_url = _resolve_report_video_url(ad, token)
                if video_url:
                    transcript = transcribe_video(video_url)
                    _update_ad_fields(ad["id"], {
                        "transcript": transcript,
                        "transcript_status": "done" if transcript else "no_audio",
                        "transcript_error": None,
                    })
            except Exception as exc:
                _update_ad_fields(ad["id"], {
                    "transcript_status": "failed",
                    "transcript_error": str(exc)[:300],
                })
            _update_account_fields(account_id, {
                "report_progress": {
                    "phase": "transcribing",
                    "done": i + 1,
                    "total": len(videos_to_transcribe),
                }
            })

        # PHASE 2: Claude copywriting audit on each ad that now has text and
        # no audit cached yet.
        eligible = _eligible_report_ads(account_id)
        to_audit = [
            a for a in eligible
            if not a.get("copy_analysis")
            and (a.get("transcript") or a.get("script") or "").strip()
        ]
        _update_account_fields(account_id, {
            "report_progress": {
                "phase": "auditing",
                "done": 0,
                "total": len(to_audit),
            }
        })
        for i, ad in enumerate(to_audit):
            try:
                text = (ad.get("transcript") or ad.get("script") or "").strip()
                if text:
                    result = analyze_copy(
                        text,
                        ad_context={
                            "name": ad.get("name"),
                            "campaign_name": ad.get("campaign_name"),
                            "creative_type": ad.get("creative_type"),
                            "roas": ad.get("roas"),
                        },
                    )
                    _update_ad_fields(ad["id"], {
                        "copy_analysis": result,
                        "copy_analysis_status": "done",
                        "copy_analysis_error": None,
                    })
            except Exception as exc:
                _update_ad_fields(ad["id"], {
                    "copy_analysis_status": "failed",
                    "copy_analysis_error": str(exc)[:300],
                })
            _update_account_fields(account_id, {
                "report_progress": {
                    "phase": "auditing",
                    "done": i + 1,
                    "total": len(to_audit),
                }
            })

        # PHASE 3: Build the strategist summary from last-28d metrics + the
        # cached copy_analyses.
        _update_account_fields(account_id, {
            "report_progress": {
                "phase": "summarizing",
                "done": 0,
                "total": 1,
            }
        })
        context = _build_report_account_context(account_id, account)
        report = build_strategist_report(context)

        _update_account_fields(account_id, {
            "report_status": "done",
            "report_completed_at": datetime.utcnow().isoformat(),
            "report_data": report,
            "report_progress": {"phase": "done", "done": 1, "total": 1},
            "report_error": None,
        })
    except Exception as exc:
        _update_account_fields(account_id, {
            "report_status": "failed",
            "report_completed_at": datetime.utcnow().isoformat(),
            "report_error": str(exc)[:500],
        })


@app.route("/accounts/<account_id>/report/estimate", methods=["POST"])
@login_required
def report_estimate(account_id):
    _, err = _require_account_json(account_id)
    if err:
        return err
    return jsonify(success=True, **_estimate_report_calls(account_id))


@app.route("/accounts/<account_id>/report/start", methods=["POST"])
@login_required
def report_start(account_id):
    if not current_user.can_launch_analysis:
        return jsonify(success=False, message="You don't have permission to launch analysis."), 403
    account, err = _require_account_json(account_id)
    if err:
        return err
    if account.get("report_status") == "pending":
        return jsonify(success=False, message="A report is already running."), 409
    _update_account_fields(account_id, {
        "report_status": "pending",
        "report_started_at": datetime.utcnow().isoformat(),
        "report_error": None,
        "report_progress": {"phase": "queued", "done": 0, "total": 0},
    })
    _REPORT_EXECUTOR.submit(_run_account_report_job, account_id)
    return jsonify(success=True, status="pending")


@app.route("/accounts/<account_id>/report/status")
@login_required
def report_status_endpoint(account_id):
    account, err = _require_account_json(account_id)
    if err:
        return err
    return jsonify(
        success=True,
        status=account.get("report_status", "idle"),
        progress=account.get("report_progress"),
        data=account.get("report_data"),
        error=account.get("report_error"),
        completed_at=account.get("report_completed_at"),
    )


@app.route("/ads/<ad_id>/transcribe", methods=["POST"])
@login_required
def transcribe_ad(ad_id):
    if not current_user.can_launch_analysis:
        return jsonify(success=False, message="You don't have permission to launch analysis."), 403
    ads_data = FileStore.load("ads", {})
    accounts = FileStore.load("accounts", {})
    ad = ads_data.get(ad_id)
    if not ad:
        return jsonify(success=False, message="Ad not found."), 404
    if not current_user.can_access_account(ad.get("account_id")):
        return jsonify(success=False, message="Forbidden."), 403

    account = accounts.get(ad.get("account_id"), {})
    video_url = None
    if ad.get("video_id") and account.get("meta_access_token"):
        media = fetch_meta_video_media(ad["video_id"], get_account_token(account))
        # Meta returns `source` only for some uploads. Reels and many newer
        # creatives expose only `permalink_url` — yt-dlp can still download
        # those from the public Facebook URL.
        video_url = media.get("source")
        if not video_url and media.get("permalink_url"):
            video_url = "https://www.facebook.com" + media["permalink_url"]
        if not video_url:
            video_url = f"https://www.facebook.com/watch/?v={ad['video_id']}"

    if not video_url:
        return jsonify(
            success=False,
            message="No playable video URL available for this ad.",
        ), 400

    _update_ad_fields(ad_id, {"transcript_status": "pending", "transcript_error": None})
    _TRANSCRIBE_EXECUTOR.submit(_run_transcription_job, ad_id, video_url)
    return jsonify(success=True, status="pending")


@app.route("/ads/<ad_id>/transcript-status")
@login_required
def transcript_status(ad_id):
    ads_data = FileStore.load("ads", {})
    ad = ads_data.get(ad_id)
    if not ad:
        return jsonify(success=False, message="Ad not found."), 404
    return jsonify(
        success=True,
        status=ad.get("transcript_status"),
        transcript=ad.get("transcript"),
        error=ad.get("transcript_error"),
    )


@app.route("/ads/<ad_id>")
@login_required
def ad_detail(ad_id):
    ads_data = FileStore.load("ads", {})
    accounts = FileStore.load("accounts", {})
    raw_ad = ads_data.get(ad_id)
    if not raw_ad:
        return redirect(url_for("dashboard"))

    if not current_user.can_access_account(raw_ad.get("account_id")):
        flash("You don't have access to that ad.", "danger")
        return redirect(url_for("dashboard"))

    ad = enrich_ad(raw_ad)
    account = accounts.get(ad.get("account_id"), {})

    if ad.get("video_id") and account.get("meta_access_token"):
        video_media = fetch_meta_video_media(
            ad["video_id"], get_account_token(account)
        )
        ad["video_source_url"] = video_media.get("source")
        if not ad.get("thumbnail_url"):
            ad["thumbnail_url"] = video_media.get("picture")

    analysis_source = ad.get("transcript") or ad.get("script", "") or ad.get("name", "")
    analysis = analyze_ad_text(analysis_source)

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

    copy_analysis = raw_ad.get("copy_analysis")
    copy_analysis_status = raw_ad.get("copy_analysis_status")
    copy_analysis_error = raw_ad.get("copy_analysis_error")

    return render_template(
        "ad_detail.html",
        ad=ad,
        account=account,
        analysis=analysis,
        copy_analysis=copy_analysis,
        copy_analysis_status=copy_analysis_status,
        copy_analysis_error=copy_analysis_error,
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
        if not current_user.is_admin:
            flash("Only admins can create ad accounts.", "danger")
            return redirect(url_for("accounts"))
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

    accounts_data = current_user.allowed_accounts(FileStore.load("accounts", {}))
    return render_template("accounts.html", accounts=accounts_data.values())


@app.route("/accounts/<account_id>", methods=["GET"])
@login_required
def account_detail(account_id):
    account, err = _require_account_html(account_id)
    if err:
        return err
    accounts_data = FileStore.load("accounts", {})

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
    account, err = _require_account_html(account_id)
    if err:
        return err
    accounts_data = FileStore.load("accounts", {})

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

    accounts_data = FileStore.load("accounts", {})

    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        is_admin = request.form.get("is_admin") == "on"
        can_launch_analysis = request.form.get("can_launch_analysis") == "on"
        can_view_tokens = request.form.get("can_view_tokens") == "on"
        allowed_account_ids = request.form.getlist("allowed_account_ids")

        users_data = FileStore.load("users", {})
        new_id = str(max([int(k) for k in users_data.keys()], default=0) + 1)

        users_data[new_id] = {
            "id": new_id,
            "username": username,
            "password_hash": generate_password_hash(password),
            "is_admin": is_admin,
            "can_launch_analysis": can_launch_analysis,
            "can_view_tokens": can_view_tokens,
            "allowed_account_ids": allowed_account_ids,
        }
        FileStore.save("users", users_data)
        flash("User created successfully.", "success")
        return redirect(url_for("admin_users"))

    return render_template(
        "admin_user_form.html",
        mode="create",
        user_data=None,
        accounts=accounts_data,
    )


@app.route("/admin/users/<user_id>/edit", methods=["GET", "POST"])
@login_required
def admin_edit_user(user_id):
    if not current_user.is_admin:
        flash("Admin access required.", "warning")
        return redirect(url_for("dashboard"))

    users_data = FileStore.load("users", {})
    user_data = users_data.get(str(user_id))
    if not user_data:
        flash("User not found.", "danger")
        return redirect(url_for("admin_users"))

    accounts_data = FileStore.load("accounts", {})

    if request.method == "POST":
        # Username and password are optional on edit — only update if filled.
        new_username = (request.form.get("username") or "").strip()
        new_password = request.form.get("password") or ""
        if new_username:
            user_data["username"] = new_username
        if new_password:
            user_data["password_hash"] = generate_password_hash(new_password)
        # Admins editing themselves keep their admin flag to avoid lockout.
        is_self = str(user_id) == str(current_user.id)
        user_data["is_admin"] = True if is_self else (request.form.get("is_admin") == "on")
        user_data["can_launch_analysis"] = request.form.get("can_launch_analysis") == "on"
        user_data["can_view_tokens"] = request.form.get("can_view_tokens") == "on"
        user_data["allowed_account_ids"] = request.form.getlist("allowed_account_ids")

        users_data[str(user_id)] = user_data
        FileStore.save("users", users_data)
        flash("User updated.", "success")
        return redirect(url_for("admin_users"))

    return render_template(
        "admin_user_form.html",
        mode="edit",
        user_data=user_data,
        accounts=accounts_data,
    )


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


def _fetch_ad_level_rows(accounts_map, date_preset):
    """Fetch one row per ad for the chosen date range, across all connected
    accounts in parallel. Used by the editor breakdown so it reflects the
    selected date filter instead of the frozen sync snapshot.
    """
    if not accounts_map:
        return []

    def run(item):
        account_id, account = item
        token = get_account_token(account)
        meta_account_id = account.get("meta_account_id") or account_id
        currency = (account.get("meta_currency") or "USD").upper()
        usd_rate = fx_rate(currency)
        rows = fetch_meta_account_insights(
            access_token=token,
            account_id=meta_account_id,
            breakdowns=None,
            time_increment=None,
            date_preset=date_preset,
            currency=currency,
            usd_rate=usd_rate,
            level="ad",
        )
        return rows

    all_rows = []
    items = list(accounts_map.items())
    with ThreadPoolExecutor(max_workers=min(8, len(items) or 1)) as ex:
        for rows in ex.map(run, items):
            all_rows.extend(rows)
    return all_rows


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
        token = get_account_token(account)
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
    accounts = current_user.allowed_accounts(FileStore.load("accounts", {}))
    ads_data = FileStore.load("ads", {})

    if scope_account_id:
        scope_account = accounts.get(scope_account_id)
        if not scope_account:
            return None
        ads_iterable = (a for a in ads_data.values() if a.get("account_id") == scope_account_id)
    else:
        scope_account = None
        # Non-admins should only see ads from accounts they can access.
        ads_iterable = (a for a in ads_data.values() if a.get("account_id") in accounts)

    ads = enrich_ads(ads_iterable)
    date_preset = insights_mod.resolve_range(request.args.get("range", insights_mod.DEFAULT_RANGE))
    connected = _connected_accounts(accounts, scope_account_id)
    breakdowns = _fetch_breakdowns_parallel(connected, date_preset)

    # Live period totals come from the timeseries breakdown (no breakdown keys,
    # one row per day for the chosen date_preset). Summing these gives the real
    # period totals that respect the date filter — unlike `ads`, which holds a
    # frozen "today" snapshot from the last Meta sync.
    period_rows = insights_mod.aggregate_timeseries(breakdowns["timeseries"])
    period_spend = sum(r["spend"] for r in period_rows)
    period_revenue = sum(r["revenue"] for r in period_rows)
    period_clicks = sum(int(r["clicks"]) for r in period_rows)
    period_impressions = sum(int(r["impressions"]) for r in period_rows)
    period_purchases = sum(int(r["purchases"]) for r in period_rows)
    period_has_data = bool(period_rows)

    account_rows = insights_mod.account_scorecard(ads, accounts)
    campaign_rows = insights_mod.campaign_leaderboard(ads, accounts)
    creative_rows = insights_mod.creative_leaderboard(ads, accounts)
    if period_has_data:
        funnel = {
            "impressions": period_impressions,
            "clicks": period_clicks,
            "purchases": period_purchases,
            "click_rate": round(period_clicks / period_impressions * 100, 2) if period_impressions else 0,
            "conversion_rate": round(period_purchases / period_clicks * 100, 2) if period_clicks else 0,
            "purchase_rate": round(period_purchases / period_impressions * 100, 4) if period_impressions else 0,
        }
    else:
        funnel = insights_mod.funnel_metrics(ads)
    distribution = insights_mod.spend_distribution(ads, accounts)
    status_data = insights_mod.status_mix(ads)
    creative_type_data = insights_mod.creative_type_mix(ads)
    ad_level_rows = _fetch_ad_level_rows(connected, date_preset)
    if ad_level_rows:
        editor_rows = insights_mod.editor_breakdown_from_insight_rows(ad_level_rows)
    else:
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
            "spend": period_spend if period_has_data else sum(a.get("spend_usd", 0) for a in ads),
            "revenue": period_revenue if period_has_data else sum(a.get("revenue_usd", 0) for a in ads),
            "purchases": period_purchases if period_has_data else sum(a.get("purchases", 0) for a in ads),
            "clicks": period_clicks if period_has_data else sum(int(a.get("clicks", 0) or 0) for a in ads),
            "impressions": period_impressions if period_has_data else sum(int(a.get("impressions", 0) or 0) for a in ads),
            "is_live": period_has_data,
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
    if not current_user.can_access_account(account_id):
        flash("You don't have access to that account.", "danger")
        return redirect(url_for("dashboard"))
    context = _build_analytics_context(scope_account_id=account_id)
    if context is None:
        return redirect(url_for("accounts"))
    return render_template("analytics.html", **context)


@app.route("/analytics/compare")
@login_required
def analytics_compare():
    ad_ids = [aid for aid in request.args.getlist("ad") if aid]
    ads_data = FileStore.load("ads", {})
    accounts = current_user.allowed_accounts(FileStore.load("accounts", {}))
    if not current_user.is_admin:
        ads_data = {aid: ad for aid, ad in ads_data.items() if ad.get("account_id") in accounts}

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


def _seed_admin_user():
    """Create the admin user if no user with that username exists yet.
    Username comes from ADMIN_USERNAME (default 'GPS').
    Password comes from ADMIN_PASSWORD (REQUIRED in production; falls back to
    'Rouis2024+' only when FLASK_ENV is not 'production').
    """
    admin_username = os.environ.get("ADMIN_USERNAME", "GPS")
    admin_password = os.environ.get("ADMIN_PASSWORD")
    if not admin_password:
        if os.environ.get("FLASK_ENV") == "production":
            raise RuntimeError(
                "ADMIN_PASSWORD env var is required in production. "
                "Set it in your hosting provider's dashboard before starting the app."
            )
        admin_password = "Rouis2024+"

    users = FileStore.load("users", {})
    if not users or not any(u.get("username") == admin_username for u in users.values()):
        users["1"] = {
            "id": "1",
            "username": admin_username,
            "password_hash": generate_password_hash(admin_password),
            "is_admin": True,
        }
        FileStore.save("users", users)


# Always seed on import — this runs both under `python app.py` and under gunicorn.
_seed_admin_user()


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=debug, host="0.0.0.0", port=port)
