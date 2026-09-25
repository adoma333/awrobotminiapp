"""
AW Admin Access — صلاحيات فريق العمل وسجل العمليات في لوحة التحكم.

الأدوار:
  owner    : مالك (من ADMIN_IDS في .env) — كل شيء، ومنه إدارة الفريق
  manager  : مدير — كل الأقسام عدا إدارة الفريق
  support  : دعم فني — المستخدمون والمكافآت (قراءة/كتابة) + الإحصاءات والنظام (قراءة)
  viewer   : مشاهد — الإحصاءات والمستخدمون والنظام والدعم (قراءة فقط)
أقسام جديدة: support (التذاكر والمساعد الذكي والأخطاء)، notifications (الإشعارات ونافذة التحديثات)،
ton (محفظة TON — العمليات الحساسة تتطلب OTP إضافيًا عبر البوت).
الأعضاء (غير المالكين) في config/staff: {members: {telegram_id: {role, name, added_at}}}.
"""
import json
import re
import time

ROLES = ("owner", "manager", "support", "viewer")
ROLE_LABEL = {"owner": "مالك", "manager": "مدير", "support": "دعم فني", "viewer": "مشاهد"}

# صلاحية كل دور على كل قسم: rw = قراءة وكتابة، r = قراءة فقط
PERMS = {
    "owner": {a: "rw" for a in ("ceo", "users", "rewards", "packages", "settings", "system", "staff", "audit",
                                 "support", "notifications", "ton")},
    "manager": {"ceo": "rw", "users": "rw", "rewards": "rw", "packages": "rw", "settings": "rw", "system": "rw", "audit": "r",
                "support": "rw", "notifications": "rw", "ton": "r"},
    "support": {"ceo": "r", "users": "rw", "rewards": "rw", "system": "r", "support": "rw", "notifications": "r"},
    "viewer": {"ceo": "r", "users": "r", "system": "r", "support": "r"},
}

# القسم حسب بادئة المسار
AREAS = [
    ("/api/admin/users", "users"), ("/api/admin/stats", "users"), ("/api/admin/referrals", "users"),
    ("/api/admin/ceo", "ceo"), ("/api/admin/rewards", "rewards"), ("/api/admin/packages", "packages"),
    ("/api/admin/settings", "settings"), ("/api/admin/leaderboard", "settings"), ("/api/admin/servers", "settings"),
    ("/api/admin/staff", "staff"), ("/api/admin/audit", "audit"), ("/api/system/status", "system"),
    ("/api/admin/support/accounts", "settings"),  # حسابات تلجرام الحقيقية: المالك والمدير فقط
    ("/api/admin/support", "support"), ("/api/admin/errors", "support"), ("/api/admin/notifications", "notifications"),
    ("/api/admin/announcements", "notifications"), ("/api/admin/growth", "packages"), ("/api/admin/export", "settings"), ("/api/admin/media", "notifications"), ("/api/admin/ton", "ton"),
]
OPEN_PATHS = {"/api/admin/verify", "/api/admin/logout", "/api/admin/me"}

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


def allowed(role: str | None, area: str | None, method: str) -> bool:
    if not role:
        return False
    if area is None:
        return True  # مسارات عامة للمشرفين (مثل /me)
    level = PERMS.get(role, {}).get(area)
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
    (r"^POST /api/admin/support/accounts$", "إضافة حساب دعم (طلب رمز)"),
    (r"^POST /api/admin/support/accounts/[^/]+/verify$", "تأكيد دخول حساب دعم"),
    (r"^PUT /api/admin/support/accounts/", "تعديل حساب دعم"),
    (r"^DELETE /api/admin/support/accounts/", "حذف حساب دعم"),
    (r"^POST /api/admin/support/tickets/[^/]+/reply$", "رد على تذكرة دعم"),
    (r"^POST /api/admin/support/tickets/[^/]+/status$", "تغيير حالة تذكرة"),
    (r"^POST /api/admin/support/kb$", "إضافة لقاعدة المعرفة"),
    (r"^DELETE /api/admin/support/kb/", "حذف من قاعدة المعرفة"),
    (r"^POST /api/admin/notifications/broadcast$", "إرسال إشعار"),
    (r"^POST /api/admin/announcements/seed$", "استعادة التحديث الافتراضي"),
    (r"^POST /api/admin/announcements$", "إضافة نافذة تحديثات"),
    (r"^PUT /api/admin/announcements/", "تعديل نافذة تحديثات"),
    (r"^DELETE /api/admin/announcements/", "حذف نافذة تحديثات"),
    (r"^POST /api/admin/media/image$", "رفع صورة"),
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
