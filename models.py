from flask_login import UserMixin
from datetime import datetime
from app import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f'<User {self.username}>'

class AdAccount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    provider = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    ads = db.relationship('Ad', backref='account', lazy=True)
    competitors = db.relationship('CompetitorAd', backref='account', lazy=True)

    def __repr__(self):
        return f'<AdAccount {self.name}>'

class Ad(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('ad_account.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    script = db.Column(db.Text, nullable=False)
    impressions = db.Column(db.Integer, default=0)
    clicks = db.Column(db.Integer, default=0)
    spend = db.Column(db.Float, default=0.0)
    revenue = db.Column(db.Float, default=0.0)
    status = db.Column(db.String(100), default='running')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    analysis = db.relationship('AdAnalysis', backref='ad', uselist=False)

    def roi(self):
        if self.spend == 0:
            return 0.0
        return round((self.revenue - self.spend) / self.spend * 100, 1)

    def ctr(self):
        if self.impressions == 0:
            return 0.0
        return round(self.clicks / self.impressions * 100, 2)

    def __repr__(self):
        return f'<Ad {self.name}>'

class AdAnalysis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ad_id = db.Column(db.Integer, db.ForeignKey('ad.id'), nullable=False)
    length = db.Column(db.Integer)
    tone = db.Column(db.String(100))
    style = db.Column(db.String(120))
    awareness_level = db.Column(db.String(120))
    score = db.Column(db.Float)
    keywords = db.Column(db.Text)
    best_hook = db.Column(db.String(256))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AdAnalysis {self.ad_id}>'

class CompetitorAd(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('ad_account.id'), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    script = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(100), default='running')
    source = db.Column(db.String(200), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CompetitorAd {self.name}>'
