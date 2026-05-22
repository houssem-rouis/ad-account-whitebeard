import os
from pathlib import Path
from dotenv import load_dotenv

base_dir = Path(__file__).resolve().parent
load_dotenv(base_dir / '.env')

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key')
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', f'sqlite:///{base_dir / "ad_insights.db"}')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMINS = [os.environ.get('ADMIN_EMAIL', 'admin@example.com')]
