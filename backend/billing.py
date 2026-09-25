"""
AW Billing — الإعدادات العامة، الباقات، والإحالة.
وحدة منفصلة لإبقاء main.py قابلاً للقراءة رغم اتساع النظام.
"""
import secrets
import string
import time

DEFAULT_SETTINGS = {
    "registration_policy": "both",  # both | real | demo
    "leverage_min": 0,               # 0 = بلا حد أدنى
    "leverage_max": 0,               # 0 = بلا حد أقصى
    "referral_enabled": True,
    "referral_days": 7,
    "kill_switch": False,
    # الفترة التجريبية المشروطة للتداول الآلي (أول ربط فقط): حساب سنت، أو لوت لا يتجاوز trial_max_lot
    "trial_enabled": False,
    "trial_days": 3,          # بين 3 و7
    "trial_max_lot": 0.01,    # 0 = لا تجربة للحسابات العادية (سنت فقط)
    # مركز التحكم: يظهر أثرها في التطبيق مباشرة
    "support_url": "",         # رابط الدعم الفني (t.me/... أو https://...)
    "pay_ton_enabled": True,
    "pay_crypto_enabled": True,
    "pay_stars_enabled": True,
    "announcement_ar": "",     # شريط إعلان أعلى الرئيسية (فارغ = لا يظهر)
    "announcement_en": "",
    "alert_large_payment_usd": 400,  # تنبيه فوري في اللوحة لأي دفعة بهذا المبلغ أو أكثر
}

_SETTINGS_DOC = ("config", "settings")


def get_settings(db) -> dict:
    ref = db.collection(_SETTINGS_DOC[0]).document(_SETTINGS_DOC[1])
    snap = ref.get()
    data = snap.to_dict() if snap.exists else {}
    return {**DEFAULT_SETTINGS, **data}


def update_settings(db, patch: dict) -> dict:
    ref = db.collection(_SETTINGS_DOC[0]).document(_SETTINGS_DOC[1])
    clean = {k: v for k, v in patch.items() if k in DEFAULT_SETTINGS}
    ref.set(clean, merge=True)
    return get_settings(db)


def account_type_allowed(settings: dict, account_type: str) -> bool:
    policy = settings.get("registration_policy", "both")
    if policy == "both":
        return True
    return account_type == policy


def leverage_allowed(settings: dict, leverage) -> bool:
    lo = settings.get("leverage_min") or 0
    hi = settings.get("leverage_max") or 0
    if leverage is None:
        return True
    if lo and leverage < lo:
        return False
    if hi and leverage > hi:
        return False
    return True


def list_packages(db, active_only=False):
    docs = db.collection("packages").order_by("sort_order").stream()
    rows = []
    for d in docs:
        row = d.to_dict() or {}
        row["id"] = d.id
        if active_only and not row.get("active", True):
            continue
        rows.append(row)
    return rows


def _features(v) -> list:
    """قائمة مزايا الباقة: تقبل قائمة أو نصًا (سطر لكل ميزة)."""
    items = v.splitlines() if isinstance(v, str) else list(v or [])
    return [str(x).strip() for x in items if str(x).strip()][:12]


TEXT_FIELDS = ("tagline_ar", "tagline_en")
LIST_FIELDS = ("features_ar", "features_en")


def create_package(db, data: dict) -> str:
    ref = db.collection("packages").document()
    ref.set(
        {
            "name_ar": data["name_ar"],
            "name_en": data["name_en"],
            "price_usd": float(data["price_usd"]),
            "duration_days": int(data["duration_days"]),
            "active": bool(data.get("active", True)),
            "sort_order": int(data.get("sort_order", 0)),
            "price_stars": int(data["price_stars"]) if data.get("price_stars") else None,
            "featured": bool(data.get("featured", False)),
            **{k: str(data.get(k) or "").strip() for k in TEXT_FIELDS},
            **{k: _features(data.get(k)) for k in LIST_FIELDS},
        }
    )
    return ref.id


def update_package(db, pkg_id: str, patch: dict):
    allowed = {"name_ar", "name_en", "price_usd", "price_stars", "duration_days", "active", "sort_order", "featured",
               *TEXT_FIELDS, *LIST_FIELDS}
    clean = {k: (_features(v) if k in LIST_FIELDS else v) for k, v in patch.items() if k in allowed}
    db.collection("packages").document(pkg_id).update(clean)


# باقات مقترحة يمكن استيرادها بضغطة من لوحة الأدمن ثم تعديلها بالكامل
DEFAULT_PACKAGES = [
    {"name_ar": "AW Starter", "name_en": "AW Starter", "price_usd": 19, "duration_days": 30, "sort_order": 1,
     "tagline_ar": "مناسب للمبتدئين", "tagline_en": "Great for beginners",
     "features_ar": ["مدة الاشتراك 30 يومًا", "مناسب للمبتدئين", "تشغيل آلي كامل للخدمة"],
     "features_en": ["30-day subscription", "Great for beginners", "Fully automated operation"]},
    {"name_ar": "AW Pro", "name_en": "AW Pro", "price_usd": 129, "duration_days": 30, "sort_order": 2, "featured": True,
     "tagline_ar": "الأكثر طلبًا", "tagline_en": "Most popular",
     "features_ar": ["مدة الاشتراك 30 يومًا", "نماذج تشغيل متعددة", "إمكانية تشغيل وإيقاف النموذج", "خدمة دعم ذكية عبر شات AI"],
     "features_en": ["30-day subscription", "Multiple trading models", "Start / stop the model anytime", "Smart AI chat support"]},
    {"name_ar": "AW Premium", "name_en": "AW Premium", "price_usd": 449, "duration_days": 90, "sort_order": 3,
     "tagline_ar": "للمحترفين", "tagline_en": "For professionals",
     "features_ar": ["مدة الاشتراك 90 يومًا", "إمكانية ربط حسابين تداول", "إمكانية تشغيل وإيقاف النموذج", "إعدادات تحكم متقدمة", "خدمة دعم ذكية عبر شات AI"],
     "features_en": ["90-day subscription", "Link two trading accounts", "Start / stop the model anytime", "Advanced control settings", "Smart AI chat support"]},
]


def seed_packages(db) -> list:
    """يضيف الباقات المقترحة غير الموجودة (بالاسم الإنجليزي) ويعيد معرّفاتها."""
    have = {p.get("name_en") for p in list_packages(db)}
    return [create_package(db, p) for p in DEFAULT_PACKAGES if p["name_en"] not in have]


def delete_package(db, pkg_id: str):
    db.collection("packages").document(pkg_id).delete()


_ALPHABET = string.ascii_uppercase + string.digits


def gen_referral_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(6))


def ensure_referral_code(db, uid) -> str:
    ref = db.collection("users").document(str(uid))
    snap = ref.get()
    data = snap.to_dict() or {}
    code = data.get("referral_code")
    if code:
        return code
    for _ in range(5):
        code = gen_referral_code()
        clash = db.collection("users").where("referral_code", "==", code).limit(1).get()
        if not clash:
            ref.set({"referral_code": code}, merge=True)
            return code
    return gen_referral_code()


def find_by_referral_code(db, code: str):
    if not code:
        return None
    docs = db.collection("users").where("referral_code", "==", code.strip().upper()).limit(1).get()
    return docs[0].id if docs else None


# ───────────────────────── الاشتراك ─────────────────────────
def is_subscription_active(data: dict) -> bool:
    sub = data.get("subscription") or {}
    return (sub.get("expires_at") or 0) > time.time()


def _add_days(db, uid, days):
    ref = db.collection("users").document(str(uid))
    snap = ref.get()
    data = snap.to_dict() or {}
    now = time.time()
    current_expiry = (data.get("subscription") or {}).get("expires_at") or 0
    base = current_expiry if current_expiry > now else now
    new_expiry = base + days * 86400
    ref.set({"subscription": {"expires_at": new_expiry, "status": "active"}}, merge=True)
    return new_expiry


def extend_subscription(db, uid, package: dict):
    ref = db.collection("users").document(str(uid))
    ref.set(
        {"subscription": {"package_id": package["id"], "package_name_ar": package.get("name_ar"), "package_name_en": package.get("name_en")}},
        merge=True,
    )
    return _add_days(db, uid, package["duration_days"])


def grant_referral_bonus_if_eligible(db, uid, days):
    """يمنح المُحيل والمُحال عليه أيامًا إضافية عند أول دفعة ناجحة للمُحال، مرة واحدة فقط."""
    ref = db.collection("users").document(str(uid))
    snap = ref.get()
    data = snap.to_dict() or {}
    if data.get("referral_reward_granted"):
        return None
    referrer_id = data.get("referred_by")
    if not referrer_id:
        return None
    ref.set({"referral_reward_granted": True}, merge=True)
    _add_days(db, uid, days)
    _add_days(db, referrer_id, days)
    return referrer_id


# ───────────────────────── الفترة التجريبية للتداول الآلي ─────────────────────────
CENT_CURRENCIES = {"USC", "EUC", "USX"}
TRIAL_MIN_DAYS, TRIAL_MAX_DAYS = 3, 7


def is_cent_account(live: dict | None, server: str | None) -> bool:
    currency = str((live or {}).get("currency") or "").upper()
    return currency in CENT_CURRENCIES or "cent" in (server or "").lower()


def trial_days(settings: dict) -> int:
    try:
        d = int(settings.get("trial_days") or TRIAL_MIN_DAYS)
    except (TypeError, ValueError):
        d = TRIAL_MIN_DAYS
    return max(TRIAL_MIN_DAYS, min(TRIAL_MAX_DAYS, d))


def trial_fields_on_first_link(settings: dict, previous: dict | None, live: dict, server: str, now: float) -> dict:
    """حقول تُضاف لمستند المستخدم عند الربط. التجربة تُمنح عند أول ربط فقط (trial_checked يمنع التكرار)."""
    if (previous or {}).get("trial_checked"):
        return {}
    fields = {"trial_checked": True}
    if not settings.get("trial_enabled"):
        return fields
    cent = is_cent_account(live, server)
    try:
        max_lot = float(settings.get("trial_max_lot") or 0)
    except (TypeError, ValueError):
        max_lot = 0.0
    if not cent and max_lot <= 0:
        return fields  # حساب عادي ولا حد لوت مضبوط: لا تجربة
    days = trial_days(settings)
    fields["trial_expires_at"] = now + days * 86400
    fields["trial"] = {"started_at": now, "days": days, "cent_account": cent, "max_lot": None if cent else max_lot}
    return fields


def auto_trade_allowed(data: dict, volume: float | None = None, now: float | None = None) -> tuple[bool, str]:
    """يُستدعى قبل كل عملية تداول آلي. يرجع (مسموح؟، السبب).
    الاشتراك الفعّال يسمح دائمًا؛ وإلا فالتجربة الفعّالة: حساب سنت بلا قيد، أو حجم لوت <= الحد."""
    now = time.time() if now is None else now
    if is_subscription_active(data):
        return True, "subscription"
    exp = data.get("trial_expires_at") or 0
    if not exp:
        return False, "no_subscription"
    if exp <= now:
        return False, "trial_expired"
    trial = data.get("trial") or {}
    if trial.get("cent_account"):
        return True, "trial_cent"
    max_lot = float(trial.get("max_lot") or 0)
    if volume is None:
        return False, "volume_required"
    if max_lot > 0 and float(volume) <= max_lot:
        return True, "trial_lot"
    return False, "lot_exceeds_trial_limit"
