import json
from pathlib import Path

# DATA_DIR can be overridden via env var so it can point at a mounted volume in
# production (Render disk, Fly volume, etc.). Local dev uses ./data.
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(__import__("os").environ.get("DATA_DIR") or (BASE_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


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


# Eagerly load shared collections used by app.py. The admin user is seeded in
# app.py (so the hashed password isn't duplicated here).
accounts = FileStore.load("accounts", {})
ads = FileStore.load("ads", {})
competitors = FileStore.load("competitors", {})
analyses = FileStore.load("analyses", {})
