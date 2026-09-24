"""
AW Retry — إعادة المحاولة بتراجع أُسّي (tenacity) لكل النداءات الشبكية الصادرة:
تلجرام، NOWPayments، و toncenter (شبكة TON). الواردة تُعالَج عبر صندوق webhook_inbox في main.py.
"""
import logging
import os

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

log = logging.getLogger("aw-retry")

RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", "4"))
RETRY_MAX_WAIT = float(os.getenv("RETRY_MAX_WAIT_SEC", "8"))


class RetryableError(Exception):
    """خطأ مؤقت من الطرف الآخر (429 أو 5xx) يستحق إعادة المحاولة."""


RETRYABLE = (httpx.TransportError, RetryableError)


def with_backoff(attempts: int | None = None, max_wait: float | None = None):
    """مُزخرف: يعيد المحاولة على أعطال الشبكة و429/5xx فقط، بانتظار 0.5ث ثم 1 ثم 2 ... حتى max_wait.
    بعد آخر محاولة يُرفع الاستثناء الأصلي (reraise) ليعالجه المستدعي كما كان."""
    return retry(
        retry=retry_if_exception_type(RETRYABLE),
        stop=stop_after_attempt(attempts or RETRY_ATTEMPTS),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=max_wait or RETRY_MAX_WAIT),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )


def raise_for_retryable(res: httpx.Response) -> httpx.Response:
    """يحوّل ردود 429/5xx إلى RetryableError؛ أي رد آخر يُعاد كما هو."""
    if res.status_code == 429 or res.status_code >= 500:
        raise RetryableError(f"HTTP {res.status_code}")
    return res
