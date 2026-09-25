"""
AW SecretBox — تشفير الأسرار المحفوظة في قاعدة البيانات (جلسات حسابات تلجرام، مفاتيح API، توكنات البوتات).

المفتاح: SECRETS_KEY من .env (أي نص طويل)، وإن غاب يُشتق من WEBHOOK_SECRET. التشفير Fernet (AES-128-CBC + HMAC).
قيمة مشفّرة تبدأ بـ "enc:" — القيم القديمة غير المشفّرة تُقرأ كما هي (توافق).
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc:"


def _fernet() -> Fernet:
    raw = os.getenv("SECRETS_KEY") or os.getenv("WEBHOOK_SECRET") or ""
    if not raw:
        raise RuntimeError("SECRETS_KEY/WEBHOOK_SECRET missing")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("aw-secretbox|" + raw).encode()).digest()))


def seal(value: str) -> str:
    if not value:
        return ""
    return PREFIX + _fernet().encrypt(value.encode()).decode()


def open_(value: str) -> str:
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value  # قيمة قديمة قبل التشفير
    try:
        return _fernet().decrypt(value[len(PREFIX):].encode()).decode()
    except InvalidToken:
        return ""
