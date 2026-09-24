"""
AW TON — الدفع المباشر عبر محفظة TON (TON Connect).

المسار:
  1) الخادم ينشئ طلبًا (order_id) ويعيد: عنوان محفظة المشروع + المبلغ بالنانو-طن + payload
     (خلية BOC تحمل تعليقًا نصيًا = order_id). الواجهة ترسلها كما هي عبر TON Connect.
  2) التأكيد لا يُصدَّق من الواجهة أبدًا: نقرأ معاملات محفظة المشروع من toncenter ونبحث عن
     معاملة واردة تعليقها = order_id وقيمتها >= المطلوب.
"""
import base64
import os
import time

import httpx

from retry import raise_for_retryable, with_backoff

TON_WALLET = os.getenv("TON_WALLET_ADDRESS", "").strip()
TONCENTER_API = os.getenv("TONCENTER_API", "https://toncenter.com/api/v2").rstrip("/")
TONCENTER_KEY = os.getenv("TONCENTER_API_KEY", "")
TON_WEBHOOK_SECRET = os.getenv("TON_WEBHOOK_SECRET", "")
TON_PAYMENT_WINDOW = int(os.getenv("TON_PAYMENT_WINDOW_SEC", "7200"))  # بعدها يُعلَّم الطلب expired
NANO = 1_000_000_000


class TonError(Exception):
    pass


def configured() -> bool:
    return bool(TON_WALLET)


def to_nano(amount_ton: float) -> int:
    return int(round(float(amount_ton) * NANO))


# ───────────── BOC لخلية تعليق نصي (op=0 + نص UTF-8) ─────────────
def _crc32c(data: bytes) -> int:
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc ^ 0xFFFFFFFF


def comment_payload(text: str) -> str:
    """يعيد BOC (base64) لخلية واحدة بلا مراجع: 32 بت أصفار ثم نص التعليق. الحد 123 بايت."""
    data = b"\x00\x00\x00\x00" + text.encode()
    if len(data) > 127:
        raise ValueError("comment too long for a single cell")
    cell = bytes([0, len(data) * 2]) + data  # d1: بلا مراجع، d2: عدد البايتات ×2 (بتات كاملة)
    # magic | flags(has_crc32c, size=1) | off_bytes=1 | cells=1 | roots=1 | absent=0 | tot_size | root=0
    boc = bytes.fromhex("b5ee9c72") + bytes([0x41, 1, 1, 1, 0, len(cell), 0]) + cell
    boc += _crc32c(boc).to_bytes(4, "little")
    return base64.b64encode(boc).decode()


# ───────────── قراءة المعاملات من الشبكة ─────────────
@with_backoff()
def _get_transactions(limit: int) -> list:
    headers = {"X-API-Key": TONCENTER_KEY} if TONCENTER_KEY else {}
    res = httpx.get(
        f"{TONCENTER_API}/getTransactions",
        params={"address": TON_WALLET, "limit": limit, "archival": "true"},
        headers=headers,
        timeout=15,
    )
    raise_for_retryable(res)
    data = res.json()
    if not data.get("ok"):
        raise TonError(data.get("error") or "toncenter error")
    return data.get("result") or []


def fetch_transactions(limit: int = 100) -> list:
    """آخر معاملات محفظة المشروع (الواردة فقط، مبسّطة)."""
    if not configured():
        raise TonError("TON_WALLET_ADDRESS not configured")
    try:
        raw = _get_transactions(limit)
    except (httpx.HTTPError, ValueError) as e:
        raise TonError(str(e))
    out = []
    for tx in raw:
        msg = tx.get("in_msg") or {}
        if not msg.get("source"):  # رسالة خارجية (من المحفظة نفسها) ليست دفعة واردة
            continue
        out.append({
            "hash": (tx.get("transaction_id") or {}).get("hash"),
            "lt": (tx.get("transaction_id") or {}).get("lt"),
            "utime": tx.get("utime"),
            "source": msg.get("source"),
            "value": int(msg.get("value") or 0),
            "comment": (msg.get("message") or "").strip(),
        })
    return out


def find_payment(txs: list, comment: str, min_nano: int):
    """أول معاملة واردة تعليقها يطابق الطلب ومبلغها كافٍ."""
    for tx in txs:
        if tx["comment"] == comment and tx["value"] >= min_nano and tx["hash"]:
            return tx
    return None


# ───────────── سعر TON بالدولار (متغيّر حسب السوق، مخزّن مؤقتًا 5 دقائق) ─────────────
RATE_TTL = int(os.getenv("TON_RATE_TTL_SEC", "300"))
_rate = {"v": None, "at": 0.0}


@with_backoff(attempts=2)
def _fetch_rate() -> float:
    try:
        res = raise_for_retryable(httpx.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "the-open-network", "vs_currencies": "usd"}, timeout=10,
        ))
        return float(res.json()["the-open-network"]["usd"])
    except (KeyError, ValueError, TypeError):
        res = raise_for_retryable(httpx.get("https://tonapi.io/v2/rates", params={"tokens": "ton", "currencies": "usd"}, timeout=10))
        return float(res.json()["rates"]["TON"]["prices"]["USD"])


def usd_rate() -> float | None:
    """سعر 1 TON بالدولار. يعيد آخر قيمة معروفة إن تعذّر الجلب، وNone إن لم تتوفر أي قيمة."""
    if _rate["v"] and time.time() - _rate["at"] < RATE_TTL:
        return _rate["v"]
    try:
        v = _fetch_rate()
        if v > 0:
            _rate.update(v=v, at=time.time())
    except Exception:  # noqa: BLE001
        pass
    return _rate["v"]


def usd_to_ton(usd: float, rate: float) -> float:
    return round(float(usd) / rate, 2)
