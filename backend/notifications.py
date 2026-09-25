"""
AW Notifications — مركز إشعارات المستخدم داخل التطبيق (🔔).

نوعان:
  • واردة تلقائيًا (notifications/{auto}): تُكتب عند نشاط المستخدم — دفع مؤكَّد، إيداع/سحب، صفقات مغلقة،
    تنبيه أمني (فشل الدخول لـ MT5، فكّ الربط)، تغيّر حالة الحساب، حالة تذكرة الدعم.
  • صادرة من الأدمن (broadcasts/{id}): لمستخدم واحد، أو مجموعة بفلتر، أو للجميع. تُحفظ كسجل دائم،
    وتُحسم قائمة المستلمين لحظة الإرسال (uids) — عدا "الجميع" فتُطابق كل مستخدم.
حالة القراءة: users.notif_seen_at — كل ما هو أحدث منها غير مقروء.
"""
import time

COL = "notifications"
BROADCASTS = "broadcasts"
KINDS = ("payment", "deposit", "trade", "security", "account", "support", "system", "broadcast")
FILTERS = ("active", "expired", "no_sub", "unlinked", "linked", "low_balance", "lang", "phone_prefix")
MAX_ITEMS = 60


def push(db, uid, kind: str, title_ar: str, title_en: str, body_ar: str = "", body_en: str = "", ref: str | None = None):
    """إشعار وارد لمستخدم واحد. لا يرفع استثناء أبدًا (الإشعار لا يُفشل العملية الأصلية)."""
    try:
        db.collection(COL).document().set({
            "uid": str(uid), "kind": kind if kind in KINDS else "system", "at": time.time(),
            "title_ar": title_ar[:120], "title_en": title_en[:120],
            "body_ar": body_ar[:600], "body_en": body_en[:600], "ref": ref,
        })
        return True
    except Exception:  # noqa: BLE001
        return False


# ───────────── مطابقة الفلاتر ─────────────
def matches(user: dict, flt: dict, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    exp = ((user.get("subscription") or {}).get("expires_at")) or 0
    linked = user.get("status") == "approved"
    checks = {
        "active": lambda v: (exp > now) == bool(v),
        "expired": lambda v: (bool(exp) and exp <= now) == bool(v),
        "no_sub": lambda v: (not exp) == bool(v),
        "unlinked": lambda v: (not linked) == bool(v),
        "linked": lambda v: linked == bool(v),
        "low_balance": lambda v: linked and float(((user.get("live") or {}).get("balance")) or 0) < float(v),
        "lang": lambda v: (user.get("language") or "") == v,
        "phone_prefix": lambda v: str(user.get("phone_prefix") or "").startswith(str(v).lstrip("+")),
    }
    for k, v in (flt or {}).items():
        if k in checks and v not in (None, "", False) and not checks[k](v):
            return False
    return True


def resolve(db, target: str, uid=None, flt: dict | None = None) -> list | None:
    """قائمة المستلمين: None = الجميع."""
    if target == "all":
        return None
    if target == "user":
        return [str(uid)] if uid else []
    now = time.time()
    return [d.id for d in db.collection("users").stream() if matches(d.to_dict() or {}, flt or {}, now)]


def broadcast(db, admin_id, target: str, title_ar: str, title_en: str, body_ar: str, body_en: str,
              uid=None, flt: dict | None = None) -> dict:
    uids = resolve(db, target, uid, flt)
    ref = db.collection(BROADCASTS).document()
    row = {"at": time.time(), "by": admin_id, "target": target, "filter": flt or {}, "uid": str(uid) if uid else None,
           "all": uids is None, "uids": uids or [], "count": None if uids is None else len(uids),
           "title_ar": title_ar[:120], "title_en": title_en[:120], "body_ar": body_ar[:1000], "body_en": body_en[:1000]}
    ref.set(row)
    return {"id": ref.id, **row}


def list_for(db, uid, user: dict | None = None) -> dict:
    uid = str(uid)
    from google.cloud.firestore_v1.base_query import FieldFilter

    items = [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(COL).where(filter=FieldFilter("uid", "==", uid)).stream()]
    for d in db.collection(BROADCASTS).order_by("at", direction="DESCENDING").limit(100).stream():
        b = d.to_dict() or {}
        if b.get("all") or uid in (b.get("uids") or []):
            items.append({"id": d.id, "kind": "broadcast", "at": b.get("at"), "title_ar": b.get("title_ar"),
                          "title_en": b.get("title_en"), "body_ar": b.get("body_ar"), "body_en": b.get("body_en")})
    items.sort(key=lambda x: -(x.get("at") or 0))
    items = items[:MAX_ITEMS]
    seen = float((user or {}).get("notif_seen_at") or 0)
    for x in items:
        x.pop("uid", None)
        x["unread"] = (x.get("at") or 0) > seen
    return {"items": items, "unread": sum(1 for x in items if x["unread"])}


def mark_read(db, uid):
    db.collection("users").document(str(uid)).set({"notif_seen_at": time.time()}, merge=True)
