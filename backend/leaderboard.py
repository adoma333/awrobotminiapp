"""
AW Leaderboard — ترتيب أرباح هذا الأسبوع.

  • المستخدمون الحقيقيون: نسبة نمو أسبوعهم الفعلية (report.weekly_growth_pct) واسمهم المستعار فقط.
  • حسابات محاكاة (اختيارية من لوحة الأدمن): منافسون بأسماء وصور وشارات، أرقامهم تتحرك كل دورة
    وتُصفَّر كل أسبوع، ويبرز فيها "نخبة" يتصدرون بالتناوب. تُعلَّم دائمًا simulated=true وتظهر بشارة
    "محاكاة" في الواجهة، فلا تُعرض أبدًا كأنها نتائج تداول حقيقية.
  • ترتيب المستخدم محسوب فعليًا بين الجميع.
"""
import random
import time
from datetime import datetime, timezone

SIM_DOC = ("leaderboard", "sim")
TICK_SEC = 20 * 60

SIM_PROFILES = [
    ("Omar Al-Rashid", "boy", "master"), ("Layla Haddad", "girl", "diamond"), ("Yousef Nasser", "boy", "platinum"),
    ("Sara Mansour", "girl", "platinum"), ("Karim Aziz", "boy", "gold"), ("Noor Khalil", "girl", "gold"),
    ("Tariq Saleh", "boy", "gold"), ("Mira Fares", "girl", "silver"), ("Zaid Hamdan", "boy", "silver"),
    ("Rana Youssef", "girl", "silver"), ("Faisal Qasim", "boy", "bronze"), ("Dana Awad", "girl", "bronze"),
    ("Hamza Jaber", "boy", "diamond"), ("Lina Sabbagh", "girl", "gold"), ("Adam Barakat", "boy", "silver"),
    ("Reem Darwish", "girl", "platinum"), ("Sami Odeh", "boy", "bronze"), ("Yara Nassar", "girl", "gold"),
    ("Khaled Mourad", "boy", "platinum"), ("Huda Salem", "girl", "silver"),
]


def week_key(ts: float) -> str:
    iso = datetime.fromtimestamp(ts, timezone.utc).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _fresh(count: int, rng) -> list:
    picks = SIM_PROFILES[: max(0, min(count, len(SIM_PROFILES)))]
    return [{"id": f"sim{i}", "name": n, "avatar": a, "tier": tr, "pct": round(rng.uniform(0.2, 2.5), 2),
             "drift": round(rng.uniform(0.05, 0.35), 3), "delta": 0.0} for i, (n, a, tr) in enumerate(picks)]


def tick(db, count: int, now: float | None = None, rng=random) -> dict:
    """يحرّك أرقام المحاكاة (سباق). يُصفّر مع بداية أسبوع جديد، ويصنع صعودًا مفاجئًا لنخبة متغيّرة."""
    now = time.time() if now is None else now
    ref = db.collection(SIM_DOC[0]).document(SIM_DOC[1])
    snap = ref.get()
    doc = (snap.to_dict() or {}) if snap.exists else {}
    wk = week_key(now)
    bots = doc.get("bots") or []
    if doc.get("week") != wk or len(bots) != min(count, len(SIM_PROFILES)):
        bots = _fresh(count, rng)
    else:
        surge = set(rng.sample(range(len(bots)), k=min(2, len(bots)))) if bots and rng.random() < 0.35 else set()
        for i, b in enumerate(bots):
            step = rng.gauss(b.get("drift", 0.15), 0.45) + (rng.uniform(1.0, 3.2) if i in surge else 0)
            new = max(-6.0, min(48.0, b["pct"] + step))
            b["delta"] = round(new - b["pct"], 2)
            b["pct"] = round(new, 2)
    doc = {"week": wk, "bots": bots, "updated_at": now}
    ref.set(doc)
    return doc


def build(db, uid, sim_enabled: bool, sim_count: int, now: float | None = None, limit: int = 20) -> dict:
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    rows = []
    for d in db.collection("users").where(filter=FieldFilter("status", "==", "approved")).stream():
        u = d.to_dict() or {}
        pct = (u.get("report") or {}).get("weekly_growth_pct")
        if pct is None:
            continue
        name = (u.get("nickname") or "Trader").strip().split(" ")[0][:14]
        rows.append({"id": d.id, "name": name, "avatar": u.get("avatar") or "boy", "pct": round(float(pct), 2),
                     "simulated": False, "you": str(d.id) == str(uid), "delta": 0.0, "tier": None})
    updated = now
    if sim_enabled and sim_count > 0:
        snap = db.collection(SIM_DOC[0]).document(SIM_DOC[1]).get()
        doc = (snap.to_dict() or {}) if snap.exists else {}
        if doc.get("week") != week_key(now) or now - float(doc.get("updated_at") or 0) > TICK_SEC:
            doc = tick(db, sim_count, now)
        updated = doc.get("updated_at") or now
        rows += [{**{k: b[k] for k in ("id", "name", "avatar", "pct", "delta", "tier")}, "simulated": True, "you": False}
                 for b in doc.get("bots") or []]
    rows.sort(key=lambda r: -r["pct"])
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    me = next((r for r in rows if r["you"]), None)
    return {"week": week_key(now), "updated_at": updated, "total": len(rows), "me": me,
            "rows": rows[:limit], "has_simulated": any(r["simulated"] for r in rows)}
