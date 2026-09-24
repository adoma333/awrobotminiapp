"""
AW Servers — سجل خوادم MT5 للاقتراح أثناء الكتابة.

لا توجد واجهة برمجية عامة تُرجع قائمة خوادم الوسطاء (بحث الخوادم داخل ترمنال MT5 يعتمد على خدمة داخلية
لـ MetaQuotes غير متاحة عبر مكتبة MetaTrader5/mt5linux)، لذلك يُبنى السجل من مصدرين موثوقين:
  1) كل ربط ناجح يسجّل اسم الخادم كما قبله MT5 فعلًا (verified=True) — الاسم الصحيح 100%.
  2) قوائم يستوردها الأدمن من لوحة التحكم (ملف/نص)، أو من خوادم الحسابات المربوطة حاليًا.
كل خادم يحمل نوعه: demo أو real حتى لا يحدث التباس.
"""
import difflib
import re
import time

COLLECTION = "mt5_servers"
_CACHE = {"rows": None, "at": 0.0}
CACHE_SEC = 300


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def server_type(name: str) -> str:
    s = (name or "").lower()
    if "demo" in s or "trial" in s or "contest" in s:
        return "demo"
    if "real" in s or "live" in s or "ecn" in s or "pro" in s:
        return "real"
    return "unknown"


def _clean_name(name) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()[:64]


def upsert(db, name: str, verified: bool = False, stype: str | None = None, source: str = "admin"):
    name = _clean_name(name)
    key = norm(name)
    if len(key) < 3:
        return None
    ref = db.collection(COLLECTION).document(key)
    snap = ref.get()
    cur = (snap.to_dict() or {}) if snap.exists else {}
    data = {
        "name": name if (verified or not cur.get("verified")) else cur.get("name", name),
        "type": stype if stype in ("demo", "real") else (cur.get("type") or server_type(name)),
        "verified": bool(cur.get("verified")) or verified,
        "source": cur.get("source") or source,
        "updated_at": time.time(),
    }
    if verified:
        data["links"] = int(cur.get("links") or 0) + 1
    ref.set(data, merge=True)
    _CACHE["rows"] = None
    return key


def record_success(db, name: str):
    """اسم الخادم كما قبله MT5 في ربط ناجح."""
    return upsert(db, name, verified=True, source="link")


def parse_import(text: str) -> list:
    """سطر لكل خادم: "Name" أو "Name,demo|real". يقبل CSV أو قائمة JSON بالحقول name/type."""
    import json

    text = (text or "").strip()
    rows = []
    if text.startswith("["):
        for item in json.loads(text):
            if isinstance(item, str):
                rows.append((item, None))
            elif isinstance(item, dict):
                rows.append((item.get("name") or item.get("server"), item.get("type")))
    else:
        for line in text.splitlines():
            parts = [p.strip() for p in re.split(r"[,;\t]", line) if p.strip()]
            if not parts or parts[0].lower() in ("name", "server"):
                continue
            t = parts[1].lower() if len(parts) > 1 else None
            rows.append((parts[0], "real" if t in ("live", "real") else "demo" if t == "demo" else None))
    return [(n, t) for n, t in rows if n]


def all_rows(db) -> list:
    if _CACHE["rows"] is not None and time.time() - _CACHE["at"] < CACHE_SEC:
        return _CACHE["rows"]
    rows = []
    for d in db.collection(COLLECTION).stream():
        x = d.to_dict() or {}
        rows.append({"id": d.id, "name": x.get("name"), "type": x.get("type") or "unknown",
                     "verified": bool(x.get("verified")), "links": int(x.get("links") or 0)})
    _CACHE.update(rows=rows, at=time.time())
    return rows


def search(db, q: str, limit: int = 8) -> list:
    """مطابقة متسامحة: تتجاهل الحالة والمسافات والشرطات، وتلتقط الأخطاء الإملائية."""
    key = norm(q)
    if len(key) < 2:
        return []
    scored = []
    for r in all_rows(db):
        n = r["id"]
        if n == key:
            score = 100
        elif n.startswith(key):
            score = 85
        elif key in n:
            score = 70
        else:
            ratio = difflib.SequenceMatcher(None, key, n).ratio()
            if ratio < 0.62:
                continue
            score = ratio * 60
        score += (8 if r["verified"] else 0) + min(r["links"], 20) * 0.2
        scored.append((score, r))
    scored.sort(key=lambda x: -x[0])
    return [{**r, "exact": r["id"] == key} for _, r in scored[:limit]]
