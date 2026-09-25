"""
AW Announcements — نافذة "ما الجديد" عند دخول المستخدم، بتحكم كامل من لوحة الأدمن.

announcements/{id}:
  enabled, priority (الأعلى أولًا), title/subtitle/body/cta بالعربية والإنجليزية، image (رابط https)،
  features: [{icon, title_ar, title_en, text_ar, text_en}]،
  frequency: once | every_open | daily | every_x_days (+ every_days)،
  audience: all | active | expired | no_sub | unlinked | linked،
  starts_at / ends_at (0 = بلا حد)، allow_dismiss (خيار "لا تظهر مرة أخرى")،
  version: يزيد عند "إعادة العرض للجميع" فيُعاد عرضها حتى لمن شاهدها.
حالة كل مستخدم: users.announce_seen.{id} = {at, count, version, dismissed}.
"""
import re
import time

COL = "announcements"
FREQUENCIES = ("once", "every_open", "daily", "every_x_days")
AUDIENCES = ("all", "active", "expired", "no_sub", "unlinked", "linked")
CTA_ACTIONS = ("close", "plans", "support", "url")
ICONS = ("bolt", "chart", "shield", "cloud", "headset", "bell", "trophy", "gift", "star", "wallet", "globe", "check")

DEFAULT = {
    "id": "launch",
    "enabled": True,
    "priority": 10,
    "frequency": "once",
    "every_days": 3,
    "audience": "all",
    "starts_at": 0,
    "ends_at": 0,
    "allow_dismiss": True,
    "image": "",
    "badge_ar": "إطلاق جديد",
    "badge_en": "New release",
    "title_ar": "AW ROBOT — التداول الآلي بمستوى جديد",
    "title_en": "AW ROBOT — Automated trading, re-engineered",
    "subtitle_ar": "نظام تداول خوارزمي يعمل نيابةً عنك على مدار الساعة، بشفافية كاملة وتحكم تام.",
    "subtitle_en": "An algorithmic trading system that works for you around the clock — fully transparent, fully in your control.",
    "features": [
        {"icon": "bolt", "title_ar": "تنفيذ آلي 24/7", "title_en": "24/7 automated execution",
         "text_ar": "خوارزميات تنفّذ الصفقات وتدير المخاطر على خوادم سحابية عالية السرعة — دون أن تُبقي هاتفك مفتوحًا.",
         "text_en": "Algorithms execute trades and manage risk on high-speed cloud servers — no need to keep your phone on."},
        {"icon": "chart", "title_ar": "أداء لحظي بوضوح", "title_en": "Live, crystal-clear performance",
         "text_ar": "رصيدك ونموك اليومي والأسبوعي والشهري وتحليلات مفصّلة في لوحة واحدة.",
         "text_en": "Balance, daily/weekly/monthly growth and deep analytics in one dashboard."},
        {"icon": "shield", "title_ar": "أمان بلا تنازلات", "title_en": "Security without compromise",
         "text_ar": "لا صلاحية لنا على السحب أو الإيداع — أموالك تبقى بينك وبين وسيطك فقط.",
         "text_en": "We have zero access to deposits or withdrawals — your funds stay between you and your broker."},
        {"icon": "headset", "title_ar": "دعم ذكي فوري", "title_en": "Instant smart support",
         "text_ar": "مساعد ذكي يعرف حالة حسابك ويحل المشكلات فورًا، مع فريق بشري عند الحاجة.",
         "text_en": "A smart assistant that knows your account and fixes issues instantly — with a human team when needed."},
        {"icon": "bell", "title_ar": "إشعارات لكل ما يهمك", "title_en": "Notifications that matter",
         "text_ar": "تنبيهات فورية للدفع والإيداع والصفقات وأي تغيير في حسابك.",
         "text_en": "Instant alerts for payments, deposits, trades and any change to your account."},
    ],
    "body_ar": "",
    "body_en": "",
    "footnote_ar": "التداول في الأسواق المالية ينطوي على مخاطر، والأداء السابق لا يضمن النتائج المستقبلية.",
    "footnote_en": "Trading financial markets involves risk; past performance does not guarantee future results.",
    "cta_label_ar": "ابدأ الآن",
    "cta_label_en": "Get started",
    "cta_action": "close",
    "cta_url": "",
    "version": 1,
    # الشكل (يُتحكَّم به من المعاينة الحية في لوحة التحكم)
    "style": {"accent": "#ff8a00", "accent2": "#ff5a00", "bg": "#0e0b09", "text": "#f5efe8", "width": 460,
              "position": "bottom", "radius": 26, "blur": 4},
}
STYLE_KEYS = {"accent", "accent2", "bg", "text", "width", "position", "radius", "blur"}
TEXT_FIELDS = ("badge_ar", "badge_en", "title_ar", "title_en", "subtitle_ar", "subtitle_en", "body_ar", "body_en",
               "footnote_ar", "footnote_en", "cta_label_ar", "cta_label_en")


def clean(patch: dict, current: dict | None = None) -> dict:
    cur = {**DEFAULT, **(current or {})}
    out = {}
    for k in TEXT_FIELDS:
        if k in patch:
            out[k] = str(patch[k] or "")[: 1500 if k.startswith("body") else 240]
    for k in ("enabled", "allow_dismiss"):
        if k in patch:
            out[k] = bool(patch[k])
    if "priority" in patch:
        out["priority"] = max(0, min(100, int(patch["priority"] or 0)))
    if "every_days" in patch:
        out["every_days"] = max(1, min(90, int(patch["every_days"] or 1)))
    for k, allowed in (("frequency", FREQUENCIES), ("audience", AUDIENCES), ("cta_action", CTA_ACTIONS)):
        if k in patch:
            if patch[k] not in allowed:
                raise ValueError(f"{k} invalid")
            out[k] = patch[k]
    for k in ("starts_at", "ends_at"):
        if k in patch:
            out[k] = max(0, float(patch[k] or 0))
    for k in ("image", "cta_url"):
        if k in patch:
            v = str(patch[k] or "").strip()
            if v and not v.startswith(("https://", "/api/media/")):
                raise ValueError(f"{k} must be https")
            out[k] = v[:400]
    if "features" in patch:
        rows = []
        for f in (patch["features"] or [])[:8]:
            if not (f.get("title_ar") or f.get("title_en")):
                continue
            rows.append({"icon": f.get("icon") if f.get("icon") in ICONS else "check",
                         **{k: str(f.get(k) or "")[:300] for k in ("title_ar", "title_en", "text_ar", "text_en")}})
        out["features"] = rows
    if "style" in patch:
        st = {**DEFAULT["style"], **(cur.get("style") or {})}
        for k, v in (patch["style"] or {}).items():
            if k not in STYLE_KEYS:
                continue
            if k in ("accent", "accent2", "bg", "text"):
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(v or "")):
                    raise ValueError(f"style.{k} must be #RRGGBB")
                st[k] = str(v)
            elif k == "position":
                if v not in ("bottom", "center"):
                    raise ValueError("style.position invalid")
                st[k] = v
            else:
                lim = {"width": (300, 760), "radius": (0, 40), "blur": (0, 12)}[k]
                st[k] = max(lim[0], min(lim[1], int(v)))
        out["style"] = st
    merged = {**cur, **out}
    if merged["ends_at"] and merged["starts_at"] and merged["ends_at"] <= merged["starts_at"]:
        raise ValueError("ends_at must be after starts_at")
    if patch.get("reset_views"):
        out["version"] = int(cur.get("version") or 1) + 1
    return out


def list_all(db) -> list:
    rows = [{**DEFAULT, **(d.to_dict() or {}), "id": d.id} for d in db.collection(COL).stream()]
    return sorted(rows, key=lambda r: (-int(r.get("priority") or 0), -(r.get("updated_at") or 0)))


def seed_default(db) -> dict:
    ref = db.collection(COL).document(DEFAULT["id"])
    if not ref.get().exists:
        ref.set({k: v for k, v in DEFAULT.items() if k != "id"} | {"updated_at": time.time()})
    return {**DEFAULT, **(ref.get().to_dict() or {}), "id": ref.id}


def in_audience(ann: dict, user: dict, now: float) -> bool:
    exp = ((user.get("subscription") or {}).get("expires_at")) or 0
    linked = user.get("status") == "approved"
    return {
        "all": True, "active": exp > now, "expired": bool(exp) and exp <= now, "no_sub": not exp,
        "unlinked": not linked, "linked": linked,
    }.get(ann.get("audience") or "all", True)


def due(ann: dict, seen: dict | None, now: float) -> bool:
    """هل يحين عرضها لهذا المستخدم الآن؟"""
    seen = seen or {}
    if int(seen.get("version") or 0) < int(ann.get("version") or 1):
        return True  # لم يشاهد هذه النسخة بعد
    if seen.get("dismissed"):
        return False
    last = float(seen.get("at") or 0)
    freq = ann.get("frequency") or "once"
    if freq == "every_open":
        return True
    if freq == "daily":
        return now - last >= 86400
    if freq == "every_x_days":
        return now - last >= int(ann.get("every_days") or 1) * 86400
    return False  # once


def pick(db, user: dict, now: float | None = None) -> dict | None:
    now = time.time() if now is None else now
    seen_map = user.get("announce_seen") or {}
    for ann in list_all(db):
        if not ann.get("enabled"):
            continue
        if ann.get("starts_at") and now < ann["starts_at"]:
            continue
        if ann.get("ends_at") and now > ann["ends_at"]:
            continue
        if not in_audience(ann, user, now):
            continue
        if due(ann, seen_map.get(ann["id"]), now):
            return {k: v for k, v in ann.items() if k not in ("updated_at", "updated_by")}
    return None


def mark_seen(db, uid, ann_id: str, dismiss: bool = False, now: float | None = None):
    now = time.time() if now is None else now
    ref = db.collection("users").document(str(uid))
    snap = ref.get()
    cur = (((snap.to_dict() or {}).get("announce_seen") or {}).get(ann_id) or {}) if snap.exists else {}
    ann = db.collection(COL).document(ann_id).get()
    version = int(((ann.to_dict() or {}).get("version")) or 1) if ann.exists else 1
    allow = bool((ann.to_dict() or {}).get("allow_dismiss", True)) if ann.exists else True
    ref.set({"announce_seen": {ann_id: {"at": now, "count": int(cur.get("count") or 0) + 1, "version": version,
                                        "dismissed": bool(dismiss and allow) or bool(cur.get("dismissed") and cur.get("version") == version)}}},
            merge=True)
