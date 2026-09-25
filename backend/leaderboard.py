"""
AW Leaderboard — ترتيب أرباح هذا الأسبوع بالدولار.

  • المستخدمون الحقيقيون: ربح أسبوعهم الفعلي (report.weekly_pnl) محوّلًا للدولار، واسمهم المستعار فقط.
  • الأسماء المُدارة من الأدمن (profiles): تُثبَّت بياناتها نهائيًا لحظة التأكيد (الاسم، الصورة، القيمة الأساسية
    base_usd). القيمة الأساسية الغائبة تُولَّد مرة واحدة بشكل حتمي (بذرة من الاسم) — فلا تتغير القائمة
    عشوائيًا مع كل تحديث أو رفع للملف نفسه. لا تتغير البيانات إلا بتأكيد جديد من الأدمن.
  • محرك المحاكاة الديناميكية (اختياري، dynamic): يحرّك القيم صعودًا وهبوطًا حول القيمة الأساسية ضمن
    نطاق volatility_pct فقط، كل interval_sec ثانية، فتتبادل الأسماء الترتيب. يُعاد كل أسبوع للقيم الأساسية.
  • وضع المجموعة المغلقة (mode=group): تُعرض مجموعة ثابتة العدد (group_size) تضم الأسماء المُدارة +
    المستخدم الحقيقي نفسه، مرتبة معًا بنفس المنطق. وضع open: كل المستخدمين الحقيقيين + الأسماء المُدارة.
  • كل صف غير حقيقي يحمل simulated=true، والواجهة تعرض سطرًا توضيحيًا واحدًا أسفل القائمة.
"""
import hashlib
import random
import time
from datetime import datetime, timezone

CONFIG_DOC = ("config", "leaderboard")
SIM_DOC = ("leaderboard", "sim")
TICK_SEC = 60  # نبضة الجدولة؛ الفاصل الفعلي interval_sec من الإعدادات
CENT_CURRENCIES = {"USC", "EUC", "USX"}

DEFAULT_PROFILES = [
    ("Omar Al-Rashid", "boy", "master"), ("Layla Haddad", "girl", "diamond"), ("Yousef Nasser", "boy", "platinum"),
    ("Sara Mansour", "girl", "platinum"), ("Karim Aziz", "boy", "gold"), ("Noor Khalil", "girl", "gold"),
    ("Tariq Saleh", "boy", "gold"), ("Mira Fares", "girl", "silver"), ("Zaid Hamdan", "boy", "silver"),
    ("Rana Youssef", "girl", "silver"), ("Faisal Qasim", "boy", "bronze"), ("Dana Awad", "girl", "bronze"),
    ("Hamza Jaber", "boy", "diamond"), ("Lina Sabbagh", "girl", "gold"), ("Adam Barakat", "boy", "silver"),
    ("Reem Darwish", "girl", "platinum"), ("Sami Odeh", "boy", "bronze"), ("Yara Nassar", "girl", "gold"),
    ("Khaled Mourad", "boy", "platinum"), ("Huda Salem", "girl", "silver"),
]
TIERS = ("bronze", "silver", "gold", "platinum", "diamond", "master")


def default_config() -> dict:
    return {
        "enabled": True,
        "mode": "open",          # open: الجميع · group: مجموعة مغلقة تضم المستخدم نفسه
        "group_size": 15,        # العدد الظاهر في وضع المجموعة (يشمل المستخدم الحقيقي)
        "count": 12,             # عدد الأسماء المُدارة المعروضة في وضع open
        "dynamic": True,         # محرك المحاكاة: حركة صعود/هبوط تلقائية
        "interval_sec": 1200,    # فاصل كل حركة
        "volatility_pct": 12,    # أقصى ابتعاد عن القيمة الأساسية ±%
        # نطاقات توليد القيمة الأساسية حتميًا لمن لا يملك base_usd
        "elite_count": 3,
        "elite_min": 250_000,
        "elite_max": 900_000,
        "base_min": 3_000,
        "base_max": 85_000,
        "profiles": [{"name": n, "avatar": a, "tier": t} for n, a, t in DEFAULT_PROFILES],
        "confirmed_at": None,
    }


def get_config(db) -> dict:
    snap = db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1]).get()
    saved = (snap.to_dict() or {}) if snap.exists else {}
    cfg = default_config()
    cfg.update({k: v for k, v in saved.items() if k in cfg})
    return cfg


def _photo_ok(v: str) -> bool:
    return v.startswith(("https://", "http://")) or v.startswith("/api/media/avatars/")


def clean_config(patch: dict) -> dict:
    out = {}
    for k in ("enabled", "dynamic"):
        if k in patch:
            out[k] = bool(patch[k])
    if "mode" in patch:
        if patch["mode"] not in ("open", "group"):
            raise ValueError("mode must be open|group")
        out["mode"] = patch["mode"]
    for k, lo, hi in (("count", 0, 50), ("elite_count", 0, 10), ("group_size", 3, 50), ("interval_sec", 60, 86400),
                      ("volatility_pct", 0, 60)):
        if k in patch:
            out[k] = max(lo, min(hi, int(patch[k])))
    for k in ("elite_min", "elite_max", "base_min", "base_max"):
        if k in patch:
            v = float(patch[k])
            if v < 0:
                raise ValueError(f"{k} must be >= 0")
            out[k] = round(v, 2)
    merged = {**default_config(), **out}
    if merged["elite_min"] > merged["elite_max"] or merged["base_min"] > merged["base_max"]:
        raise ValueError("min must be <= max")
    if "profiles" in patch:
        rows = []
        for p in patch["profiles"] or []:
            name = str(p.get("name") or "").strip()[:32]
            if not name:
                continue
            photo = str(p.get("photo") or "").strip()
            base = p.get("base_usd")
            base = round(float(base), 2) if base not in (None, "") else None
            if base is not None and base < 0:
                raise ValueError("base_usd must be >= 0")
            rows.append({"name": name, "avatar": "girl" if p.get("avatar") == "girl" else "boy",
                         "tier": p.get("tier") if p.get("tier") in TIERS else "gold",
                         "photo": photo[:300] if _photo_ok(photo) else None, "base_usd": base})
        out["profiles"] = rows[:50]
        out["confirmed_at"] = time.time()
    return out


def week_key(ts: float) -> str:
    iso = datetime.fromtimestamp(ts, timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _seed(name: str) -> int:
    return int(hashlib.sha256(name.encode()).hexdigest()[:12], 16)


def bases(cfg: dict) -> list:
    """القيمة الأساسية لكل اسم: المُدخلة يدويًا، أو مولَّدة حتميًا من الاسم (ثابتة دائمًا)."""
    out = []
    for i, p in enumerate(cfg["profiles"]):
        if p.get("base_usd") is not None:
            out.append(float(p["base_usd"]))
            continue
        lo, hi = (cfg["elite_min"], cfg["elite_max"]) if i < cfg["elite_count"] else (cfg["base_min"], cfg["base_max"])
        out.append(round(random.Random(_seed(p["name"])).uniform(lo, hi), 2))
    return out


def _bot_id(p: dict, i: int) -> str:
    return f"sim{i}-{_seed(p['name']) % 100000:05d}"


def _fingerprint(cfg: dict) -> str:
    """يتغير فقط عند تأكيد بيانات جديدة (لا عند تغيير سرعة الحركة أو نطاقها)."""
    return "|".join(f'{p["name"]}:{p.get("photo") or ""}:{p.get("avatar")}:{p.get("tier")}:{b}'
                    for p, b in zip(cfg["profiles"], bases(cfg)))


def _fresh(cfg: dict) -> list:
    return [{"id": _bot_id(p, i), "name": p["name"], "avatar": p["avatar"], "tier": p.get("tier"), "photo": p.get("photo"),
             "base": b, "usd": b, "delta": 0.0} for i, (p, b) in enumerate(zip(cfg["profiles"], bases(cfg)))]


def tick(db, cfg: dict | None = None, now: float | None = None, rng=random, force: bool = False) -> dict:
    """حركة واحدة للمحاكاة (إن كانت مفعّلة وحان وقتها). البيانات الأساسية لا تتغير أبدًا هنا."""
    cfg = cfg or get_config(db)
    now = time.time() if now is None else now
    ref = db.collection(SIM_DOC[0]).document(SIM_DOC[1])
    snap = ref.get()
    doc = (snap.to_dict() or {}) if snap.exists else {}
    wk, fp = week_key(now), _fingerprint(cfg)
    bots = doc.get("bots") or []
    if doc.get("week") != wk or doc.get("fp") != fp or len(bots) != len(cfg["profiles"]):
        bots = _fresh(cfg)  # تأكيد جديد أو أسبوع جديد: العودة للقيم الأساسية (حتمي)
    elif not force and now - float(doc.get("updated_at") or 0) < cfg["interval_sec"]:
        return doc
    elif cfg["dynamic"] and cfg["volatility_pct"] > 0:
        band = cfg["volatility_pct"] / 100
        for b in bots:
            base = float(b.get("base") or b["usd"])
            lo, hi = max(0.0, base * (1 - band)), base * (1 + band)
            step = rng.gauss(0, 0.35) * band * base + 0.25 * (base - b["usd"])  # تذبذب + عودة نحو الأساس
            new = round(max(lo, min(hi, b["usd"] + step)), 2)
            b["delta"] = round(new - b["usd"], 2)
            b["usd"] = new
    doc = {"week": wk, "fp": fp, "bots": bots, "updated_at": now}
    ref.set(doc)
    return doc


def _usd(report: dict, currency: str | None):
    pnl = (report or {}).get("weekly_pnl")
    if pnl is None:
        return None
    v = float(pnl)
    return round(v / 100 if str(currency or "").upper() in CENT_CURRENCIES else v, 2)


def _real_row(uid, u: dict, me: bool) -> dict | None:
    usd = _usd(u.get("report"), (u.get("live") or {}).get("currency"))
    if usd is None and not me:
        return None
    name = (u.get("nickname") or "Trader").strip().split(" ")[0][:14]
    return {"id": str(uid), "name": name, "avatar": u.get("avatar") or "boy", "photo": u.get("photo_url"), "usd": usd or 0.0,
            "simulated": False, "you": me, "delta": 0.0, "tier": None}


def build(db, uid, now: float | None = None, limit: int = 20) -> dict:
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    cfg = get_config(db)
    group = cfg["mode"] == "group"
    rows = []
    if group:
        snap = db.collection("users").document(str(uid)).get()
        if snap.exists and (snap.to_dict() or {}).get("status") == "approved":
            rows.append(_real_row(uid, snap.to_dict() or {}, True))
    else:
        for d in db.collection("users").where(filter=FieldFilter("status", "==", "approved")).stream():
            u = d.to_dict() or {}
            if _usd(u.get("report"), (u.get("live") or {}).get("currency")) is not None:
                rows.append(_real_row(d.id, u, str(d.id) == str(uid)))
    updated = now
    if cfg["enabled"] and cfg["profiles"]:
        doc = tick(db, cfg, now)
        updated = doc.get("updated_at") or now
        n = max(0, cfg["group_size"] - len(rows)) if group else cfg["count"]
        rows += [{"id": b["id"], "name": b["name"], "avatar": b["avatar"], "photo": b.get("photo"), "tier": b.get("tier"),
                  "usd": b["usd"], "delta": b["delta"], "simulated": True, "you": False} for b in (doc.get("bots") or [])[:n]]
    rows.sort(key=lambda r: -r["usd"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    me = next((r for r in rows if r["you"]), None)
    shown = rows if group else rows[:limit]
    return {"week": week_key(now), "updated_at": updated, "total": len(rows), "me": me, "mode": cfg["mode"],
            "rows": shown, "has_simulated": any(r["simulated"] for r in rows)}
