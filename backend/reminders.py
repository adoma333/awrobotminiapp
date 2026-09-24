"""
AW Reminders — تذكير تجديد الاشتراك قبل 3 أيام وقبل 24 ساعة من الانتهاء.
مهمة يومية (APScheduler من main.py). زر "تجديد الآن" يفتح الـ Mini App على تدفق الدفع بـ TON Connect مباشرة.
"""
import logging
import time
from datetime import datetime, timezone

log = logging.getLogger("aw-reminders")

DAY = 86400

TEXT = {
    "d3": {
        "ar": "⏳ اشتراكك في AW Robot ينتهي خلال 3 أيام ({date}).\nجدّده الآن بضغطة عبر محفظة TON 👇",
        "en": "⏳ Your AW Robot subscription ends in 3 days ({date}).\nRenew now in one tap with your TON wallet 👇",
    },
    "d1": {
        "ar": "⚠️ اشتراكك في AW Robot ينتهي خلال 24 ساعة ({date}).\nجدّده الآن كي لا تتوقف المتابعة 👇",
        "en": "⚠️ Your AW Robot subscription ends within 24 hours ({date}).\nRenew now so nothing stops 👇",
    },
}
BUTTON = {"ar": "💎 تجديد الآن", "en": "💎 Renew now"}


def stage_for(remaining: float):
    if remaining <= 0:
        return None
    if remaining <= DAY:
        return "d1"
    if remaining <= 3 * DAY:
        return "d3"
    return None


def run_renewal_reminders(db, tg, webapp_url: str, now: float | None = None) -> int:
    """يرسل تذكيرًا واحدًا لكل مرحلة لكل تاريخ انتهاء. يعيد عدد الرسائل المرسلة."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    sent = 0
    for doc in db.collection("users").where(filter=FieldFilter("subscription.status", "==", "active")).stream():
        data = doc.to_dict() or {}
        sub = data.get("subscription") or {}
        exp = float(sub.get("expires_at") or 0)
        stage = stage_for(exp - now)
        if not stage:
            continue
        done = sub.get("reminders") or {}
        if done.get("for") != exp:  # تجديد غيّر تاريخ الانتهاء: نبدأ من جديد
            done = {}
        if done.get(stage):
            continue

        lang = "ar" if data.get("language", "ar") == "ar" else "en"
        date = datetime.fromtimestamp(exp, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        params = {"chat_id": doc.id, "text": TEXT[stage][lang].format(date=date)}
        if webapp_url:
            params["reply_markup"] = {
                "inline_keyboard": [[{"text": BUTTON[lang], "web_app": {"url": f"{webapp_url}/?renew=ton"}}]]
            }
        res = tg("sendMessage", **params)
        if not res.get("ok"):
            log.warning("reminder failed uid=%s: %s", doc.id, res.get("description"))
            continue
        # تذكير 24 ساعة يُغني عن تذكير 3 أيام إن فات
        db.collection("users").document(doc.id).set(
            {"subscription": {"reminders": {"for": exp, "d3": True, "d1": stage == "d1"}}}, merge=True
        )
        sent += 1
    log.info("renewal reminders sent=%d", sent)
    return sent
