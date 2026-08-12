"""
Encrypts/decrypts LinkedIn access & refresh tokens before they touch the DB.
Uses Fernet (symmetric encryption) keyed by FERNET_KEY from .env.
"""
from cryptography.fernet import Fernet
from django.conf import settings


def _get_fernet() -> Fernet:
    key = settings.FERNET_KEY
    if not key:
        raise RuntimeError(
            "FERNET_KEY is not set in .env. Generate one with:\n"
            "python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(raw: str) -> str:
    if not raw:
        return ""
    return _get_fernet().encrypt(raw.encode()).decode()


def decrypt_value(token: str) -> str:
    if not token:
        return ""
    return _get_fernet().decrypt(token.encode()).decode()
