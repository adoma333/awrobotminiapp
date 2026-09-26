"""
تتبّع الزوار والأداء (مثل المواقع الكبرى) — بيانات أولية محفوظة عندنا فقط، بلا طرف ثالث إلا إن فعّل الأدمن بكسلات المنصات.

  • الجلسات: بدايتها ونهايتها ومدتها، صفحة الدخول والخروج، عدد الصفحات، الجهاز والنظام والمتصفح ونسخة تلجرام، اللغة، المصدر/الحملة.
  • الأحداث: مشاهدات الصفحات والأزرار والتحويلات (تسجيل، ربط، شراء…) لكل زائر ← رحلة كاملة لكل مستخدم.
  • الأداء: أزمنة تحميل التطبيق (TTFB/FCP/LCP) من أجهزة المستخدمين + زمن استجابة كل مسار API ونسبة أخطائه من الخادم.
  • المؤشرات: المتواجدون الآن، DAU/WAU/MAU، الجدد، الاحتفاظ D1/D7/D30، المصادر، الأجهزة، أكثر الصفحات والأحداث.
  • البكسلات (اختيارية): Meta · TikTok · Google Analytics 4 · X · Snapchat — المعرّفات تُضبط من اللوحة وتُحمَّل في التطبيق.

الخصوصية: لا نحفظ IP ولا بيانات دخول؛ الخصائص مقيّدة الطول والعدد؛ الأحداث تُحذف تلقائيًا بعد مدة الاحتفاظ.
"""
import re
import threading
import time
from collections import deque

EVENTS = "an_events"
SESSIONS = "an_sessions"
VISITORS = "an_visitors"
CONFIG_DOC = ("config", "analytics")
LIVE_SEC = 120
TYPES = ("session_start", "page_view", "event", "perf", "heartbeat", "session_end")
_NAME = re.compile(r"^[a-z0-9_.:-]{1,48}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")

DEFAULT_CONFIG = {
    "enabled": True,
    "retention_days": 90,       # مدة حفظ الأحداث التفصيلية (الجلسات تبقى 400 يوم للاحتفاظ والمقارنات)
    "meta_pixel": "",
    "tiktok_pixel": "",
    "ga4_id": "",
    "x_pixel": "",
    "snap_pixel": "",
}
PIXEL_RE = {
    "meta_pixel": r"\d{8,20}",
    "tiktok_pixel": r"[A-Z0-9]{12,30}",
    "ga4_id": r"G-[A-Z0-9]{4,14}",
    "x_pixel": r"[a-z0-9]{4,12}",
    "snap_pixel": r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
}
_CFG = {"v": None, "at": 0.0}


def get_config(db) -> dict:
    if _CFG["v"] is not None and time.time() - _CFG["at"] < 30:
        return _CFG["v"]
    snap = db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1]).get()
    cfg = {**DEFAULT_CONFIG, **((snap.to_dict() or {}) if snap.exists else {})}
    _CFG.update(v=cfg, at=time.time())
    return cfg


def invalidate():
    _CFG["v"] = None


def clean_config(patch: dict) -> dict:
    out = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "retention_days" in patch:
        out["retention_days"] = max(7, min(730, int(patch["retention_days"])))
    for k, rx in PIXEL_RE.items():
        if k in patch:
            v = str(patch[k] or "").strip()
            if v and not re.fullmatch(rx, v):
                raise ValueError(f"invalid {k}")
            out[k] = v
    return out


def save_config(db, patch: dict) -> dict:
    db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1]).set(clean_config(patch), merge=True)
    invalidate()
    return get_config(db)


def public_pixels(cfg: dict) -> dict:
    """ما يحتاجه التطبيق لتحميل البكسلات (معرّفات عامة بطبيعتها)."""
    return {k: cfg.get(k) or "" for k in PIXEL_RE} if cfg.get("enabled") else {}


# ═════════════════════════ الاستقبال ═════════════════════════
def _s(v, n=80) -> str:
    return re.sub(r"[\x00-\x1f]", "", str(v or ""))[:n]


def _props(p) -> dict:
    out = {}
    for k, v in list((p or {}).items())[:12]:
        k = _s(k, 32)
        if not k:
            continue
        out[k] = v if isinstance(v, (int, float, bool)) else _s(v, 120)
    return out


def _device(d: dict) -> dict:
    d = d or {}
    ua = str(d.get("ua") or "")
    os_ = ("iOS" if re.search(r"iPhone|iPad|iPod", ua) else "Android" if "Android" in ua else "Windows" if "Windows" in ua
           else "macOS" if "Mac OS" in ua else "Linux" if "Linux" in ua else "Other")
    br = ("Telegram" if d.get("tg_platform") else "Edge" if "Edg/" in ua else "Chrome" if "Chrome/" in ua
          else "Safari" if "Safari/" in ua else "Firefox" if "Firefox/" in ua else "Other")
    w = int(d.get("w") or 0)
    return {"platform": _s(d.get("tg_platform") or "web", 20), "os": os_, "browser": br, "tg_version": _s(d.get("tg_version"), 10),
            "screen": f"{w}x{int(d.get('h') or 0)}", "type": "mobile" if w and w < 600 else "tablet" if w and w < 1024 else "desktop",
            "theme": _s(d.get("theme"), 8)}


def _source(s: dict) -> dict:
    s = s or {}
    sp = _s(s.get("start_param"), 64)
    src = _s(s.get("src"), 40)
    campaign = _s(s.get("campaign"), 64)
    if not src and sp:  # روابط البوت: c_<حملة> · ref_<مستخدم> · g_<هدية> · err_ …
        head = sp.split("_", 1)[0]
        src = {"c": "campaign", "ref": "referral", "g": "gift", "gift": "gift"}.get(head, "start_param")
        if head == "c" and not campaign:
            campaign = sp[2:]
    return {"src": src or "direct", "campaign": campaign, "medium": _s(s.get("medium"), 40), "start_param": sp}


def _day(ts: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def ingest(db, uid, body: dict, now: float | None = None) -> int:
    """دفعة أحداث من التطبيق. يرجع عدد الأحداث المحفوظة."""
    cfg = get_config(db)
    if not cfg.get("enabled"):
        return 0
    now = now or time.time()
    sid, vid = str(body.get("sid") or ""), str(body.get("vid") or "")
    if not _ID.match(sid) or (not uid and not _ID.match(vid)):
        return 0
    key = f"u{uid}" if uid else f"v{vid}"
    sref = db.collection(SESSIONS).document(sid)
    snap = sref.get()
    sess = snap.to_dict() if snap.exists else None
    if sess and sess.get("key") not in (key, f"v{vid}"):  # معرّف جلسة لزائر آخر: يُتجاهل
        return 0
    events = [e for e in (body.get("events") or [])[:40] if isinstance(e, dict) and e.get("type") in TYPES]
    if not events:
        return 0
    is_new = not sess
    if is_new:
        sess = {"key": key, "uid": str(uid) if uid else None, "vid": vid, "started": now, "last": now, "day": _day(now),
                "pages": 0, "events": 0, "entry": "", "exit": "", "device": _device(body.get("device")),
                "source": _source(body.get("source")), "lang": _s(body.get("lang"), 5), "ended": False}
    elif uid and not sess.get("uid"):
        sess.update(uid=str(uid), key=key)
    saved = 0
    for e in events:
        typ = e["type"]
        page = _s(e.get("page"), 40)
        if typ == "page_view" and page:
            sess["pages"] = int(sess.get("pages") or 0) + 1
            sess["entry"] = sess.get("entry") or page
            sess["exit"] = page
        if typ == "session_end":
            sess["ended"] = True
        if typ == "heartbeat":
            continue
        name = _s(e.get("name"), 48).lower()
        if typ == "event" and not _NAME.match(name):
            continue
        db.collection(EVENTS).document().set({"key": key, "uid": sess.get("uid"), "sid": sid, "type": typ, "name": name, "page": page,
                                              "props": _props(e.get("props")), "at": now, "day": _day(now)})
        saved += 1
    sess["events"] = int(sess.get("events") or 0) + saved
    sess["last"] = now
    sess["duration"] = round(now - float(sess.get("started") or now))
    sref.set(sess)
    _touch_visitor(db, key, sess, now, is_new)
    return saved


def _touch_visitor(db, key: str, sess: dict, now: float, is_new: bool):
    ref = db.collection(VISITORS).document(key)
    snap = ref.get()
    v = snap.to_dict() if snap.exists else None
    day = _day(now)
    if not v:
        v = {"uid": sess.get("uid"), "first_seen": now, "first_day": day, "first_source": sess.get("source"), "sessions": 0, "days": []}
    if is_new:
        v["sessions"] = int(v.get("sessions") or 0) + 1
    days = list(v.get("days") or [])
    if day not in days:
        days = (days + [day])[-120:]
    v.update(last_seen=now, days=days, last_source=sess.get("source"), device=sess.get("device"), lang=sess.get("lang") or v.get("lang"),
             uid=v.get("uid") or sess.get("uid"))
    ref.set(v)


# ═════════════════════════ أداء الخادم (زمن كل مسار) ═════════════════════════
_API = {}
_API_LOCK = threading.Lock()


def record_api(route: str, ms: float, status: int):
    with _API_LOCK:
        r = _API.setdefault(route, {"lat": deque(maxlen=500), "n": 0, "err": 0, "err5": 0})
        r["lat"].append(ms)
        r["n"] += 1
        r["err"] += status >= 400
        r["err5"] += status >= 500


def _pct(vals: list, p: float):
    if not vals:
        return None
    s = sorted(vals)
    return round(s[min(len(s) - 1, int(len(s) * p))], 1)


def api_stats() -> list:
    with _API_LOCK:
        rows = [{"route": k, "count": v["n"], "p50": _pct(list(v["lat"]), 0.5), "p95": _pct(list(v["lat"]), 0.95),
                 "errors_pct": round(v["err"] / v["n"] * 100, 1) if v["n"] else 0, "server_errors": v["err5"]} for k, v in _API.items()]
    return sorted(rows, key=lambda r: -r["count"])[:60]


class ApiTimer:
    """ASGI middleware خفيف: يقيس زمن كل طلب API ويجمّعه حسب قالب المسار (لا يلمس محتوى الطلب ولا البث المباشر)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or not scope.get("path", "").startswith("/api/"):
            return await self.app(scope, receive, send)
        t0 = time.perf_counter()
        status = {"v": 500}

        async def _send(msg):
            if msg.get("type") == "http.response.start":
                status["v"] = msg.get("status", 500)
                route = getattr(scope.get("route"), "path", None) or "other"
                record_api(f"{scope.get('method')} {route}", (time.perf_counter() - t0) * 1000, status["v"])
            await send(msg)

        return await self.app(scope, receive, _send)


# ═════════════════════════ التقارير ═════════════════════════
def _rows(db, col: str, field: str, since: float) -> list:
    from google.cloud.firestore_v1.base_query import FieldFilter

    return [d.to_dict() or {} for d in db.collection(col).where(filter=FieldFilter(field, ">=", since)).stream()]


def _top(counter: dict, n: int = 12) -> list:
    return [{"k": k, "n": v} for k, v in sorted(counter.items(), key=lambda x: -x[1])[:n]]


def _inc(d: dict, k, by=1):
    k = k or "—"
    d[k] = d.get(k, 0) + by


def summary(db, days: int = 30, now: float | None = None) -> dict:
    now = now or time.time()
    days = max(1, min(180, int(days)))
    since = now - days * 86400
    sess = _rows(db, SESSIONS, "started", since)
    events = _rows(db, EVENTS, "at", since)
    visitors = {d.id: d.to_dict() or {} for d in db.collection(VISITORS).stream()}

    live = [s for s in sess if now - float(s.get("last") or 0) < LIVE_SEC and not s.get("ended")]
    live_pages: dict = {}
    for s in live:
        _inc(live_pages, s.get("exit"))
    daykeys = [_day(now - i * 86400) for i in range(days - 1, -1, -1)]
    per_day = {d: {"visitors": set(), "sessions": 0, "new": 0, "pageviews": 0} for d in daykeys}
    src, camp, plat, os_, br, dtype, lang, entry, exits, theme = ({} for _ in range(10))
    dur, pages, bounces = [], [], 0
    for s in sess:
        d = per_day.get(s.get("day"))
        if d is not None:
            d["visitors"].add(s.get("key"))
            d["sessions"] += 1
        so = s.get("source") or {}
        _inc(src, so.get("src"))
        if so.get("campaign"):
            _inc(camp, so["campaign"])
        dv = s.get("device") or {}
        _inc(plat, dv.get("platform")); _inc(os_, dv.get("os")); _inc(br, dv.get("browser")); _inc(dtype, dv.get("type")); _inc(theme, dv.get("theme"))
        _inc(lang, s.get("lang"))
        _inc(entry, s.get("entry")); _inc(exits, s.get("exit"))
        dur.append(float(s.get("duration") or 0))
        pages.append(int(s.get("pages") or 0))
        bounces += int(s.get("pages") or 0) <= 1 and float(s.get("duration") or 0) < 10
    for v in visitors.values():
        d = per_day.get(v.get("first_day"))
        if d is not None:
            d["new"] += 1
    top_pages, top_events, conv = {}, {}, {}
    perf = {"ttfb": [], "fcp": [], "lcp": [], "load": []}
    for e in events:
        if e.get("type") == "page_view":
            _inc(top_pages, e.get("page"))
            d = per_day.get(e.get("day"))
            if d is not None:
                d["pageviews"] += 1
        elif e.get("type") == "event":
            _inc(top_events, e.get("name"))
            if e.get("name") in ("register", "link_account", "checkout_open", "purchase", "support_open", "share"):
                _inc(conv, e.get("name"))
        elif e.get("type") == "perf":
            for k in perf:
                v = (e.get("props") or {}).get(k)
                if isinstance(v, (int, float)) and 0 <= v < 120000:
                    perf[k].append(float(v))

    def active(n):
        cut = _day(now - (n - 1) * 86400)
        return sum(1 for v in visitors.values() if any(x >= cut for x in (v.get("days") or [])))

    series = [{"day": k, "visitors": len(v["visitors"]), "sessions": v["sessions"], "new": v["new"], "pageviews": v["pageviews"]}
              for k, v in per_day.items()]
    n = len(sess)
    return {
        "now": now, "days": days,
        "live": {"users": len({s.get("key") for s in live}), "pages": _top(live_pages, 8)},
        "active": {"dau": active(1), "wau": active(7), "mau": active(30)},
        "totals": {"visitors": len({s.get("key") for s in sess}), "sessions": n, "pageviews": sum(pages),
                   "new": sum(x["new"] for x in series), "all_time_visitors": len(visitors),
                   "avg_duration_sec": round(sum(dur) / n) if n else 0, "median_duration_sec": _pct(dur, 0.5) or 0,
                   "pages_per_session": round(sum(pages) / n, 2) if n else 0, "bounce_pct": round(bounces / n * 100, 1) if n else 0},
        "series": series,
        "sources": _top(src), "campaigns": _top(camp), "platforms": _top(plat), "os": _top(os_), "browsers": _top(br),
        "device_types": _top(dtype), "langs": _top(lang), "themes": _top(theme),
        "entry_pages": _top(entry), "exit_pages": _top(exits), "top_pages": _top(top_pages, 15), "top_events": _top(top_events, 20),
        "conversions": conv,
        "retention": retention(visitors, now),
        "perf": {k: {"p50": _pct(v, 0.5), "p75": _pct(v, 0.75), "n": len(v)} for k, v in perf.items()},
        "api": api_stats(),
    }


def retention(visitors: dict, now: float, weeks: int = 8) -> list:
    """أفواج أسبوعية حسب أول زيارة: نسبة من عادوا بعد يوم / 7 / 30 يومًا."""
    from datetime import date, timedelta

    out = []
    today = date.fromtimestamp(now)
    for w in range(weeks - 1, -1, -1):
        start = today - timedelta(days=today.weekday() + 7 * w)
        end = start + timedelta(days=7)
        cohort = [v for v in visitors.values() if v.get("first_day") and start.isoformat() <= v["first_day"] < end.isoformat()]
        row = {"week": start.isoformat(), "size": len(cohort)}
        for n in (1, 7, 30):
            eligible = [v for v in cohort if (today - date.fromisoformat(v["first_day"])).days >= n]
            back = [v for v in eligible if any((date.fromisoformat(x) - date.fromisoformat(v["first_day"])).days >= n for x in v.get("days") or [])]
            row[f"d{n}"] = round(len(back) / len(eligible) * 100, 1) if eligible else None
        out.append(row)
    return out


def journey(db, uid, limit: int = 400) -> dict:
    """رحلة مستخدم واحد: كل جلساته وأحداثه بالترتيب."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    key = f"u{uid}"
    snap = db.collection(VISITORS).document(key).get()
    sess = [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(SESSIONS).where(filter=FieldFilter("key", "==", key)).stream()]
    sess.sort(key=lambda s: -(s.get("started") or 0))
    ev = [d.to_dict() or {} for d in db.collection(EVENTS).where(filter=FieldFilter("key", "==", key)).stream()]
    ev.sort(key=lambda e: -(e.get("at") or 0))
    return {"visitor": snap.to_dict() if snap.exists else None, "sessions": sess[:100],
            "events": [{k: e.get(k) for k in ("at", "type", "name", "page", "props", "sid")} for e in ev[:limit]]}


def cleanup(db, now: float | None = None) -> int:
    """حذف الأحداث الأقدم من مدة الاحتفاظ، والجلسات الأقدم من 400 يوم."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = now or time.time()
    cut = now - int(get_config(db).get("retention_days") or 90) * 86400
    n = 0
    for col, cutoff, field in ((EVENTS, cut, "at"), (SESSIONS, now - 400 * 86400, "started")):
        for d in db.collection(col).where(filter=FieldFilter(field, "<", cutoff)).stream():
            db.collection(col).document(d.id).delete()
            n += 1
    return n
