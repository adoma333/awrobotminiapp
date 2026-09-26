"""
AW Rewards — نظام بطاقات الخدش والمكافآت (Scratch & Win).

  • البطاقة تُمنح لحدث محدد مرة واحدة فقط: معرّف المستند = "{uid}_{event}" ويُنشأ بـ create()
    (يفشل ذريًا إن وُجد) فلا بطاقة مكررة لنفس المستخدم ولنفس الحدث حتى مع الطلبات المتزامنة.
  • الجائزة تُولَّد وتُخزَّن على الخادم فقط (generate_scratch_prize بمولّد SystemRandom)،
    والواجهة تعرض النتيجة القادمة من الخادم ولا تحدد شيئًا.
  • صلاحية الجائزة بالساعات فقط (REWARD_TTL_HOURS) وتبدأ لحظة الكشف.
  • التطبيق على الدفع يُتحقق منه في الخادم، وتُعلَّم الجائزة "مستخدمة" بعد نجاح الدفع فقط.

المجموعات:
  scratch_cards/{uid}_{event}: uid, event, status(new|revealed), prize, claimed_at, revealed_at,
                               expires_at, used, used_at, used_order
  phone_claims/{sha256(phone)}: uid   ← رقم الهاتف الواحد يؤهّل حساب تلجرام واحدًا فقط
  users/{uid}: achievements.{event} (وقت الإنجاز)، scratch_pending [معرّفات بطاقات لم تُكشف]، phone_verified
"""
import base64
import hashlib
import hmac
import json
import os
import random
import time
from datetime import date, timedelta

try:
    from google.api_core.exceptions import AlreadyExists
except ImportError:  # pragma: no cover
    class AlreadyExists(Exception):
        pass

CARDS = "scratch_cards"
PHONES = "phone_claims"

REWARD_TTL_HOURS = max(1, min(72, int(os.getenv("REWARD_TTL_HOURS", "24"))))  # ساعات فقط: 1..72
STREAK_DAYS = 7

# ───────────────────────── مصفوفة الاحتمالات (المجموع 100) ─────────────────────────
#   خصم 60% (10%/20%/50%) · أيام مجانية 25% (3..7) · رصيد/تأمين انزلاق 10% · شهر مجاني 4% · تحدي ممول 1%
PRIZE_TABLE = [
    (30, "discount", 10), (20, "discount", 20), (10, "discount", 50),
    (5, "free_days", 3), (5, "free_days", 4), (5, "free_days", 5), (5, "free_days", 6), (5, "free_days", 7),
    (10, "slippage_insurance", 10),   # رصيد تداول / تأمين انزلاق بقيمة $10
    (4, "free_month", 30),            # اشتراك شهر كامل مجانًا
    (1, "funded_challenge", 100),     # دخول تحدي حساب ممول $100
]
CATEGORY_WEIGHTS = {"discount": 60, "free_days": 25, "slippage_insurance": 10, "free_month": 4, "funded_challenge": 1}
CHECKOUT_TYPES = {"discount", "free_days"}   # تُطبَّق تلقائيًا على طلب الدفع
REDEEM_TYPES = {"free_month"}                # تُفعَّل مباشرة بلا دفع
MANUAL_TYPES = {"slippage_insurance", "funded_challenge"}  # يسلّمها الأدمن يدويًا

PRIZE_TYPES = {"discount", "free_days", "slippage_insurance", "free_month", "funded_challenge"}
TRIGGERS = ("welcome", "link_real", "referral", "streak7", "first_payment", "renewal")

_rng = random.SystemRandom()


def trigger_of(event: str) -> str:
    """اسم المحفّز من اسم الحدث (first_payment · renewal_<order> · streak7_<day> · referral_<uid> …)."""
    event = str(event or "")
    for t in sorted(TRIGGERS, key=len, reverse=True):
        if event == t or event.startswith(t + "_"):
            return t
    return event.split("_")[0]


# ───────────────────────── الإعدادات القابلة للتحكم من لوحة الأدمن (config/rewards) ─────────────────────────
def default_config() -> dict:
    return {
        "enabled": True,
        "ttl_hours": REWARD_TTL_HOURS,
        "require_phone": True,  # false = لا يُشترط توثيق الهاتف/Premium لكشف البطاقات
        "triggers": {k: k not in ("link_real", "renewal") for k in TRIGGERS},  # الجديدة معطّلة افتراضيًا
        "prizes": [{"type": t, "value": v, "weight": w, "enabled": True} for w, t, v in PRIZE_TABLE],
        "trigger_prizes": {},   # جدول جوائز خاص لكل محفّز (فارغ = الجدول العام)
        "streak_days": STREAK_DAYS,  # أيام العمل المتتالية لبطاقة السلسلة
        "max_pending": 5,       # أقصى بطاقات غير مكشوفة للمستخدم في نفس الوقت
    }


def get_config(db) -> dict:
    snap = db.collection("config").document("rewards").get()
    saved = (snap.to_dict() or {}) if snap.exists else {}
    cfg = default_config()
    cfg.update({k: v for k, v in saved.items() if k in cfg})
    cfg["triggers"] = {**default_config()["triggers"], **(saved.get("triggers") or {})}
    return cfg


def clean_config(patch: dict) -> dict:
    """يتحقق من إعدادات الأدمن قبل حفظها. يرفع ValueError برسالة واضحة."""
    cfg = default_config()
    out = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "require_phone" in patch:
        out["require_phone"] = bool(patch["require_phone"])
    if "ttl_hours" in patch:
        ttl = int(patch["ttl_hours"])
        if not 1 <= ttl <= 72:
            raise ValueError("ttl_hours must be 1..72")
        out["ttl_hours"] = ttl
    if "triggers" in patch:
        out["triggers"] = {k: bool((patch["triggers"] or {}).get(k, cfg["triggers"][k])) for k in TRIGGERS}
    if "streak_days" in patch:
        out["streak_days"] = max(3, min(30, int(patch["streak_days"])))
    if "max_pending" in patch:
        out["max_pending"] = max(1, min(20, int(patch["max_pending"])))
    if "trigger_prizes" in patch:
        tp = {}
        for trig, rows in (patch["trigger_prizes"] or {}).items():
            if trig not in TRIGGERS:
                raise ValueError(f"unknown trigger: {trig}")
            if rows:
                tp[trig] = _clean_prizes(rows)
        out["trigger_prizes"] = tp
    if "prizes" in patch:
        out["prizes"] = _clean_prizes(patch["prizes"])
    return out


def _clean_prizes(prizes) -> list:
    rows = []
    for row in prizes or []:
        typ = row.get("type")
        if typ not in PRIZE_TYPES:
            raise ValueError(f"unknown prize type: {typ}")
        value, weight = float(row.get("value") or 0), float(row.get("weight") or 0)
        if value <= 0 or weight < 0 or (typ == "discount" and value > 100):
            raise ValueError(f"bad value/weight for {typ}")
        rows.append({"type": typ, "value": int(value) if value.is_integer() else value,
                     "weight": weight, "enabled": bool(row.get("enabled", True))})
    if not any(r["enabled"] and r["weight"] > 0 for r in rows):
        raise ValueError("at least one enabled prize with weight > 0 is required")
    return rows


def generate_scratch_prize(rng=_rng, prizes: list | None = None) -> dict:
    """جائزة عشوائية بتوزيع احتمالي مرجّح (weighted random). الجدول من لوحة الأدمن، وإلا PRIZE_TABLE."""
    table = [p for p in (prizes or default_config()["prizes"]) if p.get("enabled", True) and p.get("weight", 0) > 0]
    pick = rng.choices(table, weights=[p["weight"] for p in table], k=1)[0]
    return {"type": pick["type"], "value": pick["value"]}


class RewardError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


# ───────────────────────── منح البطاقات ─────────────────────────
def grant_card(db, uid, event: str, now: float | None = None, force: bool = False):
    """يمنح بطاقة واحدة لهذا المستخدم لهذا الحدث. يعيد معرّف البطاقة، أو None إن مُنحت سابقًا
    أو كان النظام/هذا المحفز معطّلًا من لوحة الأدمن (force=True لمنح الأدمن اليدوي)."""
    now = time.time() if now is None else now
    if not force:
        cfg = get_config(db)
        if not cfg["enabled"] or not cfg["triggers"].get(trigger_of(event), True):
            return None
    card_id = f"{uid}_{event}"
    try:
        db.collection(CARDS).document(card_id).create(
            {"uid": str(uid), "event": event, "status": "new", "prize": None, "created_at": now, "used": False}
        )
    except AlreadyExists:
        return None
    user = db.collection("users").document(str(uid))
    snap = user.get()
    pending = list(((snap.to_dict() or {}).get("scratch_pending") or []) if snap.exists else [])
    if not force and len(pending) >= int(get_config(db).get("max_pending") or 5):  # لا تكديس بطاقات بلا حد
        db.collection(CARDS).document(card_id).delete()
        return None
    if card_id not in pending:
        pending.append(card_id)
    user.set({"achievements": {event: now}, "scratch_pending": pending}, merge=True)
    return card_id


def _drop_pending(db, uid, card_id):
    user = db.collection("users").document(str(uid))
    snap = user.get()
    if snap.exists:
        pending = [c for c in ((snap.to_dict() or {}).get("scratch_pending") or []) if c != card_id]
        user.set({"scratch_pending": pending}, merge=True)


# ───────────────────────── سلسلة التداول (7 أيام عمل متتالية) ─────────────────────────
def _prev_weekday(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() >= 5:  # السبت/الأحد: سوق الفوركس مغلق فلا تكسر السلسلة
        d -= timedelta(days=1)
    return d


def streak_start(day_keys, min_len: int = STREAK_DAYS):
    """أحدث سلسلة أيام تداول متتالية (أيام العمل). يعيد مفتاح يوم بدايتها إن بلغت min_len، وإلا None."""
    days = sorted({date.fromisoformat(k) for k in (day_keys or []) if k}, reverse=True)
    if not days:
        return None
    run = [days[0]]
    for d in days[1:]:
        if d == _prev_weekday(run[-1]):
            run.append(d)
        elif d < _prev_weekday(run[-1]):
            break
    return run[-1].isoformat() if len(run) >= min_len else None


# ───────────────────────── التأهل ─────────────────────────
PHONE_SALT = os.getenv("PHONE_HASH_SALT", os.getenv("WEBHOOK_SECRET", ""))


def phone_hash(phone: str) -> str:
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    return hashlib.sha256(f"{PHONE_SALT}:{digits}".encode()).hexdigest()


def verify_phone(db, uid, phone: str) -> bool:
    """يربط رقم الهاتف بحساب تلجرام واحد فقط. يعيد True إن وُثّق هذا الحساب به."""
    h = phone_hash(phone)
    ref = db.collection(PHONES).document(h)
    try:
        ref.create({"uid": str(uid), "at": time.time()})
        owner = str(uid)
    except AlreadyExists:
        owner = str((ref.get().to_dict() or {}).get("uid"))
    ok = owner == str(uid)
    db.collection("users").document(str(uid)).set(
        {"phone_verified": ok, "phone_hash": h, "phone_duplicate": not ok}, merge=True
    )
    return ok


def check_eligibility(db, tg_user: dict, card: dict, card_id: str, require_phone: bool = True):
    """يرفع RewardError إن لم يكن المستخدم مؤهلًا لكشف البطاقة."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    uid = str(tg_user["id"])
    # 1) نفس الحدث لنفس Telegram User ID مرة واحدة فقط
    same = (
        db.collection(CARDS)
        .where(filter=FieldFilter("uid", "==", uid))
        .where(filter=FieldFilter("event", "==", card["event"]))
        .get()
    )
    if any(s.id != card_id for s in same):
        raise RewardError("duplicate_event", 409)
    # 2) حساب حقيقي: رقم هاتف موثّق (غير مستخدم لحساب آخر) أو اشتراك Telegram Premium
    if not require_phone:
        return
    snap = db.collection("users").document(uid).get()
    user = (snap.to_dict() or {}) if snap.exists else {}
    if not (user.get("phone_verified") or tg_user.get("is_premium")):
        raise RewardError("phone_verification_required", 403)


# ───────────────────────── كشف البطاقة ─────────────────────────
def _card(db, uid, card_id):
    snap = db.collection(CARDS).document(card_id).get()
    if not snap.exists or str((snap.to_dict() or {}).get("uid")) != str(uid):
        raise RewardError("card_not_found", 404)
    return snap.to_dict()


def sealed(prize: dict, card_id: str, secret: str) -> dict:
    """النتيجة كما تُرسل للواجهة: محتوى مرمّز + توقيع HMAC من الخادم (للعرض فقط؛ الخادم لا يثق به عائدًا)."""
    token = base64.urlsafe_b64encode(json.dumps({"card": card_id, **prize}).encode()).decode()
    sig = hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()
    return {"token": token, "sig": sig}


def claim(db, tg_user: dict, card_id: str | None, secret: str):
    """يولّد جائزة البطاقة (مرة واحدة) ويعيدها مختومة. استدعاء متكرر يعيد نفس الجائزة."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    uid = str(tg_user["id"])
    if not card_id:
        rows = db.collection(CARDS).where(filter=FieldFilter("uid", "==", uid)).get()
        new = sorted((r for r in rows if (r.to_dict() or {}).get("status") == "new"),
                     key=lambda r: r.to_dict().get("created_at") or 0)
        if not new:
            raise RewardError("no_card", 404)
        card_id = new[0].id
    card = _card(db, uid, card_id)
    cfg = get_config(db)
    if not cfg["enabled"]:
        raise RewardError("rewards_disabled", 403)
    check_eligibility(db, tg_user, card, card_id, cfg["require_phone"])
    prize = card.get("prize")
    if not prize:
        trig = trigger_of(card.get("event"))
        prize = generate_scratch_prize(prizes=(cfg.get("trigger_prizes") or {}).get(trig) or cfg["prizes"])
        db.collection(CARDS).document(card_id).set({"prize": prize, "claimed_at": time.time()}, merge=True)
    return {"card_id": card_id, "status": card.get("status"), **sealed(prize, card_id, secret)}


def reveal(db, uid, card_id: str, now: float | None = None) -> dict:
    """تكشّف أكثر من 50%: تبدأ صلاحية الجائزة (بالساعات) وتظهر في محفظة المكافآت."""
    now = time.time() if now is None else now
    card = _card(db, uid, card_id)
    if not card.get("prize"):
        raise RewardError("not_claimed", 409)
    if card.get("status") != "revealed":
        ttl = int(get_config(db)["ttl_hours"])
        card.update(status="revealed", revealed_at=now, expires_at=now + ttl * 3600)
        db.collection(CARDS).document(card_id).set(
            {"status": "revealed", "revealed_at": now, "expires_at": card["expires_at"]}, merge=True
        )
        _drop_pending(db, uid, card_id)
    return public_reward(card_id, card, now)


# ───────────────────────── محفظة المكافآت ─────────────────────────
def reward_state(card: dict, now: float) -> str:
    if card.get("used"):
        return "used"
    return "active" if (card.get("expires_at") or 0) > now else "expired"


def public_reward(card_id: str, card: dict, now: float) -> dict:
    prize = card.get("prize") or {}
    return {
        "id": card_id,
        "event": card.get("event"),
        "type": prize.get("type"),
        "value": prize.get("value"),
        "earned_at": card.get("revealed_at"),
        "expires_at": card.get("expires_at"),
        "status": reward_state(card, now),
        "used_at": card.get("used_at"),
    }


def list_rewards(db, uid, now: float | None = None) -> dict:
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    cards, rewards = [], []
    for snap in db.collection(CARDS).where(filter=FieldFilter("uid", "==", str(uid))).stream():
        c = snap.to_dict() or {}
        if c.get("status") == "revealed":
            rewards.append(public_reward(snap.id, c, now))
        else:
            cards.append({"id": snap.id, "event": c.get("event"), "created_at": c.get("created_at")})
    cards.sort(key=lambda c: c["created_at"] or 0)
    rewards.sort(key=lambda r: (r["status"] != "active", -(r["earned_at"] or 0)))
    return {"cards": cards, "rewards": rewards}


# ───────────────────────── تطبيق الكوبون ─────────────────────────
def validate(db, uid, reward_id: str, allowed_types: set, now: float | None = None) -> dict:
    """يرفض أي جائزة ليست للمستخدم، أو لم تُكشف، أو مستخدمة، أو منتهية الصلاحية."""
    now = time.time() if now is None else now
    snap = db.collection(CARDS).document(reward_id).get()
    card = snap.to_dict() if snap.exists else None
    if not card or str(card.get("uid")) != str(uid) or card.get("status") != "revealed":
        raise RewardError("reward_not_found", 404)
    if card.get("used"):
        raise RewardError("reward_used", 409)
    if (card.get("expires_at") or 0) <= now:
        raise RewardError("reward_expired", 410)
    if (card.get("prize") or {}).get("type") not in allowed_types:
        raise RewardError("reward_not_applicable", 400)
    return card


def apply_to_amount(card: dict, amount: float) -> tuple[float, int]:
    """(المبلغ بعد الخصم، أيام إضافية تُمنح بعد نجاح الدفع)."""
    prize = card.get("prize") or {}
    if prize.get("type") == "discount":
        return amount * (1 - float(prize["value"]) / 100), 0
    if prize.get("type") == "free_days":
        return amount, int(prize["value"])
    return amount, 0


def mark_used(db, reward_id: str, order_id: str | None = None):
    db.collection(CARDS).document(reward_id).set(
        {"used": True, "used_at": time.time(), "used_order": order_id}, merge=True
    )


# ───────────────────────── أدوات الأدمن ─────────────────────────
def admin_issue_coupon(db, uid, typ: str, value, hours: int, now: float | None = None) -> str:
    """كوبون جاهز (جائزة مكشوفة) يمنحه الأدمن مباشرة لمستخدم."""
    if typ not in PRIZE_TYPES:
        raise RewardError("unknown_prize_type", 400)
    hours = int(hours)
    if not 1 <= hours <= 24 * 30:
        raise RewardError("bad_hours", 400)
    now = time.time() if now is None else now
    card_id = f"{uid}_admin_{int(now * 1000)}"
    db.collection(CARDS).document(card_id).create({
        "uid": str(uid), "event": "admin", "status": "revealed", "prize": {"type": typ, "value": value},
        "created_at": now, "claimed_at": now, "revealed_at": now, "expires_at": now + hours * 3600,
        "used": False, "issued_by_admin": True,
    })
    return card_id


def admin_list_cards(db, uid: str | None = None, limit: int = 200, now: float | None = None) -> dict:
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    q = db.collection(CARDS)
    if uid:
        q = q.where(filter=FieldFilter("uid", "==", str(uid)))
    rows, stats = [], {"total": 0, "new": 0, "active": 0, "used": 0, "expired": 0, "by_type": {}}
    for snap in q.stream():
        c = snap.to_dict() or {}
        state = "new" if c.get("status") != "revealed" else reward_state(c, now)
        typ = (c.get("prize") or {}).get("type")
        stats["total"] += 1
        stats[state] += 1
        if typ:
            stats["by_type"][typ] = stats["by_type"].get(typ, 0) + 1
        rows.append({"id": snap.id, "uid": c.get("uid"), "event": c.get("event"), "state": state,
                     "type": typ, "value": (c.get("prize") or {}).get("value"),
                     "created_at": c.get("created_at"), "expires_at": c.get("expires_at"),
                     "used_at": c.get("used_at"), "revoked": bool(c.get("revoked"))})
    rows.sort(key=lambda r: -(r["created_at"] or 0))
    return {"cards": rows[:limit], "stats": stats}


def admin_revoke(db, card_id: str):
    ref = db.collection(CARDS).document(card_id)
    if not ref.get().exists:
        raise RewardError("card_not_found", 404)
    ref.set({"used": True, "revoked": True, "used_at": time.time(), "used_order": "revoked_by_admin"}, merge=True)


def admin_extend(db, card_id: str, hours: int, now: float | None = None) -> float:
    now = time.time() if now is None else now
    ref = db.collection(CARDS).document(card_id)
    snap = ref.get()
    if not snap.exists or (snap.to_dict() or {}).get("status") != "revealed":
        raise RewardError("card_not_found", 404)
    new_exp = max(now, float(snap.to_dict().get("expires_at") or 0)) + int(hours) * 3600
    ref.set({"expires_at": new_exp}, merge=True)
    return new_exp
