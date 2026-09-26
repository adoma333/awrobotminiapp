"""
بطاقات GIF متحركة تُرفق تلقائيًا برسائل البوت — بتصميم AW (خلفية داكنة، توهّج برتقالي، شبكة خفيفة، شعار).

  • النوع يُستنتج من نص الرسالة (هدية، عرض، اشتراك، دفعة، تذكير، دعم، تنبيه، حساب، بطاقة كشط، ترحيب) أو يُمرَّر صراحةً.
  • كل نوع له أيقونة مرسومة وحركة خاصة: قصاصات احتفال للهدايا والعروض، شرارات صاعدة، نبض توهّج، لمعة تمر على البطاقة.
  • العنوان ثابت لكل نوع ولغة + «قيمة بارزة» مستخرجة (خصم %، مبلغ $، أيام…) ← نسبة إعادة استخدام عالية:
    البطاقة تُولَّد مرة واحدة، تُرفع لتلجرام مرة واحدة، ثم يُعاد استخدام file_id لكل المستخدمين.
  • النص العربي يُشكَّل ويُرتَّب من اليمين لليسار (raqm إن توفرت، وإلا arabic_reshaper + ترتيب ثنائي الاتجاه مبسّط).
"""
import hashlib
import io
import math
import os
import random
import re

from PIL import Image, ImageDraw, ImageFilter, ImageFont, features

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_BOLD = os.path.join(HERE, "assets", "fonts", "IBMPlexSansArabic-Bold.ttf")
FONT_MED = os.path.join(HERE, "assets", "fonts", "IBMPlexSansArabic-Medium.ttf")
LOGO = os.path.join(HERE, "assets", "cards", "logo.png")
W, H = 640, 360
FRAMES = 18
FRAME_MS = 80
EMBER = (255, 138, 0)
BG = (10, 9, 8)
RAQM = features.check("raqm")

KINDS = {
    # kind: (label_en, title_ar, title_en, accent, motion)
    "gift": ("GIFT", "هدية خاصة لك", "A special gift for you", (255, 138, 0), "confetti"),
    "offer": ("OFFER", "عرض خاص لك", "An exclusive offer", (255, 176, 32), "confetti"),
    "package": ("PLAN", "تم تفعيل اشتراكك", "Your plan is active", (255, 138, 0), "sparks"),
    "payment": ("PAYMENT", "تم استلام الدفعة", "Payment received", (38, 196, 133), "sparks"),
    "reminder": ("REMINDER", "تذكير مهم", "Friendly reminder", (255, 176, 32), "pulse"),
    "support": ("SUPPORT", "رد من الدعم الفني", "Support update", (86, 156, 255), "pulse"),
    "alert": ("ALERT", "تنبيه", "Heads up", (229, 87, 75), "pulse"),
    "account": ("ACCOUNT", "حساب التداول", "Trading account", (31, 167, 160), "sparks"),
    "scratch": ("SCRATCH & WIN", "بطاقة كشط جديدة", "New scratch card", (255, 138, 0), "confetti"),
    "referral": ("REFERRAL", "مكافأة الإحالة", "Referral reward", (255, 138, 0), "confetti"),
    "welcome": ("WELCOME", "أهلًا بك في AW", "Welcome to AW", (255, 138, 0), "sparks"),
    "brand": ("AW ROBOT", "AW ROBOT", "AW ROBOT", (255, 138, 0), "sparks"),
}
# ترتيب الأولوية مهم: الأكثر تحديدًا أولًا
RULES = [
    ("scratch", r"بطاقة كشط|كشط|scratch"),
    ("gift", r"🎁|هدية|هديتك|gift"),
    ("offer", r"خصم|عرض خاص|discount|% off|offer"),
    ("referral", r"إحالة|دعوة صديق|referral|invite"),
    ("payment", r"استلمنا|تم الدفع|دفعتك|الدفعة|payment (?:received|confirmed)|we received"),
    ("package", r"تم تفعيل|اشتراكك (?:مفعّل|فعّال)|activated|subscription is active|plan is active"),
    ("reminder", r"🔔|تذكير|ينتهي|تجديد|expires|renew|reminder"),
    ("support", r"🎧|💬|تذكرة|الدعم|support|ticket"),
    ("alert", r"⚠️|❌|فشل|تعذّر|رفض|failed|rejected|declined|error"),
    ("account", r"MT5|ربط الحساب|حسابك|account linked|trading account"),
    ("welcome", r"مرحب|أهلًا|أهلا|welcome"),
]
_HL = [r"\d{1,3}\s?%", r"\$\s?\d+(?:[.,]\d+)?", r"\d+(?:[.,]\d+)?\s?(?:USDT|TON|USD|\$)", r"\d{1,4}\s?(?:يوم|أيام|ساعة|days?|hours?)"]


def classify(text: str) -> str:
    low = (text or "").lower()
    for kind, rx in RULES:
        if re.search(rx, low, re.I):
            return kind
    return "brand"


def highlight(text: str) -> str:
    for rx in _HL:
        m = re.search(rx, text or "", re.I)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()[:14]
    return ""


def spec_for(text: str, lang: str, kind: str | None = None, title: str | None = None, hl: str | None = None) -> dict:
    kind = kind if kind in KINDS else classify(text)
    k = KINDS[kind]
    return {"kind": kind, "lang": "ar" if lang == "ar" else "en", "title": (title or (k[1] if lang == "ar" else k[2]))[:34],
            "hl": (highlight(text) if hl is None else hl)[:14]}


def cache_key(spec: dict) -> str:
    raw = f"v3|{spec['kind']}|{spec['lang']}|{spec['title']}|{spec['hl']}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


# ═════════════════════════ النص ثنائي الاتجاه ═════════════════════════
_AR = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LTR_RUN = re.compile(r"[A-Za-z0-9$%.,:+\-#/@&]+(?:\s+[A-Za-z0-9$%.,:+\-#/@&]+)*")


def _visual(text: str) -> str:
    """بلا raqm: تشكيل الحروف ثم ترتيب مرئي (الكلمات العربية معكوسة، والمقاطع اللاتينية/الأرقام كما هي)."""
    try:
        import arabic_reshaper

        text = arabic_reshaper.reshape(text)
    except ImportError:
        pass
    out, pos = [], 0
    for m in _LTR_RUN.finditer(text):
        out.append(("rtl", text[pos:m.start()]))
        out.append(("ltr", m.group(0)))
        pos = m.end()
    out.append(("rtl", text[pos:]))
    return "".join(seg if kind == "ltr" else seg[::-1] for kind, seg in reversed(out))


def _draw_text(d: ImageDraw.ImageDraw, xy, text: str, font, fill, anchor="mm"):
    if _AR.search(text):
        if RAQM:
            d.text(xy, text, font=font, fill=fill, anchor=anchor, direction="rtl", language="ar")
        else:
            d.text(xy, _visual(text), font=font, fill=fill, anchor=anchor)
    else:
        d.text(xy, text, font=font, fill=fill, anchor=anchor)


def _fit(text: str, path: str, size: int, max_w: int):
    while size > 14:
        f = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM if RAQM else ImageFont.Layout.BASIC)
        w = f.getlength(text if RAQM or not _AR.search(text) else _visual(text), **({"direction": "rtl"} if RAQM and _AR.search(text) else {}))
        if w <= max_w:
            return f
        size -= 2
    return ImageFont.truetype(path, size)


# ═════════════════════════ الأيقونات ═════════════════════════
def _icon(d: ImageDraw.ImageDraw, kind: str, cx: int, cy: int, s: float, accent, t: float):
    a = accent
    wob = math.sin(t * 2 * math.pi) * 3
    if kind in ("gift", "referral"):
        top = cy - 10 * s + wob
        d.rounded_rectangle([cx - 42 * s, cy - 6 * s, cx + 42 * s, cy + 44 * s], 8 * s, fill=(28, 22, 16), outline=a, width=int(3 * s))
        d.rounded_rectangle([cx - 50 * s, top - 18 * s, cx + 50 * s, top + 2 * s], 6 * s, fill=(40, 30, 18), outline=a, width=int(3 * s))
        d.rectangle([cx - 7 * s, top - 18 * s, cx + 7 * s, cy + 44 * s], fill=a)
        d.ellipse([cx - 34 * s, top - 44 * s, cx - 4 * s, top - 18 * s], outline=a, width=int(5 * s))
        d.ellipse([cx + 4 * s, top - 44 * s, cx + 34 * s, top - 18 * s], outline=a, width=int(5 * s))
    elif kind == "offer":
        d.regular_polygon((cx, cy + wob, 52 * s), 12, rotation=t * 30, fill=a)
        d.text((cx, cy + wob), "%", font=ImageFont.truetype(FONT_BOLD, int(54 * s)), fill=BG, anchor="mm")
    elif kind in ("package", "welcome", "brand"):
        pts = [(cx - 50 * s, cy + 30 * s), (cx - 56 * s, cy - 26 * s), (cx - 24 * s, cy + 2 * s), (cx, cy - 44 * s + wob),
               (cx + 24 * s, cy + 2 * s), (cx + 56 * s, cy - 26 * s), (cx + 50 * s, cy + 30 * s)]
        d.polygon(pts, fill=(40, 30, 18), outline=a, width=int(4 * s))
        d.rounded_rectangle([cx - 50 * s, cy + 34 * s, cx + 50 * s, cy + 46 * s], 4 * s, fill=a)
        for px in (-56, 0, 56):
            d.ellipse([cx + px * s - 7 * s, cy - (44 if px == 0 else 26) * s - 7 * s + (wob if px == 0 else 0),
                       cx + px * s + 7 * s, cy - (44 if px == 0 else 26) * s + 7 * s + (wob if px == 0 else 0)], fill=a)
    elif kind == "payment":
        r = 50 * s
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=a, width=int(5 * s))
        prog = min(1.0, t * 1.6)
        p1, p2, p3 = (cx - 24 * s, cy + 2 * s), (cx - 6 * s, cy + 20 * s), (cx + 26 * s, cy - 18 * s)
        if prog < 0.4:
            k = prog / 0.4
            d.line([p1, (p1[0] + (p2[0] - p1[0]) * k, p1[1] + (p2[1] - p1[1]) * k)], fill=a, width=int(8 * s))
        else:
            k = (prog - 0.4) / 0.6
            d.line([p1, p2, (p2[0] + (p3[0] - p2[0]) * k, p2[1] + (p3[1] - p2[1]) * k)], fill=a, width=int(8 * s), joint="curve")
    elif kind == "reminder":
        ang = math.sin(t * 4 * math.pi) * 12
        bell = Image.new("RGBA", (int(120 * s), int(120 * s)), (0, 0, 0, 0))
        b = ImageDraw.Draw(bell)
        m = 60 * s
        b.pieslice([m - 40 * s, m - 44 * s, m + 40 * s, m + 36 * s], 180, 360, fill=a)
        b.rectangle([m - 40 * s, m - 5 * s, m + 40 * s, m + 26 * s], fill=a)
        b.rounded_rectangle([m - 50 * s, m + 22 * s, m + 50 * s, m + 32 * s], 5 * s, fill=a)
        b.ellipse([m - 10 * s, m + 32 * s, m + 10 * s, m + 50 * s], fill=a)
        bell = bell.rotate(ang, resample=Image.BICUBIC, center=(m, m - 40 * s))
        d._image.paste(bell, (int(cx - m), int(cy - m)), bell)
    elif kind == "support":
        d.rounded_rectangle([cx - 54 * s, cy - 40 * s + wob, cx + 54 * s, cy + 30 * s + wob], 18 * s, fill=(20, 28, 44), outline=a, width=int(4 * s))
        d.polygon([(cx - 20 * s, cy + 28 * s + wob), (cx - 34 * s, cy + 50 * s + wob), (cx, cy + 28 * s + wob)], fill=a)
        for i in range(3):
            on = int(t * 3 * FRAMES) % 3 == i
            d.ellipse([cx + (i - 1) * 28 * s - 8 * s, cy - 5 * s - 8 * s + wob - (4 if on else 0), cx + (i - 1) * 28 * s + 8 * s, cy - 5 * s + 8 * s + wob - (4 if on else 0)],
                      fill=a if on else (120, 150, 200))
    elif kind == "alert":
        d.polygon([(cx, cy - 50 * s), (cx + 56 * s, cy + 44 * s), (cx - 56 * s, cy + 44 * s)], fill=(44, 20, 18), outline=a, width=int(5 * s))
        d.rounded_rectangle([cx - 6 * s, cy - 18 * s, cx + 6 * s, cy + 16 * s], 4 * s, fill=a)
        d.ellipse([cx - 7 * s, cy + 22 * s, cx + 7 * s, cy + 36 * s], fill=a)
    elif kind == "account":
        for i, off in enumerate((-22, 22)):
            d.rounded_rectangle([cx + off * s - 34 * s, cy - 18 * s + (wob if i else -wob), cx + off * s + 34 * s, cy + 18 * s + (wob if i else -wob)],
                                18 * s, outline=a, width=int(8 * s))
    elif kind == "scratch":
        d.rounded_rectangle([cx - 64 * s, cy - 40 * s, cx + 64 * s, cy + 40 * s], 12 * s, fill=(60, 44, 24), outline=a, width=int(4 * s))
        sweep = cx - 64 * s + (128 * s) * t
        d.polygon([(sweep - 20 * s, cy + 40 * s), (sweep, cy - 40 * s), (sweep + 12 * s, cy - 40 * s), (sweep - 8 * s, cy + 40 * s)], fill=(255, 220, 150))
        d.text((cx, cy), "?", font=ImageFont.truetype(FONT_BOLD, int(46 * s)), fill=a, anchor="mm")


# ═════════════════════════ الإطارات ═════════════════════════
def _background(accent) -> Image.Image:
    bg = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(bg)
    for x in range(0, W, 32):
        d.line([(x, 0), (x, H)], fill=(20, 18, 16))
    for y in range(0, H, 32):
        d.line([(0, y), (W, y)], fill=(20, 18, 16))
    return bg


def _glow(accent, cx, cy, r, strength) -> Image.Image:
    g = Image.new("RGB", (W, H), (0, 0, 0))
    ImageDraw.Draw(g).ellipse([cx - r, cy - r, cx + r, cy + r], fill=tuple(int(c * strength) for c in accent))
    return g.filter(ImageFilter.GaussianBlur(r * 0.55))


def _particles(kind_motion: str, seed: int, n: int = 34) -> list:
    rnd = random.Random(seed)
    cols = [EMBER, (255, 200, 90), (255, 255, 255), (31, 167, 160), (229, 87, 75)]
    return [{"x": rnd.uniform(0, W), "y": rnd.uniform(-H, H), "v": rnd.uniform(0.6, 1.4), "sz": rnd.uniform(2, 6),
             "c": rnd.choice(cols if kind_motion == "confetti" else cols[:3]), "ph": rnd.uniform(0, 6.28)} for _ in range(n)]


def render(spec: dict) -> bytes:
    kind, lang = spec["kind"], spec["lang"]
    label, _ta, _te, accent, motion = KINDS[kind]
    rtl = lang == "ar"
    base = _background(accent)
    logo = None
    try:
        logo = Image.open(LOGO).convert("RGB")
        logo.thumbnail((92, 72))
    except OSError:
        pass
    parts = _particles(motion, int(cache_key(spec)[:8], 16))
    f_label = ImageFont.truetype(FONT_BOLD, 17)
    title = spec["title"]
    f_title = _fit(title, FONT_BOLD, 40, 360)
    f_hl = _fit(spec["hl"], FONT_BOLD, 64, 330) if spec["hl"] else None
    icon_x = 150 if rtl else W - 150  # الأيقونة في الجهة المقابلة لبداية القراءة
    text_x = W - 205 if rtl else 205
    frames = []
    for i in range(FRAMES):
        t = i / FRAMES
        pulse = 0.5 + 0.5 * math.sin(t * 2 * math.pi)
        glow = _glow(accent, icon_x, H // 2, 110 + 18 * pulse, 0.42 + 0.18 * pulse)
        im = _add(base, glow)
        d = ImageDraw.Draw(im)
        # إطار البطاقة + لمعة تمر عليه
        d.rounded_rectangle([14, 14, W - 14, H - 14], 26, outline=(52, 42, 30), width=2)
        sx = int(-200 + (W + 400) * t)
        shine = Image.new("L", (W, H), 0)
        ImageDraw.Draw(shine).polygon([(sx, 0), (sx + 60, 0), (sx - 60, H), (sx - 120, H)], fill=60)
        edge = Image.new("L", (W, H), 0)
        ImageDraw.Draw(edge).rounded_rectangle([14, 14, W - 14, H - 14], 26, outline=255, width=3)
        im.paste(accent, (0, 0), _mul(shine, edge))
        # الجزيئات
        for p in parts:
            if motion == "confetti":
                y = (p["y"] + t * H * 1.0 * p["v"]) % (H + 40) - 20
                x = p["x"] + math.sin(p["ph"] + t * 6.28) * 10
                d.rectangle([x, y, x + p["sz"] * 1.6, y + p["sz"]], fill=p["c"])
            elif motion == "sparks":
                y = H - ((p["y"] + t * H * p["v"]) % (H + 20))
                d.ellipse([p["x"], y, p["x"] + p["sz"] * 0.7, y + p["sz"] * 0.7], fill=p["c"] if p["sz"] > 4 else (120, 80, 30))
            else:  # pulse
                r = 40 + (t * 160 + p["ph"] * 10) % 160
                if p is parts[0]:
                    d.ellipse([icon_x - r, H // 2 - r, icon_x + r, H // 2 + r], outline=tuple(int(c * (1 - r / 200)) for c in accent), width=2)
        _icon(d, kind, icon_x, H // 2, 1.25, accent, t)
        # النص
        ease = min(1.0, t * 3)
        dy = int((1 - ease) * 14)
        y0 = 0 if f_hl else 38  # بلا قيمة بارزة: النص في منتصف البطاقة
        _draw_text(d, (text_x, 96 + y0 - dy // 2), label, f_label, accent)
        _draw_text(d, (text_x, 160 + y0 - dy), title, f_title, (245, 240, 232))
        if f_hl:
            _draw_text(d, (text_x, 238 - dy), spec["hl"], f_hl, accent)
        if logo:
            im.paste(logo, (W - 36 - logo.width if not rtl else 36, H - 30 - logo.height), _logo_mask(logo))
        frames.append(im.convert("P", palette=Image.ADAPTIVE, colors=96))
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=FRAME_MS, loop=0, optimize=True, disposal=1)
    return out.getvalue()


def _add(a: Image.Image, b: Image.Image) -> Image.Image:
    from PIL import ImageChops

    return ImageChops.add(a, b)


def _mul(a: Image.Image, b: Image.Image) -> Image.Image:
    from PIL import ImageChops

    return ImageChops.multiply(a, b)


def _logo_mask(logo: Image.Image) -> Image.Image:
    """الشعار على خلفية سوداء: السطوع قناعًا (الأسود يختفي فوق الخلفية الداكنة)."""
    return logo.convert("L").point(lambda v: min(255, v * 2))


# ═════════════════════════ التخزين المؤقت ═════════════════════════
CACHE_DIR = os.getenv("CARDS_CACHE_DIR") or os.path.join(HERE, "media", "cards")


def get_file(spec: dict) -> str:
    """مسار ملف GIF للبطاقة (يُولَّد مرة واحدة ثم يُعاد استخدامه)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, cache_key(spec) + ".gif")
    if not os.path.exists(path):
        data = render(spec)
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    return path
