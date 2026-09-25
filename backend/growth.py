"""
AW Growth — أدوات النمو والتسويق المتكاملة مع كل النظام.

  • كوبونات الحملات (coupons/{CODE}): خصم % أو أيام مجانية، تاريخ انتهاء، عدد استخدامات، مرة لكل مستخدم.
    الاسترداد يحوّل الكوبون إلى مكافأة في محفظة المستخدم فتُطبَّق تلقائيًا في كل طرق الدفع (نفس مسار الجوائز).
  • روابط الهدايا (gifts/{code}): رابط t.me/<bot>?start=gift_<code> أو من داخل التطبيق (startapp) يمنح
    أيامًا مجانية أو كوبونًا أو بطاقة خدش — مرة لكل مستخدم وبحد أقصى للمطالبات.
  • الحملات (campaigns/{slug}): رابط تتبّع لكل إعلان/منصة (t.me/<bot>?start=c_<slug>) يُنسب إليه المستخدم
    (أول لمسة)، مع قمع كامل لكل حملة: نقرات ← فتح ← ربط ← دفع ← تجديد + الإيرادات. وهذا ما يخدم إعلانات
    وسائل التواصل؛ أما SEO (محركات البحث) فلا ينطبق على تطبيق داخل تلجرام.
  • الأتمتة السلوكية (automations/{id}): قواعد «محفّز ← انتظار ← رسالة + عرض» تعمل كل ساعة لكل مستخدم:
    ربط ولم يدفع، اشتراك منتهٍ، خامل، فتح ولم يربط. كل إرسال مرة واحدة لكل دورة ويُسجَّل في automation_log.
  • الإحالة المتدرّجة: أيام مكافأة المُحيل تزيد حسب عدد إحالاته الناجحة (referral_tiers في الإعدادات).
"""
import re
import secrets
import time

import rewards

COUPONS = "coupons"
REDEMPTIONS = "coupon_redemptions"
GIFTS = "gifts"
GIFT_CLAIMS = "gift_claims"
CAMPAIGNS = "campaigns"
AUTOMATIONS = "automations"
AUTO_LOG = "automation_log"
CODE_RE = r"[A-Z0-9]{3,20}"
SLUG_RE = r"[a-z0-9-]{2,30}"
OFFER_TYPES = ("discount", "free_days")
GIFT_TYPES = ("days", "discount", "free_days", "scratch")
TRIGGERS = ("linked_no_pay", "expired", "inactive", "never_linked")
TRIGGER_LABEL = {"linked_no_pay": "ربط حسابه ولم يشترك", "expired": "انتهى اشتراكه", "inactive": "لم يفتح التطبيق",
                 "never_linked": "فتح التطبيق ولم يربط"}


class GrowthError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _now(now=None):
    return time.time() if now is None else now


def _offer_card(db, uid, typ: str, value, hours: int, event: str, now=None) -> str:
    """عرض (خصم/أيام) يُضاف لمحفظة مكافآت المستخدم كجائزة مكشوفة، فيُطبَّق في الدفع تلقائيًا."""
    now = _now(now)
    card_id = f"{uid}_{event}"[:140]
    try:
        db.collection(rewards.CARDS).document(card_id).create({
            "uid": str(uid), "event": event, "status": "revealed", "prize": {"type": typ, "value": value},
            "created_at": now, "claimed_at": now, "revealed_at": now, "expires_at": now + max(1, int(hours)) * 3600,
            "used": False, "issued_by_admin": True,
        })
    except rewards.AlreadyExists:
        raise GrowthError("already_redeemed", 409)
    return card_id


# ═════════════════════════ كوبونات الحملات ═════════════════════════
def clean_coupon(d: dict) -> dict:
    code = str(d.get("code") or "").strip().upper()
    if not re.fullmatch(CODE_RE, code):
        raise GrowthError("invalid_code")
    typ = d.get("type")
    if typ not in OFFER_TYPES:
        raise GrowthError("invalid_type")
    value = int(d.get("value") or 0)
    if (typ == "discount" and not 1 <= value <= 90) or (typ == "free_days" and not 1 <= value <= 365):
        raise GrowthError("invalid_value")
    return {"code": code, "type": typ, "value": value, "expires_at": float(d.get("expires_at") or 0),
            "max_uses": max(0, int(d.get("max_uses") or 0)), "valid_hours": max(1, min(720, int(d.get("valid_hours") or 72))),
            "active": bool(d.get("active", True)), "campaign": str(d.get("campaign") or "")[:30], "note": str(d.get("note") or "")[:200]}


def redeem_coupon(db, uid, code: str, now=None) -> dict:
    now = _now(now)
    code = str(code or "").strip().upper()
    if not re.fullmatch(CODE_RE, code):
        raise GrowthError("coupon_not_found", 404)
    ref = db.collection(COUPONS).document(code)
    snap = ref.get()
    c = snap.to_dict() if snap.exists else None
    if not c or not c.get("active"):
        raise GrowthError("coupon_not_found", 404)
    if c.get("expires_at") and now > c["expires_at"]:
        raise GrowthError("coupon_expired", 410)
    if c.get("max_uses") and int(c.get("used_count") or 0) >= int(c["max_uses"]):
        raise GrowthError("coupon_exhausted", 409)
    red = db.collection(REDEMPTIONS).document(f"{code}_{uid}")
    try:
        red.create({"code": code, "uid": str(uid), "at": now})
    except rewards.AlreadyExists:
        raise GrowthError("already_redeemed", 409)
    hours = int(c.get("valid_hours") or 72)
    if c.get("expires_at"):
        hours = max(1, min(hours, int((c["expires_at"] - now) / 3600) + 1))
    card_id = _offer_card(db, uid, c["type"], c["value"], hours, f"coupon_{code}", now)
    ref.set({"used_count": int(c.get("used_count") or 0) + 1}, merge=True)
    return {"reward_id": card_id, "type": c["type"], "value": c["value"], "expires_in_hours": hours}


# ═════════════════════════ روابط الهدايا ═════════════════════════
def clean_gift(d: dict) -> dict:
    typ = d.get("type")
    if typ not in GIFT_TYPES:
        raise GrowthError("invalid_type")
    value = int(d.get("value") or 0)
    if typ != "scratch" and not 1 <= value <= (90 if typ == "discount" else 365):
        raise GrowthError("invalid_value")
    return {"type": typ, "value": value, "max_claims": max(0, int(d.get("max_claims") or 0)),
            "expires_at": float(d.get("expires_at") or 0), "valid_hours": max(1, min(720, int(d.get("valid_hours") or 72))),
            "active": bool(d.get("active", True)), "title": str(d.get("title") or "")[:80], "campaign": str(d.get("campaign") or "")[:30]}


def new_gift_code() -> str:
    return "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))


def claim_gift(db, uid, code: str, now=None) -> dict:
    now = _now(now)
    code = str(code or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9]{6,12}", code):
        raise GrowthError("gift_not_found", 404)
    ref = db.collection(GIFTS).document(code)
    snap = ref.get()
    g = snap.to_dict() if snap.exists else None
    if not g or not g.get("active"):
        raise GrowthError("gift_not_found", 404)
    if g.get("expires_at") and now > g["expires_at"]:
        raise GrowthError("gift_expired", 410)
    if g.get("max_claims") and int(g.get("claims") or 0) >= int(g["max_claims"]):
        raise GrowthError("gift_exhausted", 409)
    try:
        db.collection(GIFT_CLAIMS).document(f"{code}_{uid}").create({"code": code, "uid": str(uid), "at": now})
    except rewards.AlreadyExists:
        raise GrowthError("already_claimed", 409)
    out = {"type": g["type"], "value": g.get("value"), "title": g.get("title")}
    if g["type"] == "days":
        import billing

        billing._add_days(db, uid, int(g["value"]))
    elif g["type"] in OFFER_TYPES:
        out["reward_id"] = _offer_card(db, uid, g["type"], g["value"], int(g.get("valid_hours") or 72), f"gift_{code}", now)
    else:
        out["card_id"] = rewards.grant_card(db, uid, f"gift_{code}", now=now, force=True)
    ref.set({"claims": int(g.get("claims") or 0) + 1}, merge=True)
    return out


# ═════════════════════════ الحملات (تتبّع مصدر المستخدم) ═════════════════════════
def clean_campaign(d: dict) -> dict:
    slug = str(d.get("slug") or "").strip().lower()
    if not re.fullmatch(SLUG_RE, slug):
        raise GrowthError("invalid_slug")
    return {"slug": slug, "name": str(d.get("name") or slug)[:60], "source": str(d.get("source") or "other")[:20],
            "gift_code": str(d.get("gift_code") or "").upper()[:12], "active": bool(d.get("active", True))}


def track_start(db, uid, slug: str, now=None) -> dict | None:
    """/start c_<slug>: نقرة + نسب المستخدم للحملة (أول لمسة فقط). يرجع الحملة إن وُجدت."""
    now = _now(now)
    slug = str(slug or "").lower()
    if not re.fullmatch(SLUG_RE, slug):
        return None
    ref = db.collection(CAMPAIGNS).document(slug)
    snap = ref.get()
    c = snap.to_dict() if snap.exists else None
    if not c or not c.get("active", True):
        return None
    ref.set({"clicks": int(c.get("clicks") or 0) + 1}, merge=True)
    uref = db.collection("users").document(str(uid))
    u = uref.get()
    if not ((u.to_dict() or {}).get("campaign") if u.exists else None):
        uref.set({"campaign": slug, "campaign_at": now}, merge=True)
    return {"slug": slug, **c}


# ═════════════════════════ القمع (Funnel) ═════════════════════════
def funnel(db, campaign: str | None = None) -> dict:
    from google.cloud.firestore_v1.base_query import FieldFilter

    pay_count, revenue = {}, {}
    for d in db.collection("payments").where(filter=FieldFilter("status", "==", "finished")).stream():
        p = d.to_dict() or {}
        uid = str(p.get("uid"))
        pay_count[uid] = pay_count.get(uid, 0) + 1
        usd = float(p.get("amount_usd") or 0) if p.get("method") != "stars" else 0.0
        if p.get("method") == "ton" and p.get("amount_ton") and p.get("ton_rate_usd"):
            usd = float(p["amount_ton"]) * float(p["ton_rate_usd"])
        revenue[uid] = revenue.get(uid, 0.0) + usd
    opened = linked = paid = renewed = 0
    rev = 0.0
    for d in db.collection("users").stream():
        u = d.to_dict() or {}
        if campaign and u.get("campaign") != campaign:
            continue
        opened += 1
        if u.get("status") == "approved" or u.get("trial_checked") or u.get("last_unlink_at") or u.get("decided_at"):
            linked += 1
        n = pay_count.get(d.id, 0)
        paid += n >= 1
        renewed += n >= 2
        rev += revenue.get(d.id, 0.0)
    pct = lambda a, b: round(a / b * 100, 1) if b else None  # noqa: E731
    return {"opened": opened, "linked": linked, "paid": paid, "renewed": renewed, "revenue_usd": round(rev, 2),
            "rates": {"link": pct(linked, opened), "pay": pct(paid, linked), "renew": pct(renewed, paid)},
            "dropoff": {"not_linked": opened - linked, "linked_not_paid": linked - paid, "paid_not_renewed": paid - renewed}}


# ═════════════════════════ الأتمتة السلوكية (رسائل الاسترجاع والعروض) ═════════════════════════
DEFAULT_AUTOMATIONS = [
    {"id": "winback_linked", "name": "ربط ولم يشترك", "trigger": "linked_no_pay", "delay_hours": 24, "enabled": False,
     "offer_type": "discount", "offer_value": 10, "offer_hours": 48,
     "message_ar": "مرحبًا {name} 👋\nحسابك مربوط وجاهز — ينقصه تفعيل التداول الآلي فقط.\nهديتك: خصم {offer} صالح {hours} ساعة، يُطبَّق تلقائيًا عند الدفع.",
     "message_en": "Hi {name} 👋\nYour account is linked and ready — it just needs automated trading activated.\nYour gift: {offer} off, valid for {hours}h, applied automatically at checkout."},
    {"id": "winback_expired", "name": "انتهى اشتراكه منذ 3 أيام", "trigger": "expired", "delay_hours": 72, "enabled": False,
     "offer_type": "discount", "offer_value": 15, "offer_hours": 72,
     "message_ar": "اشتقنا لك يا {name} 🔔\nانتهى اشتراكك قبل أيام وحسابك ينتظر.\nعرض خاص لك: خصم {offer} صالح {hours} ساعة عند التجديد.",
     "message_en": "We miss you, {name} 🔔\nYour subscription ended a few days ago.\nSpecial offer: {offer} off your renewal, valid for {hours}h."},
]


def clean_automation(d: dict) -> dict:
    if d.get("trigger") not in TRIGGERS:
        raise GrowthError("invalid_trigger")
    typ = d.get("offer_type") or "none"
    if typ not in (*OFFER_TYPES, "none"):
        raise GrowthError("invalid_offer")
    val = int(d.get("offer_value") or 0)
    if typ == "discount" and not 1 <= val <= 90 or typ == "free_days" and not 1 <= val <= 60:
        raise GrowthError("invalid_value")
    return {"name": str(d.get("name") or "")[:60], "trigger": d["trigger"], "enabled": bool(d.get("enabled")),
            "delay_hours": max(1, min(24 * 90, int(d.get("delay_hours") or 24))), "offer_type": typ, "offer_value": val,
            "offer_hours": max(1, min(720, int(d.get("offer_hours") or 48))), "via_bot": bool(d.get("via_bot", True)),
            "message_ar": str(d.get("message_ar") or "")[:1000], "message_en": str(d.get("message_en") or "")[:1000]}


def list_automations(db) -> list:
    saved = {d.id: d.to_dict() or {} for d in db.collection(AUTOMATIONS).stream()}
    rows = [{**a, **saved.pop(a["id"], {}), "id": a["id"]} for a in DEFAULT_AUTOMATIONS]
    rows += [{**v, "id": k} for k, v in saved.items()]
    return rows


def _ts(v):
    try:
        return v.timestamp()
    except AttributeError:
        return float(v or 0)


def due_key(rule: dict, u: dict, now: float) -> str | None:
    """مفتاح الدورة إن كان المستخدم مستحقًا لهذه القاعدة الآن (يمنع التكرار داخل الدورة نفسها)."""
    delay = rule["delay_hours"] * 3600
    exp = float(((u.get("subscription") or {}).get("expires_at")) or 0)
    linked = u.get("status") == "approved"
    t = rule["trigger"]
    if t == "linked_no_pay":
        since = _ts(u.get("decided_at")) or _ts(u.get("created_at"))
        return "once" if linked and not exp and since and now - since >= delay else None
    if t == "expired":
        return f"exp{int(exp)}" if exp and exp < now and now - exp >= delay else None
    if t == "inactive":
        last = float(u.get("last_seen") or 0)
        return f"seen{int(last)}" if last and now - last >= delay else None
    if t == "never_linked":
        first = float(u.get("first_seen") or 0)
        return "once" if first and not linked and not u.get("trial_checked") and now - first >= delay else None
    return None


def render(rule: dict, u: dict, lang: str) -> str:
    offer = ""
    if rule["offer_type"] == "discount":
        offer = f"{rule['offer_value']}%"
    elif rule["offer_type"] == "free_days":
        offer = f"{rule['offer_value']} " + ("يوم" if lang == "ar" else "days")
    text = rule.get(f"message_{lang}") or rule.get("message_ar") or ""
    return (text.replace("{name}", (u.get("nickname") or ("صديقنا" if lang == "ar" else "there")).split(" ")[0])
            .replace("{offer}", offer).replace("{hours}", str(rule["offer_hours"])))


def run_automations(db, send, notify, now=None, limit: int = 300) -> int:
    """مهمة دورية: send(uid, text, lang) رسالة البوت، notify(uid, title_ar, title_en, body_ar, body_en) إشعار التطبيق."""
    now = _now(now)
    rules = [r for r in list_automations(db) if r.get("enabled")]
    if not rules:
        return 0
    sent = 0
    for d in db.collection("users").stream():
        if sent >= limit:
            break
        u = d.to_dict() or {}
        done = u.get("automation_sent") or {}
        for r in rules:
            key = due_key(r, u, now)
            if not key or done.get(r["id"]) == key:
                continue
            lang = u.get("language") or "ar"
            reward_id = None
            if r["offer_type"] in OFFER_TYPES:
                try:
                    reward_id = _offer_card(db, d.id, r["offer_type"], r["offer_value"], r["offer_hours"], f"auto_{r['id']}_{key}", now)
                except GrowthError:
                    pass
            text = render(r, u, lang)
            if r.get("via_bot", True):
                send(d.id, text, lang)
            notify(d.id, "🎁 عرض خاص لك", "🎁 A special offer for you", render(r, u, "ar"), render(r, u, "en"))
            db.collection("users").document(d.id).set({"automation_sent": {r["id"]: key}}, merge=True)
            db.collection(AUTO_LOG).document().set({"rule": r["id"], "uid": d.id, "key": key, "reward_id": reward_id, "at": now})
            sent += 1
            break  # رسالة واحدة لكل مستخدم في كل دورة
    return sent


# ═════════════════════════ الإحالة المتدرّجة ═════════════════════════
DEFAULT_TIERS = [{"min": 0, "days": 7}, {"min": 5, "days": 10}, {"min": 15, "days": 14}, {"min": 40, "days": 21}]


def clean_tiers(rows) -> list:
    out = []
    for r in (rows or [])[:10]:
        m, dd = int(r.get("min") or 0), int(r.get("days") or 0)
        if m < 0 or not 1 <= dd <= 365:
            raise GrowthError("invalid_tier")
        out.append({"min": m, "days": dd})
    out.sort(key=lambda r: r["min"])
    if not out or out[0]["min"] != 0:
        raise GrowthError("first_tier_must_start_at_0")
    return out


def tier_for(tiers: list, paid_count: int) -> tuple[dict, dict | None]:
    cur, nxt = tiers[0], None
    for i, t in enumerate(tiers):
        if paid_count >= t["min"]:
            cur, nxt = t, (tiers[i + 1] if i + 1 < len(tiers) else None)
    return cur, nxt
