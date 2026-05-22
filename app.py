from datetime import datetime
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config
from flask_sqlalchemy import SQLAlchemy
from forms import LoginForm, UserForm, AdAccountForm, AdForm, CompetitorForm
from analysis import analyze_ad_text, build_account_insights, build_recommendations

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'login'

from models import User, AdAccount, Ad, CompetitorAd, AdAnalysis


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        db.create_all()
        create_default_admin()

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('login'))

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user and check_password_hash(user.password_hash, form.password.data):
                login_user(user)
                return redirect(url_for('dashboard'))
            flash('Invalid username or password.', 'danger')
        return render_template('login.html', form=form)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Logged out successfully.', 'success')
        return redirect(url_for('login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        accounts = AdAccount.query.order_by(AdAccount.name).all()
        stats = build_account_insights(accounts)
        recommendations = build_recommendations(accounts)
        recent_ads = Ad.query.order_by(Ad.updated_at.desc()).limit(5).all()
        return render_template('dashboard.html', accounts=accounts, stats=stats, recommendations=recommendations, recent_ads=recent_ads)

    @app.route('/accounts', methods=['GET', 'POST'])
    @login_required
    def accounts():
        form = AdAccountForm()
        if form.validate_on_submit():
            account = AdAccount(name=form.name.data, provider=form.provider.data, created_at=datetime.utcnow())
            db.session.add(account)
            db.session.commit()
            flash('Ad account added.', 'success')
            return redirect(url_for('accounts'))
        accounts = AdAccount.query.order_by(AdAccount.name).all()
        return render_template('accounts.html', accounts=accounts, form=form)

    @app.route('/accounts/<int:account_id>', methods=['GET', 'POST'])
    @login_required
    def account_detail(account_id):
        account = AdAccount.query.get_or_404(account_id)
        form = AdForm()
        if form.validate_on_submit():
            ad = Ad(
                account=account,
                name=form.name.data,
                script=form.script.data,
                impressions=form.impressions.data,
                clicks=form.clicks.data,
                spend=form.spend.data,
                revenue=form.revenue.data,
                status=form.status.data,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            analysis = analyze_ad_text(ad.script)
            db.session.add(ad)
            db.session.commit()
            ad_analysis = AdAnalysis(ad_id=ad.id, **analysis, created_at=datetime.utcnow())
            db.session.add(ad_analysis)
            db.session.commit()
            flash('Ad saved and analyzed successfully.', 'success')
            return redirect(url_for('account_detail', account_id=account.id))
        ads = Ad.query.filter_by(account_id=account.id).order_by(Ad.updated_at.desc()).all()
        competitors = CompetitorAd.query.filter_by(account_id=account.id).order_by(CompetitorAd.created_at.desc()).all()
        return render_template('account_detail.html', account=account, ads=ads, competitors=competitors, form=form)

    @app.route('/accounts/<int:account_id>/competitors', methods=['GET', 'POST'])
    @login_required
    def competitors(account_id):
        account = AdAccount.query.get_or_404(account_id)
        form = CompetitorForm()
        if form.validate_on_submit():
            comp = CompetitorAd(
                account=account,
                name=form.name.data,
                script=form.script.data,
                status=form.status.data,
                source=form.source.data,
                created_at=datetime.utcnow(),
            )
            db.session.add(comp)
            db.session.commit()
            flash('Competitor ad added.', 'success')
            return redirect(url_for('competitors', account_id=account.id))
        competitors = CompetitorAd.query.filter_by(account_id=account.id).order_by(CompetitorAd.created_at.desc()).all()
        campaign = build_recommendations([account])
        return render_template('competitors.html', account=account, competitors=competitors, form=form, campaign=campaign)

    @app.route('/admin/users')
    @login_required
    def admin_users():
        if not current_user.is_admin:
            flash('Admin access required.', 'warning')
            return redirect(url_for('dashboard'))
        users = User.query.order_by(User.username).all()
        return render_template('admin_users.html', users=users)

    @app.route('/admin/users/create', methods=['GET', 'POST'])
    @login_required
    def admin_create_user():
        if not current_user.is_admin:
            flash('Admin access required.', 'warning')
            return redirect(url_for('dashboard'))
        form = UserForm()
        if form.validate_on_submit():
            password_hash = generate_password_hash(form.password.data)
            user = User(username=form.username.data, password_hash=password_hash, is_admin=form.is_admin.data)
            db.session.add(user)
            db.session.commit()
            flash('User created successfully.', 'success')
            return redirect(url_for('admin_users'))
        return render_template('admin_user_form.html', form=form)

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @login_required
    def admin_delete_user(user_id):
        if not current_user.is_admin:
            flash('Admin access required.', 'warning')
            return redirect(url_for('dashboard'))
        user = User.query.get_or_404(user_id)
        if user == current_user:
            flash('You cannot delete your own account.', 'danger')
            return redirect(url_for('admin_users'))
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully.', 'success')
        return redirect(url_for('admin_users'))

    return app


def create_default_admin():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password_hash=generate_password_hash('admin123'), is_admin=True)
        db.session.add(admin)
        db.session.commit()

if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
