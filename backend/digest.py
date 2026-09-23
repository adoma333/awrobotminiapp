"""
AW Digest — تقارير ملخصة أسبوعية/شهرية تُرسل عبر تلجرام للمشتركين النشطين.
تُشغَّل بواسطة APScheduler من main.py (lifespan)، ولا تُستدعى مباشرة يدويًا.
"""
import logging
import time

import billing

log = logging.getLogger("aw-digest")


def _fmt_pct(v):
    if v is None:
        return "—"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.2f}%"


def _diff_txt(curr, prev):
    if curr is None or prev is None:
        return ""
    delta = curr - prev
    if abs(delta) < 0.01:
        return " (بدون تغيير عن الفترة السابقة)"
    arrow = "🔺" if delta > 0 else "🔻"
    return f" ({arrow} {_fmt_pct(delta)} عن الفترة السابقة)"


def _build_message(period_label: str, report: dict, prev_snapshot: dict, growth_key: str) -> str:
    growth = report.get(growth_key)
    trades = report.get("trades")
    win_rate = report.get("win_rate")
    prev = prev_snapshot or {}
    lines = [
        f"📊 <b>ملخصك {period_label}</b>",
        f"نمو الحساب: {_fmt_pct(growth)}{_diff_txt(growth, prev.get('growth'))}",
        f"عدد الصفقات: {trades if trades is not None else '—'}{_diff_txt(trades, prev.get('trades'))}",
        f"نسبة الربح: {_fmt_pct(win_rate)}{_diff_txt(win_rate, prev.get('win_rate'))}",
    ]
    return "\n".join(lines)


def _iter_active_subscribers(db):
    """يُرجع (uid, user_data) لكل مستخدم مقبول واشتراكه فعّال حاليًا."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    for doc in db.collection("users").where(filter=FieldFilter("status", "==", "approved")).stream():
        data = doc.to_dict() or {}
        if billing.is_subscription_active(data):
            yield doc.id, data


def run_digest(db, tg, period: str):
    """period: 'weekly' أو 'monthly'. يرسل ملخصًا لكل مشترك نشط ويحفظ لقطة للمقارنة القادمة."""
    growth_key = "weekly_growth_pct" if period == "weekly" else "monthly_growth_pct"
    period_label = "الأسبوعي" if period == "weekly" else "الشهري"
    sent = 0

    for uid, data in _iter_active_subscribers(db):
        report = data.get("report") or {}
        if not report:
            continue  # لا توجد بيانات مزامنة بعد لهذا المستخدم
        prev = ((data.get("digest_history") or {}).get(f"last_{period}")) or {}
        text = _build_message(period_label, report, prev, growth_key)
        try:
            tg("sendMessage", chat_id=uid, parse_mode="HTML", text=text)
            sent += 1
        except Exception as e:  # noqa: BLE001
            log.warning("digest send failed uid=%s err=%s", uid, e)
            continue
        db.collection("users").document(uid).set(
            {
                "digest_history": {
                    f"last_{period}": {
                        "growth": report.get(growth_key),
                        "trades": report.get("trades"),
                        "win_rate": report.get("win_rate"),
                        "sent_at": time.time(),
                    }
                }
            },
            merge=True,
        )
    log.info("digest period=%s sent=%d", period, sent)
    return sent
