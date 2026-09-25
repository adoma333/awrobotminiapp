"""
AW Leaderboard Script — لغة معادلات آمنة يكتبها الأدمن للتحكم الكامل بحركة المتصدرين المُدارين.

المعادلة تُحسب لكل اسم في كل حركة (tick) وتُرجع القيمة الجديدة لربحه بالدولار. أمثلة:
    base * (1 + 0.1 * sin(t / 3600 + i))                      موجة ناعمة لكل اسم بطور مختلف
    cur + base * noise(0.03) + (base - cur) * 0.2               تذبذب عشوائي مع عودة نحو الأساس
    base * (1 + 0.4 * week) if elite else cur + noise(base*0.02)  النخبة تصعد تدريجيًا خلال الأسبوع

الأمان: لا تُنفَّذ المعادلة كبايثون إطلاقًا. تُحلَّل إلى شجرة وتُقيَّم بمقيِّم خاص يسمح فقط بالأرقام،
المتغيرات أدناه، العمليات الحسابية والمقارنات، والدوال المسموحة. لا وصول لأي ملف أو شبكة أو كائن.

المتغيرات: base cur i n rank t day hour week tick elite prev
الدوال: sin cos tan abs min max clamp floor ceil round sqrt log exp rand noise wave step pick
"""
import ast
import math
import random

MAX_LEN = 1500
MAX_NODES = 400
VARS = ("base", "cur", "i", "n", "rank", "t", "day", "hour", "week", "tick", "elite", "prev")
VAR_HELP = {"base": "القيمة الأساسية المؤكَّدة", "cur": "القيمة الحالية", "i": "ترتيب الاسم في القائمة (من 0)",
            "n": "عدد الأسماء", "rank": "المركز الحالي (1 = الأول)", "t": "ثوانٍ منذ بداية الأسبوع",
            "day": "يوم الأسبوع 0-6", "hour": "الساعة 0-23 (UTC)", "week": "نسبة مرور الأسبوع 0→1",
            "tick": "رقم الحركة منذ بداية الأسبوع", "elite": "1 إن كان من النخبة وإلا 0", "prev": "آخر تغيّر (delta)"}


class ScriptError(ValueError):
    pass


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _safe_log(x):
    return math.log(x) if x > 0 else 0.0


def _safe_sqrt(x):
    return math.sqrt(x) if x >= 0 else 0.0


def _safe_exp(x):
    return math.exp(min(50.0, x))


FUNCS_META = {"sin": 1, "cos": 1, "tan": 1, "abs": 1, "floor": 1, "ceil": 1, "sqrt": 1, "log": 1, "exp": 1,
              "round": (1, 2), "min": (2, 8), "max": (2, 8), "clamp": 3, "rand": (0, 2), "noise": 1, "wave": (1, 2),
              "step": 2, "pick": (2, 8)}
FUNC_HELP = {"rand()": "رقم عشوائي 0→1 (rand(a,b) بين a وb)", "noise(s)": "تذبذب عشوائي طبيعي بانحراف s",
             "wave(p)": "موجة -1→1 بدورة p ثانية (wave(p, phase))", "step(x, s)": "تقريب x لأقرب مضاعف لـ s",
             "clamp(x,a,b)": "حصر x بين a وb", "pick(a,b,..)": "اختيار عشوائي من القيم"}

_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b if b else 0.0, ast.Mod: lambda a, b: a % b if b else 0.0,
        ast.FloorDiv: lambda a, b: a // b if b else 0.0}
_CMP = {ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b, ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b, ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


def compile_script(src: str) -> ast.Expression:
    """يحلل ويتحقق مرة واحدة. يرفع ScriptError برسالة واضحة للأدمن."""
    src = (src or "").strip()
    if not src:
        raise ScriptError("المعادلة فارغة")
    if len(src) > MAX_LEN:
        raise ScriptError(f"المعادلة أطول من {MAX_LEN} حرف")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise ScriptError(f"خطأ في الصياغة عند العمود {e.offset}: {e.msg}")
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > MAX_NODES:
            raise ScriptError("المعادلة معقدة جدًا")
        if isinstance(node, (ast.Expression, ast.Load, ast.operator, ast.unaryop, ast.cmpop, ast.boolop)):
            continue
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                raise ScriptError("مسموح بالأرقام فقط كقيم ثابتة")
        elif isinstance(node, ast.Name):
            if node.id not in VARS and node.id not in FUNCS_META:
                raise ScriptError(f"اسم غير معروف: {node.id}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS_META or node.keywords:
                raise ScriptError("استدعاء دالة غير مسموح")
            want = FUNCS_META[node.func.id]
            lo, hi = (want, want) if isinstance(want, int) else want
            if not lo <= len(node.args) <= hi:
                raise ScriptError(f"الدالة {node.func.id} تأخذ {lo if lo == hi else f'{lo}-{hi}'} وسائط")
        elif isinstance(node, ast.BinOp):
            if type(node.op) not in _BIN and not isinstance(node.op, ast.Pow):
                raise ScriptError("عملية حسابية غير مسموحة")
        elif isinstance(node, ast.UnaryOp):
            if not isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
                raise ScriptError("عملية غير مسموحة")
        elif isinstance(node, (ast.BoolOp, ast.IfExp)):
            continue
        elif isinstance(node, ast.Compare):
            if any(type(op) not in _CMP for op in node.ops):
                raise ScriptError("مقارنة غير مسموحة")
        else:
            raise ScriptError(f"عنصر غير مسموح: {type(node).__name__}")
    return tree


def _num(x) -> float:
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return 0.0
    return max(-1e12, min(1e12, x))


def evaluate(tree: ast.Expression, env: dict, rng: random.Random) -> float:
    funcs = {
        "sin": math.sin, "cos": math.cos, "tan": lambda x: _clamp(math.tan(x), -1e6, 1e6), "abs": abs,
        "floor": math.floor, "ceil": math.ceil, "sqrt": _safe_sqrt, "log": _safe_log, "exp": _safe_exp,
        "round": lambda x, d=0: round(x, int(_clamp(d, 0, 6))), "min": min, "max": max, "clamp": _clamp,
        "rand": lambda a=0.0, b=1.0: rng.uniform(a, b), "noise": lambda s: rng.gauss(0, abs(s)),
        "wave": lambda p, ph=0.0: math.sin(2 * math.pi * (env["t"] / max(1.0, abs(p)) + ph)),
        "step": lambda x, s: round(x / s) * s if s else x, "pick": lambda *xs: rng.choice(xs),
    }

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return env[node.id]
        if isinstance(node, ast.BinOp):
            a, b = _num(ev(node.left)), _num(ev(node.right))
            if isinstance(node.op, ast.Pow):
                if abs(b) > 10 or (a < 0 and b != int(b)):
                    return 0.0
                return _num(a ** b)
            return _num(_BIN[type(node.op)](a, b))
        if isinstance(node, ast.UnaryOp):
            v = ev(node.operand)
            return (not v) if isinstance(node.op, ast.Not) else (-_num(v) if isinstance(node.op, ast.USub) else _num(v))
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.Compare):
            left = _num(ev(node.left))
            for op, comp in zip(node.ops, node.comparators):
                right = _num(ev(comp))
                if not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return ev(node.body) if ev(node.test) else ev(node.orelse)
        if isinstance(node, ast.Call):
            return _num(funcs[node.func.id](*[_num(ev(a)) for a in node.args]))
        raise ScriptError("عنصر غير مسموح")

    try:
        return _num(ev(tree))
    except ScriptError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ScriptError(f"خطأ أثناء الحساب: {type(e).__name__}")


PRESETS = [
    {"name": "تذبذب طبيعي مع عودة للأساس", "script": "cur + noise(base * 0.03) + (base - cur) * 0.2"},
    {"name": "موجات بأطوار مختلفة", "script": "base * (1 + 0.12 * wave(86400, i / n))"},
    {"name": "صعود تدريجي خلال الأسبوع", "script": "base * (0.6 + 0.6 * week) + noise(base * 0.01)"},
    {"name": "النخبة تتبادل الصدارة", "script": "base * (1 + 0.15 * wave(43200, i * 0.33)) if elite else cur + noise(base * 0.02) + (base - cur) * 0.25"},
    {"name": "هادئ ليلًا، نشط نهارًا", "script": "cur + noise(base * (0.005 if hour < 7 else 0.03)) + (base - cur) * 0.15"},
]


def simulate(tree, bots: list, interval_sec: int, hours: int = 168, seed: int = 7) -> list:
    """معاينة: يحاكي الأسبوع بالكامل ويعيد سلسلة لكل اسم (للرسم في لوحة التحكم)."""
    rng = random.Random(seed)
    cur = [float(b["base"]) for b in bots]
    prev = [0.0] * len(bots)
    series = [[round(v, 2)] for v in cur]
    steps = max(1, int(hours * 3600 / max(60, interval_sec)))
    stride = max(1, steps // 84)  # نحو 84 نقطة للرسم
    for k in range(1, steps + 1):
        t = k * interval_sec
        order = sorted(range(len(cur)), key=lambda j: -cur[j])
        ranks = {j: r + 1 for r, j in enumerate(order)}
        for j, b in enumerate(bots):
            env = {"base": float(b["base"]), "cur": cur[j], "i": j, "n": len(bots), "rank": ranks[j], "t": t,
                   "day": int(t // 86400) % 7, "hour": int(t // 3600) % 24, "week": min(1.0, t / (7 * 86400)),
                   "tick": k, "elite": 1 if b.get("elite") else 0, "prev": prev[j]}
            new = max(0.0, evaluate(tree, env, rng))
            prev[j], cur[j] = new - cur[j], new
        if k % stride == 0:
            for j in range(len(bots)):
                series[j].append(round(cur[j], 2))
    return series
