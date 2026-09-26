"""
AW Admin Access — صلاحيات فريق العمل وسجل العمليات في لوحة التحكم.

الأدوار:
  owner    : مالك (من ADMIN_IDS في .env) — كل شيء، ومنه إدارة الفريق
  manager  : مدير — كل الأقسام عدا إدارة الفريق
  support  : دعم فني — المستخدمون والمكافآت (قراءة/كتابة) + الإحصاءات والنظام (قراءة)
  viewer   : مشاهد — الإحصاءات والمستخدمون والنظام والدعم (قراءة فقط)
أقسام جديدة: support (التذاكر والمساعد الذكي والأخطاء)، notifications (الإشعارات ونافذة التحديثات)،
ton (محفظة TON — العمليات الحساسة تتطلب OTP إضافيًا عبر البوت).
الأعضاء (غير المالكين) في config/staff: {members: {telegram_id: {role, name, perms?, scope, agent, added_at}}}
  perms : صلاحيات مخصّصة لكل صفحة تتجاوز صلاحيات الدور (اختياري)
  scope : ما يراه داخل الأقسام (كل التذاكر أو المسندة إليه فقط، إخفاء المبالغ/بيانات التواصل)
  agent : موظف دعم يستلم تذاكر بالتوزيع العادل (التخصصات، اللغات، الحد الأقصى، الترتيب، متاح/غير متاح)
"""
import json
import re
import time

ROLES = ("owner", "manager", "support", "viewer")
ROLE_LABEL = {"owner": "مالك", "manager": "مدير", "support": "دعم فني", "viewer": "مشاهد"}

# كل صفحة في اللوحة قسم مستقل بصلاحية خاصة (rw = قراءة وتعديل، r = عرض فقط، غيابه = مخفي تمامًا)
AREA_LABEL = {
    "ceo": "التقارير والإحصاءات", "analytics": "التحليلات وتتبّع الزوار", "system": "حالة النظام", "users": "المستخدمون",
    "packages": "الباقات", "rewards": "المكافآت والكوبونات", "gateway": "بوابة الدفع", "ton": "محفظة TON",
    "support": "الدعم الفني", "notifications": "إرسال الإشعارات", "announcements": "نافذة التحديثات", "cards": "بطاقات رسائل البوت",
    "growth": "النمو والتسويق", "leaderboard": "ترتيب الأسبوع", "design": "استوديو التصميم", "control": "مركز التحكم",
    "servers": "خوادم MT5", "export": "تصدير البيانات", "staff": "فريق العمل", "audit": "سجل العمليات",
}
ALL_AREAS = tuple(AREA_LABEL)

# الصلاحيات الافتراضية لكل دور (نقطة بداية؛ يمكن للمالك تخصيص كل عضو بمفرده)
PERMS = {
    "owner": {a: "rw" for a in ALL_AREAS},
    "manager": {**{a: "rw" for a in ALL_AREAS if a not in ("staff", "audit", "ton", "gateway")}, "audit": "r", "ton": "r", "gateway": "r"},
    "support": {"ceo": "r", "analytics": "r", "users": "rw", "rewards": "rw", "system": "r", "support": "rw",
                "notifications": "r", "announcements": "r", "cards": "r"},
    "viewer": {"ceo": "r", "analytics": "r", "users": "r", "system": "r", "support": "r"},
}

# القسم حسب بادئة المسار (الأطول أولًا عند التداخل)
AREAS = [
    ("/api/admin/users", "users"), ("/api/admin/stats", "users"), ("/api/admin/referrals", "users"),
    ("/api/admin/ceo", "ceo"), ("/api/admin/analytics", "analytics"), ("/api/admin/rewards", "rewards"), ("/api/admin/packages", "packages"),
    ("/api/admin/settings", "control"), ("/api/admin/design", "design"), ("/api/admin/leaderboard", "leaderboard"), ("/api/admin/servers", "servers"),
    ("/api/admin/staff", "staff"), ("/api/admin/audit", "audit"), ("/api/system/status", "system"),
    ("/api/admin/support", "support"), ("/api/admin/errors", "support"), ("/api/admin/notifications", "notifications"),
    ("/api/admin/announcements", "announcements"), ("/api/admin/growth", "growth"), ("/api/admin/export", "export"),
    ("/api/admin/media", "announcements"), ("/api/admin/cards", "cards"), ("/api/admin/ton", "ton"), ("/api/admin/gateway", "gateway"),
]
OPEN_PATHS = {"/api/admin/verify", "/api/admin/logout", "/api/admin/me", "/api/admin/support/agents/me"}  # الأخير: العضو يبدّل توفّره هو فقط

# خيارات الرؤية لكل عضو (ما يراه وما لا يراه داخل الأقسام المسموحة)
SCOPE_DEFAULT = {"tickets": "all", "hide_money": False, "hide_contacts": False}
SKILLS = {"payments": "المدفوعات والاشتراكات", "technical": "المشاكل التقنية والمزامنة", "account": "ربط الحسابات", "general": "استفسارات عامة"}
AGENT_DEFAULT = {"enabled": False, "available": True, "skills": [], "langs": [], "max_active": 0, "order": 0}

_STAFF = {"v": None, "at": 0.0}
STAFF_TTL = 30


def area_for(path: str):
    for prefix, area in AREAS:
        if path.startswith(prefix):
            return area
    return None


def staff_members(db) -> dict:
    if _STAFF["v"] is not None and time.time() - _STAFF["at"] < STAFF_TTL:
        return _STAFF["v"]
    snap = db.collection("config").document("staff").get()
    members = ((snap.to_dict() or {}).get("members") or {}) if snap.exists else {}
    _STAFF.update(v=members, at=time.time())
    return members


def invalidate():
    _STAFF["v"] = None


def role_of(db, admin_ids: set, uid) -> str | None:
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return None
    if uid in admin_ids:
        return "owner"
    m = staff_members(db).get(str(uid))
    return m.get("role") if m and m.get("role") in ROLES[1:] else None


def clean_perms(raw) -> dict | None:
    """صلاحيات مخصّصة لعضو: {قسم: r|rw}. إدارة الفريق تبقى للمالك وحده (لا يمكن منح تعديلها)."""
    if raw is None:
        return None
    out = {}
    for a, v in (raw or {}).items():
        if a in AREA_LABEL and v in ("r", "rw"):
            out[a] = "r" if a == "staff" else v
    return out


def clean_scope(raw) -> dict:
    raw = raw or {}
    return {"tickets": "assigned" if raw.get("tickets") == "assigned" else "all",
            "hide_money": bool(raw.get("hide_money")), "hide_contacts": bool(raw.get("hide_contacts"))}


def clean_agent(raw) -> dict:
    raw = raw or {}
    return {"enabled": bool(raw.get("enabled")), "available": raw.get("available", True) is not False,
            "skills": [s for s in (raw.get("skills") or []) if s in SKILLS][:4],
            "langs": [x for x in (raw.get("langs") or []) if x in ("ar", "en")][:2],
            "max_active": max(0, min(200, int(raw.get("max_active") or 0))), "order": max(0, min(999, int(raw.get("order") or 0)))}


def perms_of(db, admin_ids: set, uid) -> dict:
    """الصلاحيات الفعلية: المالك كل شيء، والعضو صلاحياته المخصّصة إن وُجدت وإلا صلاحيات دوره."""
    role = role_of(db, admin_ids, uid)
    if not role:
        return {}
    if role == "owner":
        return dict(PERMS["owner"])
    m = staff_members(db).get(str(int(uid))) or {}
    custom = clean_perms(m.get("perms")) if isinstance(m.get("perms"), dict) else None
    return custom if custom is not None else dict(PERMS.get(role, {}))


def scope_of(db, admin_ids: set, uid) -> dict:
    try:
        if int(uid) in admin_ids:
            return dict(SCOPE_DEFAULT)
    except (TypeError, ValueError):
        return dict(SCOPE_DEFAULT)
    return clean_scope((staff_members(db).get(str(int(uid))) or {}).get("scope"))


def allowed(role_or_perms, area: str | None, method: str) -> bool:
    """role_or_perms: اسم دور (توافق قديم) أو قاموس الصلاحيات الفعلية للعضو."""
    if not role_or_perms:
        return False
    if area is None:
        return True  # مسارات عامة للمشرفين (مثل /me)
    perms = role_or_perms if isinstance(role_or_perms, dict) else PERMS.get(role_or_perms, {})
    level = perms.get(area)
    if not level:
        return False
    return method in ("GET", "HEAD", "OPTIONS") or level == "rw"


# ───────────── الجهاز والعنوان ─────────────
def client_ip(headers: dict, fallback: str | None) -> str:
    fwd = headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or headers.get("x-real-ip", "") or (fallback or "")


def parse_device(ua: str) -> dict:
    ua = ua or ""
    os_ = ("iOS" if re.search(r"iPhone|iPad|iPod", ua) else "Android" if "Android" in ua else
           "Windows" if "Windows" in ua else "macOS" if "Mac OS X" in ua or "Macintosh" in ua else
           "Linux" if "Linux" in ua else "—")
    browser = ("Telegram" if "Telegram" in ua else "Edge" if "Edg/" in ua else "Opera" if "OPR/" in ua else
               "Firefox" if "Firefox/" in ua else "Chrome" if "Chrome/" in ua else "Safari" if "Safari/" in ua else "—")
    model = ""
    m = re.search(r"Android [\d.]+; ([^;)]+)", ua)
    if m:
        model = m.group(1).strip()
    elif "iPhone" in ua:
        model = "iPhone"
    elif "iPad" in ua:
        model = "iPad"
    mobile = bool(re.search(r"Mobile|Android|iPhone|iPad", ua))
    return {"os": os_, "browser": browser, "model": model, "type": "mobile" if mobile else "desktop"}


SECRET_KEYS = {"token", "code", "password", "mt5_password", "photo", "story", "post", "secret", "support_bot_token", "boc", "api_hash", "gemini_api_key", "session"}


def summarize_body(raw: bytes, limit: int = 1500) -> str:
    """ملخص آمن لمحتوى الطلب: تُخفى المفاتيح الحساسة وتُقصّ القيم الطويلة."""
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except ValueError:
        return f"<{len(raw)} bytes>"

    def clean(v, depth=0):
        if isinstance(v, dict):
            return {k: ("•••" if k in SECRET_KEYS else clean(x, depth + 1)) for k, x in list(v.items())[:40]}
        if isinstance(v, list):
            return [clean(x, depth + 1) for x in v[:15]] + ([f"… +{len(v) - 15}"] if len(v) > 15 else [])
        if isinstance(v, str) and len(v) > 160:
            return v[:160] + "…"
        return v

    out = json.dumps(clean(data), ensure_ascii=False)
    return out[:limit] + ("…" if len(out) > limit else "")


ACTION_LABEL = [
    (r"^POST /api/admin/users/[^/]+/decision$", "قرار على طلب ربط"),
    (r"^PUT /api/admin/settings$", "تعديل الإعدادات العامة"),
    (r"^POST /api/admin/packages/seed$", "استيراد الباقات المقترحة"),
    (r"^POST /api/admin/packages$", "إضافة باقة"),
    (r"^PUT /api/admin/packages/", "تعديل باقة"),
    (r"^DELETE /api/admin/packages/", "حذف باقة"),
    (r"^PUT /api/admin/rewards/config$", "تعديل إعدادات المكافآت"),
    (r"^POST /api/admin/rewards/grant$", "منح بطاقة/كوبون"),
    (r"^POST /api/admin/rewards/[^/]+/revoke$", "إلغاء كوبون"),
    (r"^POST /api/admin/rewards/[^/]+/extend$", "تمديد كوبون"),
    (r"^PUT /api/admin/leaderboard$", "تعديل الترتيب"),
    (r"^POST /api/admin/leaderboard/photo$", "رفع صورة منافس"),
    (r"^POST /api/admin/servers/import$", "استيراد خوادم"),
    (r"^POST /api/admin/servers/backfill$", "مزامنة الخوادم"),
    (r"^DELETE /api/admin/servers/", "حذف خادم"),
    (r"^PUT /api/admin/staff$", "إضافة/تعديل عضو فريق"),
    (r"^DELETE /api/admin/staff/", "إزالة عضو فريق"),
    (r"^PUT /api/admin/support/config$", "تعديل إعدادات الدعم"),
    (r"^POST /api/admin/support/tickets/[^/]+/reply$", "رد على تذكرة دعم"),
    (r"^POST /api/admin/support/tickets/[^/]+/status$", "تغيير حالة تذكرة"),
    (r"^POST /api/admin/support/kb$", "إضافة لقاعدة المعرفة"),
    (r"^POST /api/admin/support/tickets/[^/]+/assign$", "إسناد تذكرة لموظف"),
    (r"^POST /api/admin/support/tickets/[^/]+/draft$", "مسودة رد بالذكاء الاصطناعي"),
    (r"^POST /api/admin/support/agents/me$", "تغيير التوفّر لاستلام التذاكر"),
    (r"^DELETE /api/admin/support/kb/", "حذف من قاعدة المعرفة"),
    (r"^POST /api/admin/notifications/broadcast$", "إرسال إشعار"),
    (r"^POST /api/admin/announcements/seed$", "استعادة التحديث الافتراضي"),
    (r"^POST /api/admin/announcements$", "إضافة نافذة تحديثات"),
    (r"^PUT /api/admin/announcements/", "تعديل نافذة تحديثات"),
    (r"^DELETE /api/admin/announcements/", "حذف نافذة تحديثات"),
    (r"^POST /api/admin/media/image$", "رفع صورة"),
    (r"^POST /api/admin/support/suggestions/[^/]+/approve$", "اعتماد اقتراح لقاعدة المعرفة"),
    (r"^DELETE /api/admin/support/suggestions/[^/]+$", "رفض اقتراح لقاعدة المعرفة"),
    (r"^PUT /api/admin/gateway$", "تعديل إعدادات بوابة الدفع"),
    (r"^POST /api/admin/gateway/invoices/[^/]+/accept$", "قبول فاتورة يدويًا (بوابة الدفع)"),
    (r"^POST /api/admin/gateway/invoices/[^/]+/cancel$", "إلغاء فاتورة (بوابة الدفع)"),
    (r"^POST /api/admin/gateway/invoices/[^/]+/check$", "فحص فاتورة (بوابة الدفع)"),
    (r"^POST /api/admin/gateway/sweep$", "تجميع يدوي (بوابة الدفع)"),
    (r"^POST /api/admin/ton/otp$", "طلب رمز تحقق TON"),
    (r"^POST /api/admin/ton/execute$", "تنفيذ عملية TON"),
    (r"^POST /api/admin/ton/transfer-result$", "نتيجة تحويل TON"),
    (r"^POST /api/admin/growth/coupons$", "حفظ كوبون حملة"),
    (r"^DELETE /api/admin/growth/coupons/", "حذف كوبون"),
    (r"^POST /api/admin/growth/gifts$", "إنشاء رابط هدية"),
    (r"^DELETE /api/admin/growth/gifts/", "حذف رابط هدية"),
    (r"^POST /api/admin/growth/campaigns$", "حفظ حملة"),
    (r"^DELETE /api/admin/growth/campaigns/", "حذف حملة"),
    (r"^PUT /api/admin/growth/automations/", "تعديل قاعدة أتمتة"),
    (r"^DELETE /api/admin/growth/automations/", "حذف قاعدة أتمتة"),
    (r"^POST /api/admin/growth/automations/run$", "تشغيل الأتمتة يدويًا"),
    (r"^POST /api/admin/packages/private$", "إرسال باقة خاصة لمستخدم"),
    (r"^POST /api/admin/logout$", "تسجيل خروج"),
    (r"^LOGIN", "تسجيل دخول"),
    (r"^EXPORT /api/admin/export/users", "تصدير بيانات المستخدمين"),
    (r"^EXPORT /api/admin/export/payments", "تصدير المدفوعات"),
    (r"^EXPORT /api/admin/export/tickets", "تصدير التذاكر"),
]


def action_label(method: str, path: str) -> str:
    key = f"{method} {path}"
    for pat, label in ACTION_LABEL:
        if re.search(pat, key):
            return label
    return key
