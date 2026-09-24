"""
AW Payments — تكامل NOWPayments (USDT/TON عبر صفحة الدفع المستضافة لديهم).
"""
import hashlib
import hmac
import json
import os

import httpx

from retry import RetryableError, raise_for_retryable, with_backoff

NP_API_KEY = os.getenv("NOWPAYMENTS_API_KEY", "")
NP_IPN_SECRET = os.getenv("NOWPAYMENTS_IPN_SECRET", "")
NP_API = "https://api.nowpayments.io/v1"
NP_WIDGET = "https://nowpayments.io/embeds/payment-widget"


class PaymentError(Exception):
    pass


@with_backoff()
def _post_invoice(body: dict) -> httpx.Response:
    return raise_for_retryable(
        httpx.post(
            f"{NP_API}/invoice",
            headers={"x-api-key": NP_API_KEY, "Content-Type": "application/json"},
            json=body,
            timeout=20,
        )
    )


def create_invoice(order_id: str, amount_usd: float, description: str, ipn_url: str, success_url: str, cancel_url: str) -> dict:
    try:
        res = _post_invoice({
            "price_amount": amount_usd,
            "price_currency": "usd",
            "order_id": order_id,
            "order_description": description,
            "ipn_callback_url": ipn_url,
            "success_url": success_url,
            "cancel_url": cancel_url,
        })
        data = res.json()
    except (httpx.HTTPError, RetryableError, ValueError) as e:
        raise PaymentError(f"network error: {e}")
    if res.status_code >= 400 or "invoice_url" not in data:
        raise PaymentError(data.get("message") or f"NOWPayments error: {data}")
    return data


def widget_url(invoice_id) -> str:
    """رابط بوابة الدفع المضمّنة (iframe) لفاتورة NOWPayments."""
    return f"{NP_WIDGET}?iid={invoice_id}"


def verify_ipn_signature(raw_body: bytes, signature: str) -> bool:
    """يتحقق من توقيع NOWPayments: HMAC-SHA512 على JSON مرتّب المفاتيح (على كل المستويات)."""
    if not signature or not NP_IPN_SECRET:
        return False
    try:
        parsed = json.loads(raw_body)
    except ValueError:
        return False
    ordered = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
    digest = hmac.new(NP_IPN_SECRET.encode(), ordered.encode(), hashlib.sha512).hexdigest()
    return hmac.compare_digest(digest, signature)


# ───────────── بوابة مخصّصة: دفعة مباشرة (عنوان + مبلغ) بدل صفحة NOWPayments المستضافة ─────────────
# pay_currency → (الاسم، الشبكة). يمكن تقليص القائمة عبر NP_CURRENCIES في .env
CURRENCIES = {
    "usdttrc20": ("USDT", "TRON (TRC20)"),
    "usdtbsc": ("USDT", "BNB Smart Chain (BEP20)"),
    "usdterc20": ("USDT", "Ethereum (ERC20)"),
    "ton": ("TON", "TON"),
    "btc": ("BTC", "Bitcoin"),
    "eth": ("ETH", "Ethereum"),
    "ltc": ("LTC", "Litecoin"),
    "trx": ("TRX", "TRON"),
}
ENABLED = [c for c in os.getenv("NP_CURRENCIES", "usdttrc20,usdtbsc,ton,btc,eth,ltc").replace(" ", "").split(",") if c in CURRENCIES]


def currencies() -> list:
    return [{"code": c, "symbol": CURRENCIES[c][0], "network": CURRENCIES[c][1]} for c in ENABLED]


@with_backoff()
def _np(method: str, path: str, body: dict | None = None) -> httpx.Response:
    return raise_for_retryable(
        httpx.request(method, f"{NP_API}{path}", headers={"x-api-key": NP_API_KEY, "Content-Type": "application/json"},
                      json=body, timeout=20)
    )


def create_direct_payment(order_id: str, amount_usd: float, pay_currency: str, description: str, ipn_url: str) -> dict:
    """ينشئ دفعة مباشرة ويعيد عنوان الإيداع والمبلغ بالعملة المختارة (والمذكّرة/memo إن لزمت)."""
    if pay_currency not in ENABLED:
        raise PaymentError("unsupported_currency")
    try:
        res = _np("POST", "/payment", {
            "price_amount": amount_usd,
            "price_currency": "usd",
            "pay_currency": pay_currency,
            "order_id": order_id,
            "order_description": description,
            "ipn_callback_url": ipn_url,
        })
        data = res.json()
    except (httpx.HTTPError, RetryableError, ValueError) as e:
        raise PaymentError(f"network error: {e}")
    if res.status_code >= 400 or not data.get("pay_address"):
        msg = str(data.get("message") or data)
        raise PaymentError("amount_too_low" if "minimal" in msg.lower() or "less than" in msg.lower() else msg)
    return data


def get_payment(payment_id) -> dict:
    """حالة الدفعة من NOWPayments مباشرة (طلب موقّع بمفتاح الـ API فهو موثوق)."""
    try:
        return _np("GET", f"/payment/{payment_id}").json()
    except (httpx.HTTPError, RetryableError, ValueError) as e:
        raise PaymentError(f"network error: {e}")
