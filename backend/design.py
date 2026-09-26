"""
استوديو التصميم — تخصيص كامل لواجهة الـ Mini App من لوحة التحكم (بلا برمجة).

  • رموز التصميم العامة: الألوان (ليلي/نهاري)، الخطوط، حجم الواجهة، الكثافة، شكل الأزرار، الزوايا، التوهج، الحركة،
    التكيّف التلقائي مع كل الأجهزة، أقصى عرض.
  • الصفحات: ترتيب العناصر وإظهارها (سحب وإفلات)، خيارات كل عنصر، الأيقونات، الأحجام.
  • النصوص: استبدال أي نص في التطبيق بالعربية والإنجليزية.
  • صفحة خارج تلجرام (رمز QR + رابط) و SEO.
  • مسودة ← نشر، سجل تحديثات مع استرجاع أي نسخة، قوالب محفوظة لكل صفحة ومجموعات قوالب، واقتراحات الذكاء الاصطناعي.

كل قيمة يتحقق منها clean() قبل الحفظ: ألوان #RRGGBB، قوائم ثابتة، نطاقات رقمية، معرّفات عناصر معروفة فقط، وأيقونات من
القائمة المعتمدة — لا CSS أو HTML حر (لا حقن).
"""
import copy
import json
import os
import re
import time

CONFIG_DOC = ("config", "design")
HISTORY = "design_history"
THEMES = "design_themes"

ICONS = ("home", "analytics", "referral", "rewards", "plans", "settings", "star", "share", "copy", "download", "bolt", "headset",
         "bell", "chart", "shield", "cloud", "trophy", "gift", "wallet", "globe", "check", "alert", "refresh", "image", "send",
         "sun", "moon", "eye", "lock", "card", "user", "megaphone", "rocket", "diamond", "crown", "fire", "heart", "chat",
         "calendar", "clock", "target", "coin", "percent", "sparkle", "info", "question", "book", "calc", "history", "grid",
         "layers", "palette", "phone", "qr", "telegram", "key", "lifebuoy", "flag", "list", "trend")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
TEXT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}$")

TOKEN_COLORS = ("accent", "accent2", "bg", "surface", "text", "muted", "ok", "danger")
ENUMS = {
    "font_body": ("plex", "system", "chakra"),
    "font_display": ("chakra", "plex", "system"),
    "density": ("compact", "comfortable", "spacious"),
    "button_shape": ("angled", "rounded", "pill", "square"),
    "default_theme": ("dark", "light", "auto"),
    "card_style": ("glass", "solid", "outline", "gradient"),
}
RANGES = {"radius": (0, 32), "ui_scale": (80, 130), "max_width": (360, 760), "glow": (0, 100)}

HOME_BLOCKS = ("who", "feedback", "hero", "announce", "subscription", "scratch", "quick", "growth")
START_BLOCKS = ("logo", "stepper", "title", "options", "perks")
QUICK_ITEMS = ("support", "notifications", "billing", "faq", "calc", "plans", "rewards", "referral", "analytics", "settings")
GROWTH_CELLS = ("today", "week", "month", "all", "winrate", "trades", "profit_factor", "drawdown")
NAV_ITEMS = ("main", "analytics", "referral", "rewards", "plans", "settings")
PAGES = ("global", "start", "home", "nav", "topbar", "landing")


def _blocks(ids, hidden=()):
    return [{"id": i, "visible": i not in hidden} for i in ids]


DEFAULT = {
    "tokens": {
        "dark": {"accent": "#ff8a00", "accent2": "#ff5a00", "bg": "#000000", "surface": "#100e0c", "text": "#f5efe8",
                 "muted": "#8c8378", "ok": "#3ddc97", "danger": "#ff6b5e"},
        "light": {"accent": "#e87800", "accent2": "#f05200", "bg": "#f6f2ec", "surface": "#ffffff", "text": "#1b1612",
                  "muted": "#6e655b", "ok": "#12a26b", "danger": "#d9443a"},
        "font_body": "plex", "font_display": "chakra", "density": "comfortable", "button_shape": "angled",
        "card_style": "glass", "default_theme": "dark", "radius": 14, "ui_scale": 100, "max_width": 440, "glow": 60,
        "fluid": True, "animations": True,
    },
    "pages": {
        "start": {"blocks": _blocks(START_BLOCKS), "logo_size": 54,
                  "perks": [{"icon": "bolt", "text_ar": "", "text_en": ""}, {"icon": "chart", "text_ar": "", "text_en": ""},
                            {"icon": "lock", "text_ar": "", "text_en": ""}]},
        "home": {"blocks": _blocks(HOME_BLOCKS),
                 "hero": {"sparkline": True, "stats": True, "balance_size": 100, "today": True, "eye": True},
                 "quick": {"items": [{"id": "support", "icon": "headset"}, {"id": "notifications", "icon": "bell"},
                                     {"id": "billing", "icon": "history"}, {"id": "faq", "icon": "question"}], "columns": 4},
                 "growth": {"cells": ["week", "month", "winrate", "drawdown"]}},
        "nav": {"items": [{"id": i, "icon": ic, "visible": True} for i, ic in
                          (("main", "home"), ("analytics", "analytics"), ("referral", "referral"), ("rewards", "rewards"),
                           ("plans", "plans"), ("settings", "settings"))],
                "labels": True},
        "topbar": {"theme_toggle": True, "support": True, "bell": True, "logo_size": 26},
        "landing": {"title_ar": "افتح AW ROBOT في تلجرام", "title_en": "Open AW ROBOT in Telegram",
                    "sub_ar": "التطبيق يعمل داخل تلجرام فقط. امسح الرمز بهاتفك أو اضغط الزر.",
                    "sub_en": "The app runs inside Telegram. Scan the code with your phone or tap the button.",
                    "button_ar": "فتح في تلجرام", "button_en": "Open in Telegram", "show_qr": True, "show_features": True},
    },
    "texts": {"ar": {}, "en": {}},
    "seo": {"title": "AW ROBOT — التداول الآلي داخل تلجرام", "description": "نظام تداول آلي يربط حساب MetaTrader 5 ويعرض أداءه لحظيًا داخل تلجرام.",
            "keywords": "AW Robot, تداول آلي, MT5, Telegram", "og_image": "", "site_name": "AW ROBOT", "index": True, "theme_color": "#000000"},
}


def default() -> dict:
    return copy.deepcopy(DEFAULT)


class DesignError(ValueError):
    pass


def _deep_merge(base: dict, patch: dict) -> dict:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _s(v, n=240) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f<>]", "", str(v if v is not None else ""))[:n]


def _num(v, lo, hi, name):
    try:
        x = int(float(v))
    except (TypeError, ValueError):
        raise DesignError(f"{name} must be a number")
    return max(lo, min(hi, x))


def _icon(v, name):
    if v not in ICONS:
        raise DesignError(f"{name}: unknown icon")
    return v


def _block_list(rows, allowed, name):
    out, seen = [], set()
    for r in rows or []:
        i = r.get("id")
        if i not in allowed or i in seen:
            raise DesignError(f"{name}: unknown or duplicate block {i}")
        seen.add(i)
        out.append({"id": i, "visible": bool(r.get("visible", True))})
    out += [{"id": i, "visible": False} for i in allowed if i not in seen]  # عنصر جديد في الإصدارات القادمة: مخفي حتى يُفعَّل
    return out


def clean(d: dict) -> dict:
    """يتحقق من تصميم كامل (بعد دمجه مع الافتراضي) ويعيده نظيفًا. يرفع DesignError برسالة واضحة."""
    d = _deep_merge(default(), d or {})
    t = d["tokens"]
    tokens = {}
    for mode in ("dark", "light"):
        tokens[mode] = {}
        for k in TOKEN_COLORS:
            v = str(t[mode].get(k) or DEFAULT["tokens"][mode][k])
            if not HEX.match(v):
                raise DesignError(f"tokens.{mode}.{k} must be #RRGGBB")
            tokens[mode][k] = v.lower()
    for k, allowed in ENUMS.items():
        if t.get(k) not in allowed:
            raise DesignError(f"tokens.{k} invalid")
        tokens[k] = t[k]
    for k, (lo, hi) in RANGES.items():
        tokens[k] = _num(t.get(k), lo, hi, f"tokens.{k}")
    tokens["fluid"] = bool(t.get("fluid"))
    tokens["animations"] = bool(t.get("animations"))

    p = d["pages"]
    st = p["start"]
    start = {"blocks": _block_list(st.get("blocks"), START_BLOCKS, "start"), "logo_size": _num(st.get("logo_size"), 32, 96, "start.logo_size"),
             "perks": [{"icon": _icon(x.get("icon"), "start.perks"), "text_ar": _s(x.get("text_ar"), 80), "text_en": _s(x.get("text_en"), 80)}
                       for x in (st.get("perks") or [])[:6]]}
    h = p["home"]
    hero = h.get("hero") or {}
    quick = h.get("quick") or {}
    q_items, seen = [], set()
    for x in (quick.get("items") or [])[:8]:
        if x.get("id") not in QUICK_ITEMS or x["id"] in seen:
            raise DesignError("home.quick: unknown item")
        seen.add(x["id"])
        q_items.append({"id": x["id"], "icon": _icon(x.get("icon"), "home.quick.icon"), "label_ar": _s(x.get("label_ar"), 24), "label_en": _s(x.get("label_en"), 24)})
    cells = [c for c in ((h.get("growth") or {}).get("cells") or []) if c in GROWTH_CELLS][:6]
    if len(cells) % 2:
        cells = cells[:-1]
    home = {"blocks": _block_list(h.get("blocks"), HOME_BLOCKS, "home"),
            "hero": {"sparkline": bool(hero.get("sparkline", True)), "stats": bool(hero.get("stats", True)), "today": bool(hero.get("today", True)),
                     "eye": bool(hero.get("eye", True)), "balance_size": _num(hero.get("balance_size", 100), 70, 140, "home.hero.balance_size")},
            "quick": {"items": q_items, "columns": _num(quick.get("columns", 4), 2, 5, "home.quick.columns")},
            "growth": {"cells": cells or ["week", "month"]}}
    n = p["nav"]
    nav_items, seen = [], set()
    for x in n.get("items") or []:
        if x.get("id") not in NAV_ITEMS or x["id"] in seen:
            raise DesignError("nav: unknown item")
        seen.add(x["id"])
        nav_items.append({"id": x["id"], "icon": _icon(x.get("icon"), "nav.icon"), "visible": bool(x.get("visible", True)) or x["id"] == "main",
                          "label_ar": _s(x.get("label_ar"), 20), "label_en": _s(x.get("label_en"), 20)})
    if not any(x["id"] == "main" for x in nav_items):
        raise DesignError("nav: home item is required")
    nav = {"items": nav_items, "labels": bool(n.get("labels", True))}
    tb = p["topbar"]
    topbar = {k: bool(tb.get(k, True)) for k in ("theme_toggle", "support", "bell")}
    topbar["logo_size"] = _num(tb.get("logo_size", 26), 18, 44, "topbar.logo_size")
    ld = p["landing"]
    landing = {k: _s(ld.get(k), 60 if k.startswith(("title", "button")) else 240) for k in
               ("title_ar", "title_en", "sub_ar", "sub_en", "button_ar", "button_en")}
    landing.update(show_qr=bool(ld.get("show_qr", True)), show_features=bool(ld.get("show_features", True)))

    texts = {}
    for lang in ("ar", "en"):
        src = (d.get("texts") or {}).get(lang) or {}
        if len(src) > 1500:
            raise DesignError("too many text overrides")
        texts[lang] = {}
        for k, v in src.items():
            if not TEXT_KEY.match(str(k)):
                raise DesignError(f"texts.{lang}: invalid key {k}")
            if str(v).strip():
                texts[lang][k] = _s(v, 2000)
    seo_in = d.get("seo") or {}
    seo = {"title": _s(seo_in.get("title"), 70), "description": _s(seo_in.get("description"), 170), "keywords": _s(seo_in.get("keywords"), 200),
           "site_name": _s(seo_in.get("site_name"), 40), "index": bool(seo_in.get("index", True))}
    og = str(seo_in.get("og_image") or "").strip()
    if og and not re.fullmatch(r"(https://|/api/media/)[^\s\"'<>]{1,400}", og):
        raise DesignError("seo.og_image must be an https URL")
    seo["og_image"] = og
    tc = str(seo_in.get("theme_color") or "#000000")
    if not HEX.match(tc):
        raise DesignError("seo.theme_color must be #RRGGBB")
    seo["theme_color"] = tc
    return {"tokens": tokens, "pages": {"start": start, "home": home, "nav": nav, "topbar": topbar, "landing": landing}, "texts": texts, "seo": seo}


# ═════════════════════════ التخزين: مسودة ← نشر، سجل، قوالب ═════════════════════════
def _doc(db):
    return db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1])


def load(db) -> dict:
    snap = _doc(db).get()
    raw = (snap.to_dict() or {}) if snap.exists else {}
    pub = raw.get("published") or {}
    draft = raw.get("draft") or pub
    try:
        pub = clean(pub)
    except DesignError:
        pub = default()
    try:
        draft = clean(draft)
    except DesignError:
        draft = pub
    return {"published": pub, "draft": draft, "published_at": raw.get("published_at"), "draft_at": raw.get("draft_at"),
            "version": int(raw.get("version") or 0)}


_PUB = {"v": None, "at": 0.0}


def published(db) -> dict:
    if _PUB["v"] is None or time.time() - _PUB["at"] > 30:
        st = load(db)
        _PUB.update(v={"version": st["version"], **st["published"]}, at=time.time())
    return _PUB["v"]


def save_draft(db, design: dict) -> dict:
    d = clean(design)
    _doc(db).set({"draft": d, "draft_at": time.time()}, merge=True)
    return d


def publish(db, design: dict | None, by, note: str = "", source: str = "manual") -> dict:
    st = load(db)
    d = clean(design if design is not None else st["draft"])
    version = st["version"] + 1
    now = time.time()
    _doc(db).set({"published": d, "draft": d, "published_at": now, "draft_at": now, "version": version}, merge=True)
    db.collection(HISTORY).document(f"v{version:06d}").set({"version": version, "at": now, "by": str(by), "note": _s(note, 200),
                                                            "source": source, "data": d})
    _PUB["v"] = None
    return {"version": version, "published": d}


def history(db, limit: int = 60) -> list:
    rows = [{"id": s.id, **{k: v for k, v in (s.to_dict() or {}).items() if k != "data"}} for s in db.collection(HISTORY).stream()]
    rows.sort(key=lambda r: -(r.get("version") or 0))
    return rows[:limit]


def restore(db, hid: str, by) -> dict:
    snap = db.collection(HISTORY).document(hid).get()
    if not snap.exists:
        raise DesignError("history entry not found")
    h = snap.to_dict() or {}
    return publish(db, h.get("data") or {}, by, f"استرجاع الإصدار {h.get('version')}", source="restore")


def history_item(db, hid: str) -> dict | None:
    snap = db.collection(HISTORY).document(hid).get()
    return {"id": hid, **(snap.to_dict() or {})} if snap.exists else None


def themes(db) -> list:
    rows = [{"id": s.id, **(s.to_dict() or {})} for s in db.collection(THEMES).stream()]
    rows.sort(key=lambda r: -(r.get("at") or 0))
    return rows


def save_theme(db, name: str, scopes: list, draft: dict, by, tag: str = "") -> dict:
    """يحفظ قالبًا من المسودة الحالية لصفحة واحدة أو عدة صفحات (مجموعة قوالب)."""
    scopes = [s for s in (scopes or []) if s in PAGES]
    if not scopes or not str(name or "").strip():
        raise DesignError("theme needs a name and at least one page")
    data = {}
    for s in scopes:
        data[s] = copy.deepcopy(draft["tokens"] if s == "global" else draft["pages"][s])
    ref = db.collection(THEMES).document()
    row = {"name": _s(name, 60), "scopes": scopes, "data": data, "tag": _s(tag, 30), "by": str(by), "at": time.time()}
    ref.set(row)
    return {"id": ref.id, **row}


def apply_theme(db, tid: str, scopes: list | None = None) -> dict:
    snap = db.collection(THEMES).document(tid).get()
    if not snap.exists:
        raise DesignError("theme not found")
    th = snap.to_dict() or {}
    d = copy.deepcopy(load(db)["draft"])
    for s in scopes or th.get("scopes") or []:
        if s not in (th.get("data") or {}):
            continue
        if s == "global":
            d["tokens"] = _deep_merge(d["tokens"], th["data"][s])
        else:
            d["pages"][s] = _deep_merge(d["pages"][s], th["data"][s])
    return save_draft(db, d)


# ═════════════════════════ قوالب جاهزة ═════════════════════════
def _preset(name, desc, tokens=None, pages=None):
    return {"name": name, "desc": desc, "tokens": tokens or {}, "pages": pages or {}}


PRESETS = {
    "aw_classic": _preset("AW الكلاسيكي", "الهوية الأصلية: أسود وبرتقالي بأزرار مائلة", {}),
    "midnight_gold": _preset("ذهبي ليلي", "فخامة ذهبية على كحلي داكن", {
        "dark": {"accent": "#e5b84b", "accent2": "#c9922e", "bg": "#070a12", "surface": "#0e1320", "text": "#f3efe6", "muted": "#8a8f9c"},
        "button_shape": "rounded", "card_style": "gradient", "font_display": "plex", "radius": 18}),
    "neon_mint": _preset("نعناعي نيون", "أخضر حيوي عصري للتطبيقات المالية", {
        "dark": {"accent": "#1fd1a0", "accent2": "#0fa3b1", "bg": "#03100d", "surface": "#0a1a16", "text": "#e9fff8", "muted": "#7fa39a"},
        "light": {"accent": "#0a9e78", "accent2": "#0b8793", "bg": "#f1f8f6", "surface": "#ffffff", "text": "#0e2520", "muted": "#5e7a73"},
        "button_shape": "pill", "card_style": "glass", "radius": 20}),
    "royal_purple": _preset("بنفسجي ملكي", "تدرج بنفسجي فاخر", {
        "dark": {"accent": "#a78bfa", "accent2": "#7c3aed", "bg": "#07040f", "surface": "#120b22", "text": "#f3eeff", "muted": "#9488b0"},
        "button_shape": "rounded", "card_style": "gradient", "radius": 16}),
    "clean_light": _preset("نهاري نظيف", "واجهة فاتحة بسيطة ومريحة", {
        "default_theme": "light", "button_shape": "rounded", "card_style": "solid", "radius": 16, "glow": 20}),
    "minimal_mono": _preset("بسيط أحادي", "بلا توهج، حدود رفيعة، تركيز كامل على الأرقام", {
        "dark": {"accent": "#f5f5f5", "accent2": "#bdbdbd", "bg": "#000000", "surface": "#0b0b0b", "text": "#f5f5f5", "muted": "#8a8a8a"},
        "button_shape": "square", "card_style": "outline", "glow": 0, "radius": 6, "font_display": "system", "font_body": "system"}),
    "compact_pro": _preset("احترافي مضغوط", "كثافة عالية لعرض أكثر في الشاشات الصغيرة", {
        "density": "compact", "ui_scale": 94, "radius": 10},
        {"home": {"quick": {"columns": 5}}}),
}


def apply_preset(db, key: str) -> dict:
    pr = PRESETS.get(key)
    if not pr:
        raise DesignError("preset not found")
    d = copy.deepcopy(load(db)["draft"])
    base = default()["tokens"]
    d["tokens"] = _deep_merge(base, pr["tokens"])  # القالب الجاهز يبدأ من الهوية الأصلية ثم يطبّق فروقه
    for page, patch in pr["pages"].items():
        d["pages"][page] = _deep_merge(d["pages"][page], patch)
    return save_draft(db, d)


# ═════════════════════════ الذكاء الاصطناعي: اقتراحات قابلة للتطبيق ═════════════════════════
AI_SYSTEM = """أنت مصمم واجهات خبير (UI/UX) لتطبيق تداول آلي فاخر داخل تلجرام اسمه AW ROBOT.
ستستلم إعدادات التصميم الحالية بصيغة JSON وطلب المسؤول. اقترح تحسينًا واحدًا متكاملًا ومتناسقًا.
أعد JSON فقط بهذا الشكل بلا أي نص آخر:
{"explanation": "شرح قصير بالعربية لما غيّرته ولماذا (3 جمل كحد أقصى)", "patch": { ... نفس بنية الإعدادات، فقط المفاتيح التي تغيّرها ... }}
قواعد: الألوان #RRGGBB فقط، حافظ على تباين كافٍ للقراءة (WCAG AA)، الأيقونات من هذه القائمة فقط: {icons}.
القيم المسموحة: font_body/font_display: plex|system|chakra · density: compact|comfortable|spacious · button_shape: angled|rounded|pill|square ·
card_style: glass|solid|outline|gradient · radius 0-32 · ui_scale 80-130 · glow 0-100.
عناصر الرئيسية: who, feedback, hero, announce, subscription, scratch, quick, growth. خلايا النمو: today, week, month, all, winrate, trades, profit_factor, drawdown.
اختصارات الرئيسية: support, notifications, billing, faq, calc, plans, rewards, referral, analytics, settings (تجنب تكرار ما في الشريط السفلي)."""


def _json_from(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise DesignError("AI returned no JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        raise DesignError("AI returned invalid JSON")


def ai_suggest(llm_text, cfg, draft: dict, scope: str, question: str) -> dict:
    """يطلب اقتراحًا من Gemini ويتحقق أنه صالح (يُدمج مع المسودة ويمر من clean) قبل إعادته للمسؤول."""
    focus = draft["tokens"] if scope == "global" else draft["pages"].get(scope, draft)
    prompt = (f"النطاق: {scope}\nطلب المسؤول: {question or 'حسّن التناسق والجاذبية والوضوح'}\n"
              f"الإعدادات الحالية للنطاق:\n{json.dumps(focus, ensure_ascii=False)[:6000]}")
    raw = llm_text(cfg, AI_SYSTEM.replace("{icons}", ", ".join(ICONS)), prompt, max_tokens=1600)
    out = _json_from(raw)
    patch = out.get("patch") or {}
    wrapped = {"tokens": patch} if scope == "global" else ({"pages": {scope: patch}} if scope in PAGES else patch)
    merged = clean(_deep_merge(draft, wrapped))  # يرفع خطأ إن اقترح شيئًا غير صالح
    return {"explanation": _s(out.get("explanation"), 600), "patch": wrapped, "preview": merged}


ICON_SYSTEM = """اختر أنسب أيقونة لعنصر في واجهة تطبيق تداول آلي من هذه القائمة فقط: {icons}.
أعد JSON فقط: {"icon": "الاسم", "alternatives": ["اسم", "اسم"], "reason": "سبب قصير بالعربية"}"""


def ai_icon(llm_text, cfg, label: str, current: str = "") -> dict:
    raw = llm_text(cfg, ICON_SYSTEM.replace("{icons}", ", ".join(ICONS)), f"العنصر: {label}\nالأيقونة الحالية: {current or '-'}", max_tokens=300)
    out = _json_from(raw)
    icon = out.get("icon") if out.get("icon") in ICONS else None
    if not icon:
        raise DesignError("AI suggested an unknown icon")
    return {"icon": icon, "alternatives": [a for a in (out.get("alternatives") or []) if a in ICONS and a != icon][:3], "reason": _s(out.get("reason"), 200)}


# ═════════════════════════ SEO: يُكتب في index.html للتطبيق (يراه جوجل وروابط المعاينة) ═════════════════════════
SEO_START, SEO_END = "<!--aw-seo-->", "<!--/aw-seo-->"


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def seo_html(seo: dict, base_url: str = "") -> str:
    title = _esc(seo.get("title") or "AW ROBOT")
    desc = _esc(seo.get("description") or "")
    img = seo.get("og_image") or ""
    if img.startswith("/") and base_url:
        img = base_url.rstrip("/") + img
    tags = [f"<title>{title}</title>", f'<meta name="description" content="{desc}" />',
            f'<meta name="keywords" content="{_esc(seo.get("keywords"))}" />',
            f'<meta name="robots" content="{"index, follow" if seo.get("index", True) else "noindex, nofollow"}" />',
            f'<meta name="theme-color" content="{_esc(seo.get("theme_color") or "#000000")}" />',
            f'<meta property="og:type" content="website" />', f'<meta property="og:title" content="{title}" />',
            f'<meta property="og:description" content="{desc}" />', f'<meta property="og:site_name" content="{_esc(seo.get("site_name"))}" />',
            f'<meta name="twitter:card" content="{"summary_large_image" if img else "summary"}" />',
            f'<meta name="twitter:title" content="{title}" />', f'<meta name="twitter:description" content="{desc}" />']
    if base_url:
        tags += [f'<link rel="canonical" href="{_esc(base_url)}" />', f'<meta property="og:url" content="{_esc(base_url)}" />']
    if img:
        tags += [f'<meta property="og:image" content="{_esc(img)}" />', f'<meta name="twitter:image" content="{_esc(img)}" />']
    return SEO_START + "\n    " + "\n    ".join(tags) + "\n    " + SEO_END


def write_seo(index_path: str, seo: dict, base_url: str = "") -> bool:
    """يستبدل كتلة SEO بين العلامتين في index.html المبني (يُستدعى عند النشر وعند تشغيل الخادم)."""
    try:
        with open(index_path, encoding="utf-8") as f:
            html = f.read()
    except OSError:
        return False
    if SEO_START not in html or SEO_END not in html:
        return False
    a, b = html.index(SEO_START), html.index(SEO_END) + len(SEO_END)
    new = html[:a] + seo_html(seo, base_url) + html[b:]
    if new != html:
        tmp = index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(tmp, index_path)
    return True
