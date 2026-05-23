import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

BASE_DIR = Path(__file__).resolve().parent
KEY_FILE = BASE_DIR / ".secret.key"
ENC_PREFIX = "enc:v1:"


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("TOKEN_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()
    key = Fernet.generate_key()
    KEY_FILE.write_bytes(key)
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return key


_fernet = Fernet(_load_or_create_key())


def encrypt_token(value):
    """Encrypt a token. Returns the value unchanged if empty or already encrypted."""
    if not value:
        return value
    if isinstance(value, str) and value.startswith(ENC_PREFIX):
        return value
    token = _fernet.encrypt(value.encode()).decode()
    return ENC_PREFIX + token


def decrypt_token(value):
    """Decrypt a token. Returns plaintext unchanged if it has no encryption prefix."""
    if not value:
        return value
    if not isinstance(value, str) or not value.startswith(ENC_PREFIX):
        return value
    try:
        return _fernet.decrypt(value[len(ENC_PREFIX):].encode()).decode()
    except InvalidToken as exc:
        raise ValueError(
            "Failed to decrypt token — the .secret.key file is missing or different "
            "from the one used to encrypt this value."
        ) from exc


def get_account_token(account):
    """Return the plaintext meta_access_token for an account dict."""
    if not account:
        return None
    return decrypt_token(account.get("meta_access_token"))
