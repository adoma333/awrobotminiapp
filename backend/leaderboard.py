"""
AW Leaderboard — ترتيب أرباح هذا الأسبوع بالدولار.

  • المستخدمون الحقيقيون: ربح أسبوعهم الفعلي (report.weekly_pnl) محوّلًا للدولار، واسمهم المستعار فقط.
  • منافسون محاكاة (قابلة للتحكم الكامل من لوحة الأدمن: التشغيل، العدد، النخبة، نطاقات الأرباح، الأسماء والصور):
    أرقامهم تتحرك كل دورة وتُعاد كل أسبوع وتتبادل النخبة الصدارة. كل صف منهم يحمل simulated=true
    وتُظهره الواجهة بعلامة صغيرة مع سطر توضيحي، فلا يُعرض كنتيجة تداول حقيقية.
  • ترتيب المستخدم محسوب فعليًا بين الجميع.
"""
import random
import time
from datetime import datetime, timezone

CONFIG_DOC = ("config", "leaderboard")
SIM_DOC = ("leaderboard", "sim")
TICK_SEC = 20 * 60
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
        "count": 12,           # عدد المنافسين المحاكاة المعروضين
        "elite_count": 3,      # النخبة المتصدرة
        "elite_min": 250_000,  # نطاق ربح النخبة الأسبوعي بالدولار
        "elite_max": 900_000,
        "base_min": 3_000,     # نطاق ربح البقية
        "base_max": 85_000,
        "profiles": [{"name": n, "avatar": a, "tier": t} for n, a, t in DEFAULT_PROFILES],
    }


def get_config(db) -> dict:
    snap = db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1]).get()
    saved = (snap.to_dict() or {}) if snap.exists else {}
    cfg = default_config()
    cfg.update({k: v for k, v in saved.items() if k in cfg})
    return cfg


def clean_config(patch: dict) -> dict:
    out = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    for k, lo, hi in (("count", 0, 50), ("elite_count", 0, 10)):
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
            rows.append({"name": name, "avatar": "girl" if p.get("avatar") == "girl" else "boy",
                         "tier": p.get("tier") if p.get("tier") in TIERS else "gold",
                         "photo": photo[:300] if photo.startswith(("https://", "http://")) else None})
        out["profiles"] = rows[:50]
    return out


def week_key(ts: float) -> str:
    iso = datetime.fromtimestamp(ts, timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _fingerprint(cfg: dict) -> str:
    keys = ("count", "elite_count", "elite_min", "elite_max", "base_min", "base_max")
    return "|".join(str(cfg[k]) for k in keys) + "|" + "|".join(f'{p["name"]}:{p.get("photo") or ""}:{p.get("avatar")}:{p.get("tier")}' for p in cfg["profiles"])


def _fresh(cfg: dict, rng) -> list:
    profiles = cfg["profiles"][: cfg["count"]]
    elite = set(rng.sample(range(len(profiles)), k=min(cfg["elite_count"], len(profiles)))) if profiles else set()
    bots = []
    for i, p in enumerate(profiles):
        lo, hi = (cfg["elite_min"], cfg["elite_max"]) if i in elite else (cfg["base_min"], cfg["base_max"])
        bots.append({"id": f"sim{i}", **p, "elite": i in elite, "lo": lo, "hi": hi,
                     "usd": round(rng.uniform(lo, lo + (hi - lo) * 0.45), 2), "delta": 0.0})
    return bots


def tick(db, cfg: dict | None = None, now: float | None = None, rng=random) -> dict:
    """يحرّك الأرباح (سباق) ضمن نطاق كل منافس بميل صاعد، ويُعيد التوزيع مع كل أسبوع أو تغيير في الإعدادات."""
    cfg = cfg or get_config(db)
    now = time.time() if now is None else now
    ref = db.collection(SIM_DOC[0]).document(SIM_DOC[1])
    snap = ref.get()
    doc = (snap.to_dict() or {}) if snap.exists else {}
    wk, fp = week_key(now), _fingerprint(cfg)
    bots = doc.get("bots") or []
    if doc.get("week") != wk or doc.get("fp") != fp:
        bots = _fresh(cfg, rng)
    else:
        for b in bots:
            span = b["hi"] - b["lo"]
            step = rng.gauss(0.018, 0.035) * span  # ميل صاعد خلال الأسبوع مع تذبذب
            new = max(b["lo"], min(b["hi"], b["usd"] + step))
            b["delta"] = round(new - b["usd"], 2)
            b["usd"] = round(new, 2)
    doc = {"week": wk, "fp": fp, "bots": bots, "updated_at": now}
    ref.set(doc)
    return doc


def _usd(report: dict, currency: str | None):
    pnl = (report or {}).get("weekly_pnl")
    if pnl is None:
        return None
    v = float(pnl)
    return round(v / 100 if str(currency or "").upper() in CENT_CURRENCIES else v, 2)


def build(db, uid, now: float | None = None, limit: int = 20) -> dict:
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    cfg = get_config(db)
    rows = []
    for d in db.collection("users").where(filter=FieldFilter("status", "==", "approved")).stream():
        u = d.to_dict() or {}
        usd = _usd(u.get("report"), (u.get("live") or {}).get("currency"))
        if usd is None:
            continue
        name = (u.get("nickname") or "Trader").strip().split(" ")[0][:14]
        rows.append({"id": d.id, "name": name, "avatar": u.get("avatar") or "boy", "photo": u.get("photo_url"), "usd": usd,
                     "simulated": False, "you": str(d.id) == str(uid), "delta": 0.0, "tier": None})
    updated = now
    if cfg["enabled"] and cfg["count"] > 0 and cfg["profiles"]:
        snap = db.collection(SIM_DOC[0]).document(SIM_DOC[1]).get()
        doc = (snap.to_dict() or {}) if snap.exists else {}
        if (doc.get("week") != week_key(now) or doc.get("fp") != _fingerprint(cfg)
                or now - float(doc.get("updated_at") or 0) > TICK_SEC):
            doc = tick(db, cfg, now)
        updated = doc.get("updated_at") or now
        rows += [{"id": b["id"], "name": b["name"], "avatar": b["avatar"], "photo": b.get("photo"), "tier": b["tier"], "usd": b["usd"],
                  "delta": b["delta"], "simulated": True, "you": False} for b in doc.get("bots") or []]
    rows.sort(key=lambda r: -r["usd"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    me = next((r for r in rows if r["you"]), None)
    return {"week": week_key(now), "updated_at": updated, "total": len(rows), "me": me,
            "rows": rows[:limit], "has_simulated": any(r["simulated"] for r in rows)}
