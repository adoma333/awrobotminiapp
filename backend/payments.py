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
