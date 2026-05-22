import os
import json
from datetime import datetime
from pathlib import Path
from werkzeug.security import generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

class FileStore:
    """Simple JSON file-based storage."""
    
    @staticmethod
    def get_file(name):
        return DATA_DIR / f"{name}.json"
    
    @staticmethod
    def load(name, default=None):
        try:
            with open(FileStore.get_file(name)) as f:
                return json.load(f)
        except FileNotFoundError:
            return default or {}
    
    @staticmethod
    def save(name, data):
        with open(FileStore.get_file(name), 'w') as f:
            json.dump(data, f, indent=2, default=str)

# Initialize data files
users = FileStore.load("users", {})
if not users or not any(u.get('username') == 'admin' for u in users.values()):
    users = {
        "1": {
            "id": "1",
            "username": "admin",
            "password_hash": generate_password_hash('admin123'),
            "is_admin": True
        }
    }
    FileStore.save("users", users)

accounts = FileStore.load("accounts", {})
ads = FileStore.load("ads", {})
competitors = FileStore.load("competitors", {})
analyses = FileStore.load("analyses", {})
