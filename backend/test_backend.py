"""اختبارات الباك اند (بلا Firebase ولا تلجرام ولا MT5 حقيقية): python test_backend.py"""
import base64
import hashlib
import hmac
import json
import os
import re
import sys
import tempfile
import time
import types
from datetime import datetime, timezone
from urllib.parse import urlencode

# ───────────── Firestore وهمي في الذاكرة ─────────────
SERVER_TS = object()


def _now():
    return datetime.now(timezone.utc)


def _materialize(v):
    if v is SERVER_TS:
        return _now()
    if isinstance(v, dict):
        return {k: _materialize(x) for k, x in v.items()}
    return v


def _merge(dst, src):
    for k, v in src.items():
        v = _materialize(v)
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def _get_path(d, path):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return False, None
        cur = cur[p]
    return True, cur


class Snap:
    def __init__(self, id_, data):
        self.id, self._d = id_, data
        self.exists = data is not None

    def to_dict(self):
        return json.loads(json.dumps(self._d, default=lambda o: o)) if False else (dict(self._d) if self._d is not None else None)


class Query:
    def __init__(self, store, name, filters=None, lim=None, order=None):
        self.store, self.name = store, name
        self.filters, self.lim, self.order = filters or [], lim, order

    def where(self, field=None, op=None, value=None, filter=None):
        if filter is not None:
            field, op, value = filter.field_path, filter.op_string, filter.value
        return Query(self.store, self.name, self.filters + [(field, op, value)], self.lim, self.order)

    def limit(self, n):
        q = Query(self.store, self.name, self.filters, n, self.order)
        q.desc = getattr(self, "desc", False)
        return q

    def order_by(self, field, direction="ASCENDING"):
        q = Query(self.store, self.name, self.filters, self.lim, field)
        q.desc = direction == "DESCENDING"
        return q

    def select(self, _fields):
        return self

    def _rows(self):
        rows = []
        for id_, d in self.store.setdefault(self.name, {}).items():
            good = True
            for f, op, v in self.filters:
                has, cur = _get_path(d, f)
                name = getattr(op, "name", op)  # FieldFilter الحقيقي يحوّل != None إلى IS_NOT_NULL
                if name in ("==", "EQUAL"):
                    good &= has and cur == v
                elif name in ("!=", "NOT_EQUAL"):
                    good &= has and cur != v
                elif name in (">=", "GREATER_THAN_OR_EQUAL"):
                    good &= has and cur is not None and cur >= v
                elif name in ("<", "LESS_THAN"):
                    good &= has and cur is not None and cur < v
                elif name == "IS_NOT_NULL":
                    good &= has and cur is not None
                elif name == "IS_NULL":
                    good &= (not has) or cur is None
                else:
                    raise AssertionError(f"عامل استعلام غير مدعوم في القاعدة الوهمية: {name}")
            if good:
                rows.append(Snap(id_, d))
        if self.order:
            rows.sort(key=lambda r: (r.to_dict().get(self.order) is None, r.to_dict().get(self.order)),
                      reverse=getattr(self, "desc", False))
        return rows[: self.lim] if self.lim else rows

    def stream(self):
        return iter(self._rows())

    def get(self):
        return self._rows()


class Doc:
    def __init__(self, store, name, id_):
        self.store, self.name, self.id = store, name, id_

    def _col(self):
        return self.store.setdefault(self.name, {})

    def get(self):
        return Snap(self.id, self._col().get(self.id))

    def set(self, data, merge=False):
        if merge and self.id in self._col():
            _merge(self._col()[self.id], data)
        else:
            self._col()[self.id] = _materialize(data)

    def update(self, data):
        cur = self._col()[self.id]
        for k, v in data.items():
            *path, last = k.split(".")
            d = cur
            for p in path:
                d = d.setdefault(p, {})
            d[last] = _materialize(v)

    def delete(self):
        self._col().pop(self.id, None)

    def create(self, data):
        if self.id in self._col():
            from rewards import AlreadyExists
            raise AlreadyExists("exists")
        self._col()[self.id] = _materialize(data)


class Col(Query):
    def __init__(self, store, name):
        super().__init__(store, name)
        self._n = 0

    def document(self, id_=None):
        if id_ is None:
            id_ = f"auto{len(self.store.setdefault(self.name, {})) + 1}"
        return Doc(self.store, self.name, str(id_))


class FakeDB:
    def __init__(self):
        self.store = {}

    def collection(self, name):
        return Col(self.store, name)


DB = FakeDB()
fa = types.ModuleType("firebase_admin")
fa.initialize_app = lambda c: None
cr = types.ModuleType("firebase_admin.credentials")
cr.Certificate = lambda x: x
fs = types.ModuleType("firebase_admin.firestore")
fs.client = lambda: DB
fs.SERVER_TIMESTAMP = SERVER_TS
fa.credentials, fa.firestore = cr, fs
sys.modules.update({"firebase_admin": fa, "firebase_admin.credentials": cr, "firebase_admin.firestore": fs})

# ───────────── بيئة الاختبار (قبل استيراد main) ─────────────
NP_SECRET = "np-secret"
os.environ.update(
    BOT_TOKEN="123:TEST", CHANNEL_ID="-100999", WEBHOOK_SECRET="sekret", ADMIN_IDS="555",
    FIREBASE_KEY_JSON="{}", WEBAPP_URL="https://example.test", ADMIN_SESSION_SECRET="jwt-secret",
    NOWPAYMENTS_API_KEY="np-key", NOWPAYMENTS_IPN_SECRET=NP_SECRET,
    MT5_LOCK_PATH=os.path.join(tempfile.mkdtemp(), "mt5.lock"),
)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import billing  # noqa: E402
import main  # noqa: E402
import payments  # noqa: E402
import sync_worker  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

CALLS = []


def fake_tg(method, **p):
    CALLS.append((method, p))
    if method == "createInvoiceLink":
        return {"ok": True, "result": "https://t.me/$invoice"}
    return {"ok": True}


main.tg = fake_tg
import support  # noqa: E402
REAL_LLM = support.llm
import analytics  # noqa: E402
support.bot_call = lambda token, method, **p: fake_tg(method, _token=token, **p) if method != "sendMessage" else (CALLS.append((method, {"_token": token, **p})) or {"ok": True, "result": {"message_id": len(CALLS)}})
support.ASYNC = False
os.environ.pop("ANTHROPIC_API_KEY", None)
main.get_logo_file_id = lambda: None
c = TestClient(main.app, base_url="https://testserver")


def ok(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    assert cond, name


def init_data(uid=42, token="123:TEST", age=0, lang="ar", premium=False):
    u = {"id": uid, "first_name": "Ali", "username": "ali_x", "language_code": lang}
    if premium:
        u["is_premium"] = True
    user = json.dumps(u)
    p = {"auth_date": str(int(time.time()) - age), "user": user}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(p.items()))
    sec = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    p["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return urlencode(p)


def reset():
    DB.store.clear()
    CALLS.clear()


def add_user(uid, **kw):
    DB.store.setdefault("users", {})[str(uid)] = kw


def add_package(id_="p1", **kw):
    row = {"name_ar": "شهري", "name_en": "Monthly", "price_usd": 29.0, "duration_days": 30,
           "active": True, "sort_order": 1, "price_stars": 1500}
    row.update(kw)
    DB.store.setdefault("packages", {})[id_] = row


def active_sub(days=10):
    return {"package_id": "p1", "package_name_ar": "شهري", "package_name_en": "Monthly",
            "expires_at": time.time() + days * 86400, "status": "active"}


# ───────────── عميل MT5 وهمي داخل register ─────────────
class FakeBridge:
    def __init__(self, cfg): pass
    def start(self): pass


class FakeClient:
    mode = "ok"
    seen = {}

    def __init__(self, cfg, bridge=None): pass

    def fetch(self, login, password, server, since, now, lock_wait=None):
        FakeClient.seen = {"login": login, "lock_wait": lock_wait}
        m = FakeClient.mode
        if isinstance(m, Exception):
            raise m
        return {"account": {"login": login, "balance": 1000.0, "equity": 1000.0, "profit": 0.0,
                            "margin": 0.0, "margin_free": 1000.0, "margin_level": 0.0, "credit": 0.0,
                            "leverage": 500, "currency": "USD", "name": "n", "server": server},
                "deals": []}


sync_worker.Mt5Client, sync_worker.BridgeCtl = FakeClient, FakeBridge
BODY = lambda uid=42, **kw: {  # noqa: E731
    "init_data": init_data(uid), "language": "ar",
    "profile": {"nickname": "Ahmed", "avatar": "boy"},
    "mt5": {"login": kw.get("login", "51234567"), "password": "pw", "server": kw.get("server", "Exness-Real21")},
    "terms_accepted": kw.get("terms", True),
}
W = lambda upd, s="sekret": c.post("/api/telegram-webhook", json=upd, headers={"X-Telegram-Bot-Api-Secret-Token": s})  # noqa: E731

# ═════════ 1) الهوية ═════════
ok("توقيع مزوّر → 401", c.post("/api/status", json={"init_data": init_data(token="9:BAD")}).status_code == 401)
ok("initData منتهي → 401", c.post("/api/status", json={"init_data": init_data(age=999999)}).status_code == 401)

# ═════════ 2) الباقات العامة ═════════
reset()
add_package("a", sort_order=2, name_en="B")
add_package("b", sort_order=1, name_en="A")
add_package("c", active=False)
pk = c.get("/api/packages").json()["packages"]
ok("الباقات النشطة فقط ومرتبة", [p["id"] for p in pk] == ["b", "a"])

# ═════════ 3) /api/status ═════════
reset()
r = c.post("/api/status", json={"init_data": init_data()}).json()
ok("مستخدم جديد: none + اشتراك null + إعدادات عامة", r["status"] == "none" and r["subscription"] is None and r["settings"]["kill_switch"] is False)
add_user(42, status="approved", nickname="A", avatar="boy", language="ar", mt5_login="111", mt5_server="S",
         mt5_password="TOPSECRET", subscription=active_sub(3),
         live={"balance": 5.0, "updated_at": _now()}, report=None, sync={"state": "new", "next_due": 1})
r = c.post("/api/status", json={"init_data": init_data()}).json()
ok("اشتراك نشط ومتبقٍ 3 أيام", r["subscription"]["active"] and r["subscription"]["days_left"] == 3)
ok("كود إحالة يُنشأ ويثبت", len(r["referral_code"]) == 6 and c.post("/api/status", json={"init_data": init_data()}).json()["referral_code"] == r["referral_code"])
ok("report=null لا يكسر الرد", r["report"] is None and r["live"]["balance"] == 5.0)
ok("لا تسرّب كلمة المرور ولا أسرار المزامنة", "TOPSECRET" not in json.dumps(r) and "next_due" not in json.dumps(r))
add_user(43, status="approved", subscription={"expires_at": time.time() - 100, "status": "active"})
r = c.post("/api/status", json={"init_data": init_data(43)}).json()
ok("اشتراك منتهٍ: active=false و days_left=0", r["subscription"]["active"] is False and r["subscription"]["days_left"] == 0)

# ═════════ 4) /api/register ═════════
reset()
add_user(42, subscription=active_sub())
FakeClient.mode = "ok"
r = c.post("/api/register", json=BODY())
ok("نجاح: approved", r.status_code == 200 and r.json() == {"status": "approved"})
u = DB.store["users"]["42"]
ok("الحساب محفوظ ومقبول ويدخل قائمة المزامنة", u["status"] == "approved" and u["sync"]["state"] == "new" and u["mt5_login"] == "51234567")
ok("live.updated_at موجود فورًا", u["live"]["balance"] == 1000.0 and u["live"]["updated_at"] is not None)
ok("انتظار القفل محدود (45ث) في مسار التسجيل", FakeClient.seen["lock_wait"] == 45)
ok("إشعار القناة سليم الترميز (🟢)", any(m == "sendMessage" and "🟢" in p.get("text", "") and "ð" not in p.get("text", "") for m, p in CALLS))
r = c.post("/api/register", json=BODY())
ok("مسجّل مسبقًا → 409 approved", r.status_code == 409 and r.json()["detail"] == "approved")

reset(); add_user(42, subscription=active_sub())
DB.store["config"] = {"settings": {"kill_switch": True}}
r = c.post("/api/register", json=BODY())
ok("kill_switch → 503 registration_paused", r.status_code == 503 and r.json()["detail"] == "registration_paused")

reset(); add_user(42)
r = c.post("/api/register", json=BODY())
ok("بلا اشتراك → الربط مسموح (الشراء بعد الربط)", r.status_code == 200 and r.json() == {"status": "approved"})
reset(); add_user(42, subscription={"expires_at": time.time() - 5})
ok("اشتراك منتهٍ → الربط مسموح", c.post("/api/register", json=BODY()).status_code == 200)

reset(); add_user(42, subscription=active_sub())
DB.store["blacklist"] = {"51234567": {"reason": "x"}}
r = c.post("/api/register", json=BODY())
ok("قائمة سوداء → 403", r.status_code == 403 and r.json()["detail"] == "account_blacklisted")

reset(); add_user(42, subscription=active_sub()); add_user(7, status="approved", mt5_login="51234567")
r = c.post("/api/register", json=BODY())
ok("رقم الحساب لدى مستخدم آخر → 409", r.status_code == 409 and r.json()["detail"] == "account_already_linked")

reset(); add_user(42, subscription=active_sub())
DB.store["config"] = {"settings": {"registration_policy": "demo"}}
r = c.post("/api/register", json=BODY(server="Exness-Real21"))
ok("سياسة demo ترفض الحقيقي → 403", r.status_code == 403 and r.json()["detail"] == "account_type_not_allowed")
ok("سياسة demo تقبل التجريبي", c.post("/api/register", json=BODY(server="Exness-MT5Trial16")).status_code == 200)

reset(); add_user(42, subscription=active_sub())
DB.store["config"] = {"settings": {"leverage_max": 100}}
r = c.post("/api/register", json=BODY())
ok("رافعة 500 > الحد 100 → 403 leverage_not_allowed", r.status_code == 403 and r.json()["detail"] == "leverage_not_allowed")
ok("ولا يُحفظ الحساب", DB.store["users"]["42"].get("status") != "approved")

reset(); add_user(42, subscription=active_sub())
for code, want in ((-6, "cred"), (-2, "srv")):
    FakeClient.mode = sync_worker.Mt5Error(code, "x", "auth")
    r = c.post("/api/register", json=BODY())
    ok(f"فشل توثيق {code} → 422 {want}", r.status_code == 422 and r.json()["detail"] == want)
FakeClient.mode = sync_worker.Mt5Error(-6, "x", "auth")
ok("المحاولة الثالثة تُنفَّذ وتفشل (422)", c.post("/api/register", json=BODY()).status_code == 422)
r = c.post("/api/register", json=BODY())
ok("رابع محاولة فاشلة خلال ساعة → 429", r.status_code == 429 and r.json()["detail"] == "too_many_attempts")
DB.store["users"]["42"]["link_fails"] = [time.time() - 4000] * 3
FakeClient.mode = "ok"
ok("المحاولات القديمة (>ساعة) لا تُحتسب", c.post("/api/register", json=BODY()).status_code == 200)

reset(); add_user(42, subscription=active_sub())
FakeClient.mode = sync_worker.Mt5Error(-10004, "bridge down", "transient")
r = c.post("/api/register", json=BODY())
ok("عطل مؤقت → 503 verification_temporarily_unavailable", r.status_code == 503 and r.json()["detail"] == "verification_temporarily_unavailable")
ok("العطل المؤقت لا يُحتسب محاولة فاشلة", not DB.store["users"]["42"].get("link_fails"))
FakeClient.mode = "ok"
bad = BODY(); bad["mt5"]["login"] = "abc"
ok("رقم حساب غير صالح → 422 (تحقق النموذج)", c.post("/api/register", json=bad).status_code == 422)

# ═════════ 5) الدفع عبر NOWPayments ═════════
reset(); add_package("p1"); add_user(42)
payments.create_invoice = lambda **kw: {"id": "inv1", "invoice_url": "https://nowpayments.io/pay/inv1"}
r = c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1"})
ok("إنشاء فاتورة", r.status_code == 200 and r.json()["invoice_url"].endswith("inv1") and r.json()["order_id"].startswith("42-p1-"))
ok("سجل الدفع waiting", DB.store["payments"][r.json()["order_id"]]["status"] == "waiting")
ok("باقة غير موجودة → 404", c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "zzz"}).status_code == 404)
def _boom(**kw): raise payments.PaymentError("down")
payments.create_invoice = _boom
ok("مزوّد الدفع معطّل → 502", c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1"}).status_code == 502)


def np_post(payload, secret=NP_SECRET, sig=...):
    raw = json.dumps(payload).encode()
    ordered = json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":"))
    if sig is ...:  # التوقيع الصحيح؛ أي قيمة أخرى (مثل "") تُرسَل كما هي
        sig = hmac.new(secret.encode(), ordered.encode(), hashlib.sha512).hexdigest()
    return c.post("/api/payments/nowpayments-webhook", content=raw, headers={"x-nowpayments-sig": sig, "content-type": "application/json"})


order = next(iter(DB.store["payments"]))
ok("توقيع خاطئ → 401", np_post({"order_id": order, "payment_status": "finished"}, secret="wrong").status_code == 401)
ok("بلا توقيع → 401", np_post({"order_id": order, "payment_status": "finished"}, sig="").status_code == 401)
ok("الطلب المرفوض لم يفعّل شيئًا", not DB.store["users"]["42"].get("subscription") and DB.store["payments"][order]["status"] == "waiting")
CALLS.clear()
np_post({"order_id": order, "payment_status": "confirming"})
ok("حالة وسيطة تُسجَّل ولا تُفعّل الاشتراك", DB.store["payments"][order]["status"] == "confirming" and not DB.store["users"]["42"].get("subscription"))
np_post({"order_id": order, "payment_status": "finished"})
sub = DB.store["users"]["42"]["subscription"]
ok("الدفع المكتمل يفعّل الاشتراك 30 يومًا", sub["status"] == "active" and 29 < (sub["expires_at"] - time.time()) / 86400 <= 30)
ok("يصل المستخدم إشعار التفعيل", any(m == "sendMessage" and p.get("chat_id") == 42 and "تفعيل" in p["text"] for m, p in CALLS))
exp1 = sub["expires_at"]
np_post({"order_id": order, "payment_status": "finished"})
ok("تكرار الإشعار لا يمدّد مرتين (idempotent)", DB.store["users"]["42"]["subscription"]["expires_at"] == exp1)

# مكافأة الإحالة: مرة واحدة للمُحال وللمُحيل
reset(); add_package("p1"); add_user(1, subscription=active_sub(1)); add_user(2, referred_by="1")
DB.store["payments"] = {"o1": {"uid": 2, "package_id": "p1", "status": "waiting"}, "o2": {"uid": 2, "package_id": "p1", "status": "waiting"}}
np_post({"order_id": "o1", "payment_status": "finished"})
d2, d1 = DB.store["users"]["2"], DB.store["users"]["1"]
ok("المُحال: 30 + 7 أيام", 36.9 < (d2["subscription"]["expires_at"] - time.time()) / 86400 <= 37)
ok("المُحيل: +7 أيام", 7.9 < (d1["subscription"]["expires_at"] - time.time()) / 86400 <= 8.1)
before = d2["subscription"]["expires_at"]
np_post({"order_id": "o2", "payment_status": "finished"})
ok("المكافأة مرة واحدة فقط", d2["referral_reward_granted"] and DB.store["users"]["2"]["subscription"]["expires_at"] - before < 30 * 86400 + 5)

# ═════════ 6) الدفع بـ Telegram Stars ═════════
reset(); add_package("p1"); add_package("nostars", price_stars=None); add_user(42)
r = c.post("/api/payments/create-stars", json={"init_data": init_data(), "package_id": "p1"})
inv = [p for m, p in CALLS if m == "createInvoiceLink"][0]
ok("رابط فاتورة Stars", r.status_code == 200 and r.json()["invoice_link"].startswith("https://t.me/") and inv["currency"] == "XTR" and inv["prices"][0]["amount"] == 1500)
ok("باقة بلا سعر Stars → 400", c.post("/api/payments/create-stars", json={"init_data": init_data(), "package_id": "nostars"}).status_code == 400)
order = next(iter(DB.store["payments"]))
CALLS.clear()
W({"pre_checkout_query": {"id": "q1", "invoice_payload": order}})
ok("pre_checkout يُقبل لطلب معروف", CALLS[0][0] == "answerPreCheckoutQuery" and CALLS[0][1]["ok"] is True)
CALLS.clear()
W({"pre_checkout_query": {"id": "q2", "invoice_payload": "nope"}})
ok("pre_checkout يُرفض لطلب مجهول", CALLS[0][1]["ok"] is False and CALLS[0][1]["error_message"])
W({"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "successful_payment": {"invoice_payload": order, "telegram_payment_charge_id": "ch1"}}})
ok("الدفع بـ Stars يفعّل الاشتراك", DB.store["users"]["42"]["subscription"]["status"] == "active" and DB.store["payments"][order]["telegram_payment_charge_id"] == "ch1")
e1 = DB.store["users"]["42"]["subscription"]["expires_at"]
W({"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "successful_payment": {"invoice_payload": order}}})
ok("تكرار successful_payment لا يمدّد", DB.store["users"]["42"]["subscription"]["expires_at"] == e1)

# ═════════ 7) /start والـ webhook ═════════
reset(); CALLS.clear()
ok("webhook بسر خاطئ → 403", W({"message": {}}, s="bad").status_code == 403)
W({"message": {"chat": {"id": 9, "type": "private"}, "from": {"id": 9, "language_code": "ar"}, "text": "/start"}})
m, p = CALLS[-1]
ok("/start عربي: نص + زر Mini App", m == "sendMessage" and "عائلة" in p["text"] and p["reply_markup"]["inline_keyboard"][0][0]["web_app"]["url"] == "https://example.test")
CALLS.clear()
W({"message": {"chat": {"id": 9, "type": "private"}, "from": {"id": 9, "language_code": "en"}, "text": "/start ABC123"}})
ok("/start إنجليزي مع payload", "Welcome" in CALLS[-1][1]["text"])
main.get_logo_file_id = lambda: "FILEID"
CALLS.clear()
W({"message": {"chat": {"id": 9, "type": "private"}, "from": {"id": 9, "language_code": "ar"}, "text": "/start"}})
ok("مع الشعار المتحرك: sendAnimation", CALLS[-1][0] == "sendAnimation" and CALLS[-1][1]["animation"] == "FILEID")
main.get_logo_file_id = lambda: None
orig = main.handle_private_message
main.handle_private_message = lambda _m: (_ for _ in ()).throw(RuntimeError("boom"))
r = W({"message": {"chat": {"id": 9, "type": "private"}, "from": {"id": 9}, "text": "/start"}})
ok("انهيار المعالج لا يُرجع خطأ لتلجرام", r.status_code == 200 and r.json() == {"ok": True})
main.handle_private_message = orig

# ═════════ 8) ضبط webhook ═════════
WANT = "https://example.test/api/telegram-webhook"


def scripted(info, set_ok=True):
    calls = []

    def f(method, **p):
        calls.append((method, p))
        return {"ok": True, "result": info} if method == "getWebhookInfo" else {"ok": set_ok, "description": "err"}
    return f, calls


f, calls = scripted({"url": WANT}); main.tg = f
ok("webhook سليم: لا تغيير", main.ensure_webhook() == "ok" and [x[0] for x in calls] == ["getWebhookInfo"])
f, calls = scripted({"url": WANT, "allowed_updates": ["message", "callback_query"]}); main.tg = f
ok("allowed_updates بلا pre_checkout_query → يُعاد الضبط", main.ensure_webhook() == "reset" and "pre_checkout_query" in calls[-1][1]["allowed_updates"])
f, calls = scripted({"url": ""}); main.tg = f
res = main.ensure_webhook()
ok("webhook غائب → يُضبط بسر وكل الأنواع", res == "reset" and calls[-1][1]["secret_token"] == "sekret" and {"message", "callback_query", "pre_checkout_query"} <= set(calls[-1][1]["allowed_updates"]))
f, calls = scripted({"url": WANT, "last_error_date": int(time.time()) - 30, "last_error_message": "500"}); main.tg = f
ok("خطأ توصيل حديث → إعادة ضبط تحفظ Stars", main.ensure_webhook() == "reset" and "pre_checkout_query" in calls[-1][1]["allowed_updates"])
f, calls = scripted({"url": ""}, set_ok=False); main.tg = f
ok("تلجرام يرفض → failed دون انهيار", main.ensure_webhook() == "failed")
main.tg = fake_tg

# ═════════ 9) لوحة الأدمن ═════════
reset()
W({"message": {"chat": {"id": 1, "type": "private"}, "from": {"id": 1}, "text": "/admin"}})
ok("/admin من غير أدمن: لا رابط", not CALLS)
W({"message": {"chat": {"id": 555, "type": "private"}, "from": {"id": 555}, "text": "/admin"}})
txt = CALLS[-1][1]["text"]
token = txt.split("token=")[1].split("\n")[0].strip()
code = txt.split("<code>")[1].split("</code>")[0]
ok("/admin من أدمن: رابط ورمز", len(token) > 20 and len(code) == 6)
ok("رمز خاطئ → 401", c.post("/api/admin/verify", json={"token": token, "code": "000000"}).status_code == 401)
ok("بلا جلسة → 401", c.get("/api/admin/me").status_code == 401)
r = c.post("/api/admin/verify", json={"token": token, "code": code})
ok("دخول ناجح ويضع كوكي الجلسة", r.status_code == 200 and "aw_admin" in c.cookies)
ok("الجلسة تعمل (JWT بـ sub نصّي)", c.get("/api/admin/me").json()["admin_id"] == 555)
ok("الرمز أحادي الاستخدام", c.post("/api/admin/verify", json={"token": token, "code": code}).status_code == 401)

s = c.get("/api/admin/settings").json()
ok("الإعدادات الافتراضية", s["registration_policy"] == "both" and s["kill_switch"] is False)
s = c.put("/api/admin/settings", json={"kill_switch": True, "leverage_max": 200, "evil": 1}).json()
ok("تحديث الإعدادات يتجاهل المفاتيح الغريبة", s["kill_switch"] is True and s["leverage_max"] == 200 and "evil" not in s)
c.put("/api/admin/settings", json={"kill_switch": False})

pid = c.post("/api/admin/packages", json={"name_ar": "أ", "name_en": "A", "price_usd": 9.5, "duration_days": 7}).json()["id"]
ok("إنشاء باقة", DB.store["packages"][pid]["price_usd"] == 9.5)
ok("باقة ناقصة → 422", c.post("/api/admin/packages", json={"name_ar": "x"}).status_code == 422)
c.put(f"/api/admin/packages/{pid}", json={"active": False, "price_usd": 12})
ok("تعديل باقة", DB.store["packages"][pid]["active"] is False and DB.store["packages"][pid]["price_usd"] == 12)
ok("الباقة المعطّلة لا تظهر للعامة", all(p["id"] != pid for p in c.get("/api/packages").json()["packages"]))
c.delete(f"/api/admin/packages/{pid}")
ok("حذف باقة", pid not in DB.store["packages"])

add_user(10, status="approved", nickname="Sara", mt5_login="900", mt5_server="Exness-Real5", live={"leverage": 500}, created_at=_now())
add_user(11, status="approved", nickname="Omar", mt5_login="901", mt5_server="Exness-MT5Trial9", live={"leverage": 100}, created_at=_now(), referred_by="10")
ok("قائمة المستخدمين + فلتر نوع الحساب", c.get("/api/admin/users?account_type=demo").json()["total"] == 1)
ok("فلتر الرافعة", c.get("/api/admin/users?leverage_min=200").json()["users"][0]["nickname"] == "Sara")
ok("بحث بالاسم", c.get("/api/admin/users?search=omar").json()["total"] == 1)
ok("الإحالات", [r_["uid"] for r_ in c.get("/api/admin/referrals").json()["referrals"]] == ["11"])
c.cookies.clear()
ok("بعد الخروج لا وصول", c.get("/api/admin/users").status_code == 401)

# ═════════ 10) الإحالة عبر /start و/api/status لمستند بلا status ═════════
def start_msg(text, uid, lang="ar"):
    return {"message": {"chat": {"id": uid, "type": "private"}, "from": {"id": uid, "language_code": lang}, "text": text}}


reset()
add_user(1, referral_code="ABC123", status="approved")
add_user(2, referral_code="ZZZ999", status="approved")
W(start_msg("/start ABC123", 50))
ok("الإحالة تُلتقط عند /start مع payload", DB.store["users"]["50"]["referred_by"] == "1")
r = c.post("/api/status", json={"init_data": init_data(50)}).json()
ok("مستند أنشأته الإحالة فقط = مستخدم جديد (none) لا pending", r["status"] == "none")
W(start_msg("/start ZZZ999", 50))
ok("المُحيل الأول لا يُستبدل", DB.store["users"]["50"]["referred_by"] == "1")
W(start_msg("/start ABC123", 1))
ok("لا إحالة ذاتية", not DB.store["users"]["1"].get("referred_by"))
W(start_msg("/start ABC123", 2))
ok("مستخدم مسجّل لا يتأثر بروابط الإحالة", not DB.store["users"]["2"].get("referred_by"))
for bad in ("/start ??", "/start x", "/start ABC123;DROP", "/start " + "A" * 40):
    W(start_msg(bad, 60))
ok("payload غير صالح يُتجاهل", "60" not in DB.store["users"] or not DB.store["users"]["60"].get("referred_by"))
W(start_msg("/start NOSUCH1", 61))
ok("كود إحالة غير موجود يُتجاهل", "61" not in DB.store["users"] or not DB.store["users"]["61"].get("referred_by"))

main._BOT_USERNAME["v"] = "awbot"
add_user(70, status="approved", nickname="N", subscription=active_sub(10))
r = c.post("/api/status", json={"init_data": init_data(70)}).json()
ok("remaining_days و days_left متطابقان", r["subscription"]["remaining_days"] == r["subscription"]["days_left"] == 10)
ok("اسم البوت لرابط الدعوة", r["bot_username"] == "awbot")

# ═════════ 11) فكّ الربط ═════════
reset()
add_package("p1")
ok("فكّ ربط مجهول → 404", c.post("/api/unlink", json={"init_data": init_data(80)}).status_code == 404)
add_user(80, status="none")
ok("غير مربوط → 400", c.post("/api/unlink", json={"init_data": init_data(80)}).status_code == 400)

add_user(80, status="approved", mt5_login="9000", mt5_password="pw", mt5_server="Exness-Real5", subscription=active_sub(20),
         live={"balance": 1}, report={"win_rate": 50}, stats={"wins": 9, "cursor": 123}, sync={"state": "ok", "fails": 2, "next_due": 5})
CALLS.clear()
r = c.post("/api/unlink", json={"init_data": init_data(80)})
u = DB.store["users"]["80"]
ok("فكّ الربط ينجح", r.status_code == 200 and u["status"] == "unlinked")
ok("مسح بيانات الحساب والإحصاءات", all(u[k] is None for k in ("mt5_login", "mt5_password", "mt5_server", "live", "report", "stats", "sync")))
ok("الاشتراك يبقى كما هو", u["subscription"]["status"] == "active")
ok("إشعار الأدمن بفكّ الربط", any(m == "sendMessage" and "فكّ ربط" in p["text"] for m, p in CALLS))
r = c.post("/api/status", json={"init_data": init_data(80)}).json()
ok("الحالة بعد الفكّ: unlinked مع بقاء الاشتراك", r["status"] == "unlinked" and r["subscription"]["active"])
ok("فكّ ثانٍ مباشرة → 400 (لم يعد مربوطًا)", c.post("/api/unlink", json={"init_data": init_data(80)}).status_code == 400)

# ربط حساب آخر بعد الفكّ: لا تنتقل إحصاءات/فشل المزامنة القديمة
DB.store["users"]["80"]["stats"] = {"wins": 999}          # كأن المزامنة أعادت كتابتها أثناء الفكّ
DB.store["users"]["80"]["sync"] = {"state": "error", "fails": 3, "first_fail": 1, "next_due": 9e9}
FakeClient.mode = "ok"
ok("إعادة الربط بعد الفكّ تنجح", c.post("/api/register", json=BODY(80, login="777000")).status_code == 200)
u = DB.store["users"]["80"]
ok("الحساب الجديد يبدأ بإحصاءات ومزامنة نظيفة", u["stats"] is None and u["report"] is None and u["sync"]["fails"] == 0 and u["sync"]["next_due"] == 0 and u["sync"]["state"] == "new")
add_user(81, subscription=active_sub())
ok("والحساب القديم صار متاحًا لمستخدم آخر", c.post("/api/register", json=BODY(81, login="9000")).status_code == 200)

# فترة الانتظار 24 ساعة بين عمليتي فكّ
DB.store["users"]["80"]["last_unlink_at"] = time.time() - 3600
r = c.post("/api/unlink", json={"init_data": init_data(80)})
ok("فكّ خلال 24 ساعة → 429 cooldown_Nh", r.status_code == 429 and r.json()["detail"].startswith("cooldown_") and r.json()["detail"].endswith("h"))
DB.store["users"]["80"]["last_unlink_at"] = time.time() - 90000
ok("بعد مرور 24 ساعة يسمح", c.post("/api/unlink", json={"init_data": init_data(80)}).status_code == 200)

# ═════════ 12) الملف الشخصي ═════════
reset(); add_user(90, status="approved", language="ar", nickname="Old")
ok("تحديث اللغة", c.post("/api/profile", json={"init_data": init_data(90), "language": "en"}).status_code == 200 and DB.store["users"]["90"]["language"] == "en")
c.post("/api/profile", json={"init_data": init_data(90), "nickname": "New Name", "avatar": "girl"})
ok("تحديث الاسم والأفاتار", DB.store["users"]["90"]["nickname"] == "New Name" and DB.store["users"]["90"]["avatar"] == "girl")
ok("لغة غير صالحة → 422", c.post("/api/profile", json={"init_data": init_data(90), "language": "fr"}).status_code == 422)
ok("اسم قصير → 422", c.post("/api/profile", json={"init_data": init_data(90), "nickname": "x"}).status_code == 422)
ok("مستخدم مجهول → 404", c.post("/api/profile", json={"init_data": init_data(91), "language": "en"}).status_code == 404)

# ═════════ 13) الدفع عبر TON Connect ═════════
import ton  # noqa: E402
import rewards  # noqa: E402
import reminders  # noqa: E402
import heartbeat  # noqa: E402
import leaderboard  # noqa: E402
from collections import Counter  # noqa: E402

ok("BOC التعليق مطابق لمكتبة TON المرجعية", ton.comment_payload("42-p1-1700000000") == "te6cckEBAQEAFgAAKAAAAAA0Mi1wMS0xNzAwMDAwMDAw+rFG6w==")
reset(); add_package("p1"); add_user(42)
ton.usd_rate = lambda: 3.625  # 29$ ÷ 3.625 = 8 TON
ton.TON_WALLET = ""
ok("TON غير مهيأ → 503", c.post("/api/payments/create-ton", json={"init_data": init_data(), "package_id": "p1"}).status_code == 503)
ok("/api/packages يبلّغ ton_enabled", c.get("/api/packages").json()["ton_enabled"] is False)
ton.TON_WALLET = "UQ_PROJECT_WALLET"
r = c.post("/api/payments/create-ton", json={"init_data": init_data(), "package_id": "p1"})
tx = r.json()
ok("طلب TON: العنوان والمبلغ بالنانو والتعليق = order_id", r.status_code == 200 and tx["address"] == "UQ_PROJECT_WALLET" and tx["amount_nano"] == "8000000000" and tx["payload"] == ton.comment_payload(tx["order_id"]))
ok("/api/packages: سعر TON متغيّر من سعر السوق", c.get("/api/packages").json()["packages"][0]["price_ton"] == 8.0)
ton.usd_rate = lambda: None
ok("سعر TON غير متاح → 503", c.post("/api/payments/create-ton", json={"init_data": init_data(), "package_id": "p1"}).status_code == 503)
ton.usd_rate = lambda: 3.625
CHAIN = []
ton.fetch_transactions = lambda limit=100: list(CHAIN)
ok("لا معاملة على الشبكة → يبقى waiting", c.post("/api/payments/ton-check", json={"init_data": init_data(), "order_id": tx["order_id"]}).json()["status"] == "waiting")
CHAIN.append({"hash": "h1", "lt": 1, "utime": 1, "source": "EQ_USER", "value": 7_000_000_000, "comment": tx["order_id"]})
ok("مبلغ ناقص لا يفعّل", main.scan_ton_payments() == 0)
CHAIN.append({"hash": "h2", "lt": 2, "utime": 2, "source": "EQ_USER", "value": 8_000_000_000, "comment": tx["order_id"]})
ok("طلب مستخدم آخر → 404", c.post("/api/payments/ton-check", json={"init_data": init_data(7), "order_id": tx["order_id"]}).status_code == 404)
r = c.post("/api/payments/ton-check", json={"init_data": init_data(), "order_id": tx["order_id"]})
ok("معاملة مطابقة على الشبكة → يتفعّل الاشتراك", r.json()["status"] == "finished" and DB.store["users"]["42"]["subscription"]["status"] == "active" and DB.store["payments"][tx["order_id"]]["ton_tx_hash"] == "h2")
e1 = DB.store["users"]["42"]["subscription"]["expires_at"]
ok("فحص متكرر لا يمدّد مرتين", main.scan_ton_payments() == 0 and DB.store["users"]["42"]["subscription"]["expires_at"] == e1)
hist = c.get("/api/billing/history", params={"init_data": init_data()})
ok("سجل الفواتير يعرض TON ومعرّف المعاملة", hist.status_code == 200 and hist.json()["payments"][0]["currency"] == "TON" and hist.json()["payments"][0]["tx_id"] == "h2")
# نفس المعاملة لا تفعّل طلبًا ثانيًا
DB.store["payments"]["42-p1-2"] = {"uid": 42, "package_id": "p1", "method": "ton", "status": "waiting", "created_at": time.time(), "amount_nano": 1}
CHAIN.append({"hash": "h2", "lt": 2, "utime": 2, "source": "EQ_USER", "value": 8_000_000_000, "comment": "42-p1-2"})
ok("معاملة واحدة لا تفعّل طلبين", main.scan_ton_payments() == 0)
DB.store["payments"]["old"] = {"uid": 42, "package_id": "p1", "method": "ton", "status": "waiting", "created_at": time.time() - 99999, "amount_nano": 1}
main.scan_ton_payments()
ok("طلب TON قديم → expired", DB.store["payments"]["old"]["status"] == "expired")

ton.TON_WEBHOOK_SECRET = "tonsec"
ok("webhook TON بلا سر → 401", c.post("/api/payments/ton-webhook", json={}).status_code == 401)
reset(); add_package("p1"); add_user(42)
tx = c.post("/api/payments/create-ton", json={"init_data": init_data(), "package_id": "p1"}).json()
CHAIN[:] = [{"hash": "h9", "lt": 9, "utime": 9, "source": "EQ_U", "value": 8_000_000_000, "comment": tx["order_id"]}]
r = c.post("/api/payments/ton-webhook?secret=tonsec", json={"tx_hash": "ignored"})
inbox = list(DB.store["webhook_inbox"].values())
ok("webhook TON: يُحفظ في الصندوق ويُفعَّل في الخلفية بعد التحقق على الشبكة", r.status_code == 200 and inbox[0]["processed"] and DB.store["payments"][tx["order_id"]]["status"] == "finished")
ok("manifest TON Connect", c.get("/api/tonconnect-manifest.json").json()["url"] == "https://example.test")

# ═════════ 14) NOWPayments داخل التطبيق + صندوق الإشعارات وإعادة المحاولة ═════════
reset(); add_package("p1"); add_user(42)
payments.create_invoice = lambda **kw: {"id": "inv77", "invoice_url": "https://nowpayments.io/pay/inv77"}
r = c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1"}).json()
ok("بوابة مضمّنة: widget_url لـ iframe", r["widget_url"] == "https://nowpayments.io/embeds/payment-widget?iid=inv77")
orig = main.process_nowpayments
calls = {"n": 0}
def flaky(data):
    calls["n"] += 1
    raise RuntimeError("firestore down")
main.process_nowpayments = flaky
np_post({"order_id": r["order_id"], "payment_status": "finished"})
item_id, item = next(iter(DB.store["webhook_inbox"].items()))
ok("فشل مؤقت: الإشعار محفوظ غير معالَج مع إعادة محاولة tenacity (3)", not item["processed"] and item["attempts"] == 1 and calls["n"] == 3)
main.process_nowpayments = orig
item["received_at"] = time.time() - 120
main.retry_inbox()
ok("المهمة الدورية تعيد المعالجة وتفعّل الاشتراك", DB.store["webhook_inbox"][item_id]["processed"] and DB.store["users"]["42"]["subscription"]["status"] == "active")

import retry as retry_mod  # noqa: E402
n = {"i": 0}
@retry_mod.with_backoff(attempts=3, max_wait=0.01)
def unstable():
    n["i"] += 1
    if n["i"] < 3:
        raise retry_mod.RetryableError("503")
    return "ok"
ok("tenacity: تراجع أُسّي ثم نجاح", unstable() == "ok" and n["i"] == 3)

# ═════════ 15) الفترة التجريبية المشروطة ═════════
S = {**billing.DEFAULT_SETTINGS, "trial_enabled": True, "trial_days": 10, "trial_max_lot": 0.05}
f = billing.trial_fields_on_first_link(S, {}, {"currency": "USC"}, "Exness-Real", 1000.0)
ok("حساب سنت: تجربة مقيّدة بـ 3..7 أيام", f["trial"]["cent_account"] and f["trial_expires_at"] == 1000.0 + 7 * 86400)
ok("التجربة عند أول ربط فقط", billing.trial_fields_on_first_link(S, {"trial_checked": True}, {"currency": "USC"}, "x", 1) == {})
ok("معطّلة افتراضيًا", "trial" not in billing.trial_fields_on_first_link(billing.DEFAULT_SETTINGS, {}, {"currency": "USC"}, "x", 1))
f2 = billing.trial_fields_on_first_link(S, {}, {"currency": "USD"}, "Exness-Real", 1000.0)
u = {"trial_expires_at": f2["trial_expires_at"], "trial": f2["trial"]}
ok("حساب عادي: لوت ضمن الحد مسموح", billing.auto_trade_allowed(u, 0.05, now=2000) == (True, "trial_lot"))
ok("لوت أكبر من الحد مرفوض", billing.auto_trade_allowed(u, 0.1, now=2000) == (False, "lot_exceeds_trial_limit"))
ok("بعد انتهاء trial_expires_at مرفوض", billing.auto_trade_allowed(u, 0.01, now=f2["trial_expires_at"] + 1) == (False, "trial_expired"))
ok("الاشتراك الفعّال يسمح دائمًا", billing.auto_trade_allowed({"subscription": active_sub()}, 5)[0])
reset(); add_user(42)
DB.store["config"] = {"settings": {"trial_enabled": True}}
FakeClient.mode = "ok"
c.post("/api/register", json=BODY(server="Exness-MT5Cent"))
ok("الربط الأول يسجّل trial_expires_at", DB.store["users"]["42"].get("trial_expires_at", 0) > time.time() + 2 * 86400)

# ═════════ 16) تذكير التجديد ═════════
reset(); SENT = []
def rtg(method, **p):
    SENT.append(p)
    return {"ok": True}
NOW = time.time()
add_user(1, language="ar", subscription={"status": "active", "expires_at": NOW + 2.5 * 86400})
add_user(2, language="en", subscription={"status": "active", "expires_at": NOW + 20 * 3600})
add_user(3, subscription={"status": "active", "expires_at": NOW + 10 * 86400})
ok("يرسل قبل 3 أيام وقبل 24 ساعة فقط", reminders.run_renewal_reminders(DB, rtg, "https://example.test", NOW) == 2)
btn = SENT[0]["reply_markup"]["inline_keyboard"][0][0]
ok("زر تجديد الآن يفتح تدفق TON", btn["web_app"]["url"] == "https://example.test/?renew=ton")
ok("لا تكرار لنفس المرحلة", reminders.run_renewal_reminders(DB, rtg, "https://example.test", NOW + 60) == 0)
ok("المستخدم 1 يصله تذكير 24 ساعة لاحقًا", reminders.run_renewal_reminders(DB, rtg, "https://example.test", NOW + 1.8 * 86400) == 1)
DB.store["users"]["2"]["subscription"]["expires_at"] = NOW + 2 * 86400  # جدّد
ok("التجديد يعيد ضبط التذكيرات", reminders.run_renewal_reminders(DB, rtg, "https://example.test", NOW) == 1)

# ═════════ 17) Heartbeat ═════════
clock = {"t": 0.0}; up = {"v": True}; notes, events, restarts = [], [], []
hb = heartbeat.Heartbeat(notes.append, lambda k, d: events.append(k), probe=lambda: up["v"],
                         restart=lambda: restarts.append(1) or True, clock=lambda: clock["t"], alert_after=15, restart_cooldown=120)
hb.beat()
up["v"] = False
for t_ in (5, 10):
    clock["t"] = t_; hb.beat()
ok("انقطاع قصير (<15ث) بلا تنبيه", not notes and events == ["lost"])
clock["t"] = 20; hb.beat()
ok("بعد 15ث: تنبيه فوري + إعادة تشغيل + تسجيل", len(notes) == 1 and "🚨" in notes[0] and restarts == [1] and events == ["lost", "alert", "restart"])
clock["t"] = 25; hb.beat()
ok("لا تكرار للتنبيه ولا لإعادة التشغيل ضمن فترة التهدئة", len(notes) == 1 and restarts == [1])
ok("اللقطة: down مع المدة", hb.snapshot()["status"] == "down" and hb.snapshot()["down_for_sec"] == 20)
up["v"] = True; clock["t"] = 30; hb.beat()
ok("التعافي يُبلَّغ ويُسجَّل", "✅" in notes[-1] and events[-1] == "recovered" and hb.snapshot()["status"] == "up")

# ═════════ 18) Scratch & Win ═════════
rng = __import__("random").Random(7)
cnt = Counter(rewards.generate_scratch_prize(rng)["type"] for _ in range(100000))
ok("مصفوفة الاحتمالات 60/25/10/4/1 (توزيع مرجّح)", all(abs(cnt[k] / 1000 - w) < 0.8 for k, w in rewards.CATEGORY_WEIGHTS.items()))
ok("مجموع الأوزان 100", sum(w for w, _, _ in rewards.PRIZE_TABLE) == 100)
ok("الخصومات 10/20/50 فقط", {p_["value"] for p_ in (rewards.generate_scratch_prize(rng) for _ in range(3000)) if p_["type"] == "discount"} == {10, 20, 50})

reset(); add_user(42)
r = c.post("/api/onboarding/complete", json={"init_data": init_data()})
ok("إكمال التعريف يمنح بطاقة الترحيب", r.json()["card_id"] == "42_welcome" and DB.store["users"]["42"]["scratch_pending"] == ["42_welcome"])
ok("لا بطاقة مكررة لنفس الحدث", c.post("/api/onboarding/complete", json={"init_data": init_data()}).json()["card_id"] is None and len(DB.store["scratch_cards"]) == 1)
c.post("/api/register", json=BODY(server="Exness-MT5Trial16"))
ok("ربط حساب تجريبي بعد التعريف لا يمنح بطاقة ثانية", len(DB.store["scratch_cards"]) == 1)
ok("الحالة تُظهر عدد البطاقات", c.post("/api/status", json={"init_data": init_data()}).json()["scratch_pending"] == 1)

reset(); add_user(1, referral_code="REF1"); add_user(50, referred_by="1")
c.post("/api/register", json=BODY(50, login="5050"))
ok("إحالة ناجحة تمنح المُحيل بطاقة", "1_referral_50" in DB.store["scratch_cards"] and "referral_50" in DB.store["users"]["1"]["achievements"])

ok("سلسلة 7 أيام عمل (تتخطى العطلة)", rewards.streak_start(["2026-09-10", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]) == "2026-09-10")
ok("انقطاع يكسر السلسلة", rewards.streak_start(["2026-09-09", "2026-09-11", "2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]) is None)

reset(); add_user(42)
rewards.grant_card(DB, 42, "welcome")
r = c.post("/api/scratch/claim", json={"init_data": init_data()})
ok("بلا توثيق هاتف ولا Premium → 403", r.status_code == 403 and r.json()["detail"] == "phone_verification_required")
ok("لم تُولَّد أي جائزة لغير المؤهل", DB.store["scratch_cards"]["42_welcome"]["prize"] is None)
W({"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "contact": {"user_id": 42, "phone_number": "+964 770 000 1111"}}})
ok("مشاركة الرقم عبر البوت توثّق الحساب", DB.store["users"]["42"]["phone_verified"] is True)
add_user(43)
W({"message": {"chat": {"id": 43, "type": "private"}, "from": {"id": 43}, "contact": {"user_id": 43, "phone_number": "9647700001111"}}})
ok("نفس الرقم لحساب آخر مرفوض", DB.store["users"]["43"]["phone_verified"] is False)
W({"message": {"chat": {"id": 43, "type": "private"}, "from": {"id": 43}, "contact": {"user_id": 99, "phone_number": "111"}}})
ok("رقم شخص آخر (user_id مختلف) يُتجاهل", DB.store["users"]["43"]["phone_verified"] is False)

r = c.post("/api/scratch/claim", json={"init_data": init_data()}).json()
card = DB.store["scratch_cards"]["42_welcome"]
shown = json.loads(__import__("base64").urlsafe_b64decode(r["token"]))
ok("الجائزة تُولَّد وتُخزَّن على الخادم وتُرسل مختومة", card["prize"] and shown["type"] == card["prize"]["type"] and hmac.new(main.REWARD_SECRET.encode(), r["token"].encode(), hashlib.sha256).hexdigest() == r["sig"])
r2 = c.post("/api/scratch/claim", json={"init_data": init_data(), "card_id": "42_welcome"}).json()
ok("طلب متكرر يعيد نفس الجائزة (لا إعادة سحب)", r2["token"] == r["token"])
ok("Premium مؤهل بلا هاتف", c.post("/api/scratch/claim", json={"init_data": init_data(44, premium=True)}).json()["detail"] == "no_card")
ok("بطاقة مستخدم آخر → 404", c.post("/api/scratch/claim", json={"init_data": init_data(44, premium=True), "card_id": "42_welcome"}).status_code == 404)
card["prize"] = {"type": "discount", "value": 20}
rv = c.post("/api/scratch/reveal", json={"init_data": init_data(), "card_id": "42_welcome"}).json()
ok("الكشف: صلاحية بالساعات فقط", rv["status"] == "active" and abs(rv["expires_at"] - time.time() - rewards.REWARD_TTL_HOURS * 3600) < 5 and rewards.REWARD_TTL_HOURS <= 72)
ok("الكشف يزيل البطاقة من المعلّقة", DB.store["users"]["42"]["scratch_pending"] == [])
hub = c.get("/api/rewards", params={"init_data": init_data()}).json()
ok("محفظة المكافآت: النوع والقيمة والانتهاء والحالة", hub["rewards"][0]["type"] == "discount" and hub["rewards"][0]["value"] == 20 and hub["rewards"][0]["status"] == "active" and hub["cards"] == [])

add_package("p1"); ton.usd_rate = lambda: 2.9  # 29$ = 10 TON
payments.create_invoice = lambda **kw: CALLS.append(("np", kw)) or {"id": "inv5", "invoice_url": "https://np/inv5"}
r = c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1", "reward_id": "42_welcome"}).json()
npkw = [p for m, p in CALLS if m == "np"][-1]
ok("الخصم يُطبَّق تلقائيًا قبل إنشاء طلب NOWPayments (دولار صحيح بلا كسور)", npkw["amount_usd"] == 23 and DB.store["payments"][r["order_id"]]["price_full"] == 29.0)
ok("الجائزة لا تُعلَّم مستخدمة قبل نجاح الدفع", card.get("used") is False)
tx = c.post("/api/payments/create-ton", json={"init_data": init_data(), "package_id": "p1", "reward_id": "42_welcome"}).json()
ok("الخصم على TON Connect أيضًا", tx["amount_nano"] == "8000000000")
np_post({"order_id": r["order_id"], "payment_status": "finished"})
ok("بعد نجاح الدفع تُعلَّم مستخدمة", card["used"] is True and card["used_order"] == r["order_id"])
ok("جائزة مستخدمة ترفض → 409", c.post("/api/payments/create-stars", json={"init_data": init_data(), "package_id": "p1", "reward_id": "42_welcome"}).status_code == 409)

rewards.grant_card(DB, 42, "referral_77"); c.post("/api/scratch/claim", json={"init_data": init_data(), "card_id": "42_referral_77"})
DB.store["scratch_cards"]["42_referral_77"]["prize"] = {"type": "free_days", "value": 5}
c.post("/api/scratch/reveal", json={"init_data": init_data(), "card_id": "42_referral_77"})
DB.store["scratch_cards"]["42_referral_77"]["expires_at"] = time.time() - 1
r = c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1", "reward_id": "42_referral_77"})
ok("جائزة منتهية الصلاحية مرفوضة → 410", r.status_code == 410 and r.json()["detail"] == "reward_expired")
DB.store["scratch_cards"]["42_referral_77"]["expires_at"] = time.time() + 3600
before = DB.store["users"]["42"]["subscription"]["expires_at"]
r = c.post("/api/payments/create-stars", json={"init_data": init_data(), "package_id": "p1", "reward_id": "42_referral_77"}).json()
W({"message": {"chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "successful_payment": {"invoice_payload": next(k for k, v in DB.store["payments"].items() if v.get("method") == "stars"), "telegram_payment_charge_id": "c9"}}})
gain = (DB.store["users"]["42"]["subscription"]["expires_at"] - before) / 86400
ok("أيام مجانية تُضاف بعد نجاح الدفع (30 + 5)", 34.9 < gain < 35.1 and DB.store["scratch_cards"]["42_referral_77"]["used"])

rewards.grant_card(DB, 42, "streak7_2026-09-10"); c.post("/api/scratch/claim", json={"init_data": init_data(), "card_id": "42_streak7_2026-09-10"})
DB.store["scratch_cards"]["42_streak7_2026-09-10"]["prize"] = {"type": "free_month", "value": 30}
ok("شهر مجاني لا يُطبَّق على الدفع", c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1", "reward_id": "42_streak7_2026-09-10"}).status_code == 404)
c.post("/api/scratch/reveal", json={"init_data": init_data(), "card_id": "42_streak7_2026-09-10"})
before = DB.store["users"]["42"]["subscription"]["expires_at"]
ok("تفعيل الشهر المجاني مباشرة", c.post("/api/rewards/redeem", json={"init_data": init_data(), "reward_id": "42_streak7_2026-09-10"}).status_code == 200 and 29.9 < (DB.store["users"]["42"]["subscription"]["expires_at"] - before) / 86400 < 30.1)
ok("ولا يُفعَّل مرتين", c.post("/api/rewards/redeem", json={"init_data": init_data(), "reward_id": "42_streak7_2026-09-10"}).status_code == 409)

ok("حالة النظام: زمن استجابة عالٍ = degraded", main._timed_status(time.time() - 5)["status"] == "degraded" and main._timed_status(time.time())["status"] == "up")

# ═════════ 19) التحليلات والإحالة ═════════
reset(); add_user(1, referral_code="R1")
add_user(10, referred_by="1", trial_checked=True, referral_reward_granted=True)
add_user(11, referred_by="1", status="approved", trial_checked=True)
add_user(12, referred_by="1")
add_user(13, referred_by="2", trial_checked=True)
a = c.get("/api/analytics", params={"init_data": init_data(1)}).json()["referrals"]
ok("إحصاءات الإحالة: مدعوون/ناجحة/دفعوا/تحويل", a == {"invited": 3, "linked": 2, "paid": 1, "conversion_pct": 66.7})
ok("بلا إحالات: معدل التحويل None", c.get("/api/analytics", params={"init_data": init_data(99)}).json()["referrals"]["conversion_pct"] is None)

st = sync_worker.apply_deals(sync_worker.empty_stats(), [
    {"ticket": 1, "time": 1_758_000_000, "type": 0, "entry": 1, "profit": 10.0, "commission": -1.0, "swap": 0.0, "fee": 0.0},
    {"ticket": 2, "time": 1_758_000_500, "type": 1, "entry": 1, "profit": -4.0, "commission": 0.0, "swap": 0.0, "fee": 0.0},
    {"ticket": 3, "time": 1_758_090_000, "type": 0, "entry": 1, "profit": 7.5, "commission": 0.0, "swap": 0.0, "fee": 0.0},
], __import__("zoneinfo").ZoneInfo("UTC"), 1_758_100_000)
rep = sync_worker.build_report({"balance": 1000.0}, st)
ok("سلسلة الربح اليومي للرسوم", rep["series"] == [{"d": "2025-09-16", "pnl": 5.0}, {"d": "2025-09-17", "pnl": 7.5}])

# ═════════ 20) التحكم بالمكافآت من لوحة الأدمن ═════════
reset()
W({"message": {"chat": {"id": 555, "type": "private"}, "from": {"id": 555}, "text": "/admin"}})
txt = CALLS[-1][1]["text"]
c.post("/api/admin/verify", json={"token": txt.split("token=")[1].split("\n")[0].strip(), "code": txt.split("<code>")[1].split("</code>")[0]})
cfg = c.get("/api/admin/rewards/config").json()
ok("الإعدادات الافتراضية للمكافآت", cfg["enabled"] and cfg["ttl_hours"] == 24 and len(cfg["prizes"]) == len(rewards.PRIZE_TABLE))
ok("جدول بلا جائزة مفعّلة مرفوض", c.put("/api/admin/rewards/config", json={"prizes": [{"type": "discount", "value": 10, "weight": 0}]}).status_code == 422)
ok("نوع جائزة مجهول مرفوض", c.put("/api/admin/rewards/config", json={"prizes": [{"type": "cash", "value": 1, "weight": 1}]}).status_code == 422)
ok("صلاحية خارج 1..72 مرفوضة", c.put("/api/admin/rewards/config", json={"ttl_hours": 100}).status_code == 422)
r = c.put("/api/admin/rewards/config", json={"ttl_hours": 6, "require_phone": False, "triggers": {"welcome": False},
                                             "prizes": [{"type": "discount", "value": 35, "weight": 5}, {"type": "free_days", "value": 2, "weight": 0}]})
ok("حفظ إعدادات الأدمن", r.status_code == 200 and r.json()["ttl_hours"] == 6 and r.json()["triggers"] == {"welcome": False, "link_real": False, "referral": True, "streak7": True, "first_payment": True, "renewal": False})
add_user(42)
ok("محفز معطّل لا يمنح بطاقة", c.post("/api/onboarding/complete", json={"init_data": init_data()}).json()["card_id"] is None)
rewards.grant_card(DB, 42, "referral_9")
r = c.post("/api/scratch/claim", json={"init_data": init_data()}).json()
ok("بلا اشتراط الهاتف + الجدول المخصص يُستخدم", DB.store["scratch_cards"]["42_referral_9"]["prize"] == {"type": "discount", "value": 35})
rv = c.post("/api/scratch/reveal", json={"init_data": init_data(), "card_id": "42_referral_9"}).json()
ok("الصلاحية من إعدادات الأدمن (6 ساعات)", abs(rv["expires_at"] - time.time() - 6 * 3600) < 5)
r = c.post("/api/admin/rewards/grant", json={"uid": "42", "type": "discount", "value": 15, "hours": 3})
cid = r.json()["card_id"]
ok("كوبون يدوي جاهز للاستخدام + إشعار", DB.store["scratch_cards"][cid]["status"] == "revealed" and DB.store["scratch_cards"][cid]["prize"] == {"type": "discount", "value": 15} and any(p.get("chat_id") == "42" for m, p in CALLS if m == "sendMessage"))
ok("بطاقة خدش يدوية حتى مع محفز معطّل", c.post("/api/admin/rewards/grant", json={"uid": "42", "notify": False}).json()["card_id"].startswith("42_admin_"))
ok("كوبون بلا قيمة مرفوض", c.post("/api/admin/rewards/grant", json={"uid": "42", "type": "discount"}).status_code == 422)
before = DB.store["scratch_cards"][cid]["expires_at"]
c.post(f"/api/admin/rewards/{cid}/extend", json={"hours": 24})
ok("تمديد صلاحية كوبون", abs(DB.store["scratch_cards"][cid]["expires_at"] - before - 24 * 3600) < 2)
lst = c.get("/api/admin/rewards/cards", params={"uid": "42"}).json()
ok("قائمة البطاقات والإحصاءات", lst["stats"]["total"] == 3 and lst["stats"]["active"] == 2 and lst["stats"]["new"] == 1)
c.post(f"/api/admin/rewards/{cid}/revoke"); add_package("p1")
ok("إلغاء كوبون يمنع استخدامه", c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1", "reward_id": cid}).status_code == 409)
c.put("/api/admin/rewards/config", json={"enabled": False})
ok("تعطيل النظام كليًا", c.post("/api/scratch/claim", json={"init_data": init_data()}).json()["detail"] == "rewards_disabled")
c.post("/api/admin/logout")
ok("مسارات المكافآت تتطلب جلسة أدمن", c.get("/api/admin/rewards/config").status_code == 401)

# ═════════ 21) حالة جسر المراقبة حين يكون منفذه مغلقًا ═════════
units = {}
main._unit_state = lambda u: units.get(u, "unknown")
units.update({"mt5-monitor-bridge": "inactive", "aw-sync": "active"})
ok("جسر مطفأ عمدًا وaw-sync يعمل = idle لا down", main._monitor_bridge_when_closed("refused")["status"] == "idle")
units["aw-sync"] = "inactive"
ok("aw-sync متوقف = down مع السبب", "aw-sync" in main._monitor_bridge_when_closed("refused")["error"])
units.update({"mt5-monitor-bridge": "failed", "aw-sync": "active"})
ok("خدمة الجسر failed = down", main._monitor_bridge_when_closed("refused")["status"] == "down")
units["mt5-monitor-bridge"] = "activating"
ok("قيد التشغيل = degraded", main._monitor_bridge_when_closed("refused")["status"] == "degraded")

# ═════════ 22) الموافقة على Terms & Risks ═════════
reset(); add_user(42)
r = c.post("/api/register", json=BODY(terms=False))
ok("الربط بلا موافقة على الشروط → 400 terms_required", r.status_code == 400 and r.json()["detail"] == "terms_required")
c.post("/api/register", json=BODY())
ok("الموافقة تُحفظ بنسختها ووقتها", DB.store["users"]["42"]["terms"]["version"] == main.TERMS_VERSION)

# ═════════ 23) الباقات بالمزايا + البوابة المخصّصة للعملات الرقمية ═════════
reset()
W({"message": {"chat": {"id": 555, "type": "private"}, "from": {"id": 555}, "text": "/admin"}})
txt = CALLS[-1][1]["text"]
c.post("/api/admin/verify", json={"token": txt.split("token=")[1].split("\n")[0].strip(), "code": txt.split("<code>")[1].split("</code>")[0]})
ok("استيراد الباقات المقترحة", len(c.post("/api/admin/packages/seed").json()["created"]) == 3)
ok("الاستيراد لا يكرر", c.post("/api/admin/packages/seed").json()["created"] == [])
pk = {p["name_en"]: p for p in c.get("/api/packages").json()["packages"]}
ok("مزايا وبيانات الباقة", pk["AW Pro"]["price_usd"] == 129 and pk["AW Pro"]["featured"] and "نماذج تشغيل متعددة" in pk["AW Pro"]["features_ar"] and pk["AW Premium"]["duration_days"] == 90)
pid = pk["AW Starter"]["id"]
c.put(f"/api/admin/packages/{pid}", json={"features_ar": "ميزة 1\nميزة 2\n", "tagline_ar": "جديد"})
ok("تعديل المزايا من لوحة الأدمن (سطر لكل ميزة)", DB.store["packages"][pid]["features_ar"] == ["ميزة 1", "ميزة 2"])
c.post("/api/admin/logout")

add_user(42)
seen = {}
def fake_direct(**kw):
    seen.update(kw)
    return {"payment_id": 777, "pay_address": "TXYZ", "pay_amount": 19.2, "pay_currency": kw["pay_currency"], "payin_extra_id": None}
payments.create_direct_payment = fake_direct
r = c.post("/api/payments/create", json={"init_data": init_data(), "package_id": pid, "pay_currency": "usdttrc20"}).json()
ok("بوابة مخصّصة: عنوان ومبلغ وشبكة", r["pay_address"] == "TXYZ" and r["pay_amount"] == 19.2 and r["network"] == "TRON (TRC20)" and seen["amount_usd"] == 19)
order = r["order_id"]
payments.get_payment = lambda pid_: {"payment_status": "confirming"}
ok("حالة الدفع من NOWPayments", c.post("/api/payments/status", json={"init_data": init_data(), "order_id": order}).json()["status"] == "confirming")
ok("حالة طلب مستخدم آخر → 404", c.post("/api/payments/status", json={"init_data": init_data(7), "order_id": order}).status_code == 404)
DB.store["payments"][order]["np_checked_at"] = 0
payments.get_payment = lambda pid_: {"payment_status": "finished"}
ok("اكتمال الدفع يفعّل الاشتراك", c.post("/api/payments/status", json={"init_data": init_data(), "order_id": order}).json()["status"] == "finished" and DB.store["users"]["42"]["subscription"]["status"] == "active")
def too_low(**kw): raise payments.PaymentError("amount_too_low")
payments.create_direct_payment = too_low
ok("مبلغ أقل من الحد الأدنى للعملة → 400 amount_too_low", c.post("/api/payments/create", json={"init_data": init_data(), "package_id": pid, "pay_currency": "btc"}).json()["detail"] == "amount_too_low")
ok("قائمة العملات", any(x["code"] == "usdttrc20" for x in c.get("/api/payments/currencies").json()["currencies"]))

# ═════════ 24) مشاركة القصص والمنشورات ═════════
import base64 as _b64  # noqa: E402
main.MEDIA_DIR = tempfile.mkdtemp()
main._BOT_USERNAME["v"] = "awbot"
reset(); add_user(42, referral_code="ABC123")
JPG = _b64.b64encode(b"\xff\xd8\xff\xe0" + b"0" * 200).decode()
r = c.post("/api/share/create", json={"init_data": init_data(), "story": JPG, "post": JPG, "caption": "ربحت <b>+12%</b>\nانضم"}).json()
ok("رفع القصة والمنشور يعيد روابط عامة", r["story_url"].startswith("https://example.test/api/share/img/") and r["page_url"].endswith(r["id"]))
img = c.get(r["story_url"].replace("https://example.test", ""))
ok("الصورة متاحة للعامة (لـ Telegram Stories)", img.status_code == 200 and img.headers["content-type"] == "image/jpeg")
page = c.get(r["page_url"].replace("https://example.test", "")).text
ok("صفحة المنشور بوسوم Open Graph ووصف آمن", 'og:image" content="https://example.test/api/share/img/' in page and "&lt;b&gt;" in page and "<b>+12%" not in page and "t.me/awbot?start=ABC123" in page)
ok("ليست JPEG → 422", c.post("/api/share/create", json={"init_data": init_data(), "story": _b64.b64encode(b"GIF89a").decode(), "post": JPG}).status_code == 422)
ok("مسار صورة غير صالح → 404", c.get("/api/share/img/..%2Fmain.py").status_code == 404)
DB.store["users"]["42"]["share_quota"] = {time.strftime("%Y-%m-%d", time.gmtime()): 30}
ok("حد يومي للمشاركات", c.post("/api/share/create", json={"init_data": init_data(), "story": JPG, "post": JPG}).status_code == 429)

# ═════════ 25) ترتيب الأسبوع (بالدولار) ═════════
reset()
add_user(42, status="approved", nickname="Ahmed Ali", avatar="boy", report={"weekly_pnl": 1250.5}, live={"currency": "USD"})
add_user(43, status="approved", nickname="Sara", report={"weekly_pnl": 300000.0}, live={"currency": "USC"})  # سنت → 3000$
add_user(44, status="approved", nickname="NoData")
DB.store["config"] = {"leaderboard": {"enabled": False}}
lb = c.get("/api/leaderboard", params={"init_data": init_data()}).json()
ok("حقيقي فقط بالدولار (حساب السنت ÷100)", [(r["name"], r["usd"]) for r in lb["rows"]] == [("Sara", 3000.0), ("Ahmed", 1250.5)] and lb["me"]["rank"] == 2)
DB.store["config"] = {"leaderboard": {"enabled": True, "count": 12, "elite_count": 3}}
lb = c.get("/api/leaderboard", params={"init_data": init_data()}).json()
sims = [r for r in lb["rows"] if r["simulated"]]
ok("النخبة فوق 250 ألف دولار وتتصدر", len(sims) == 12 and all(r["usd"] >= 250000 for r in lb["rows"][:3]) and all(r["simulated"] for r in lb["rows"][:3]))
ok("ترتيب المستخدم محسوب بين الجميع", lb["me"]["rank"] == 1 + sum(1 for r in lb["rows"] if r["usd"] > 1250.5))
cfg = leaderboard.get_config(DB)
first = [(r["name"], r["usd"]) for r in lb["rows"]]
DB.store.pop("leaderboard", None)  # حتى لو أُعيد حساب كل شيء من الصفر: نفس القيم (حتمية)
ok("البيانات ثابتة: لا تتغير عشوائيًا مع كل تحديث", [(r["name"], r["usd"]) for r in c.get("/api/leaderboard", params={"init_data": init_data()}).json()["rows"]] == first)
before = {b["id"]: b["usd"] for b in DB.store["leaderboard"]["sim"]["bots"]}
leaderboard.tick(DB, cfg, rng=__import__("random").Random(3))
ok("لا حركة قبل الفاصل الزمني الذي يحدده الأدمن", before == {b["id"]: b["usd"] for b in DB.store["leaderboard"]["sim"]["bots"]})
leaderboard.tick(DB, cfg, rng=__import__("random").Random(3), force=True)
moved = DB.store["leaderboard"]["sim"]["bots"]
ok("المحاكاة الديناميكية: الأرباح تتحرك", before != {b["id"]: b["usd"] for b in moved})
ok("الحركة ضمن نطاق التذبذب حول القيمة الأساسية", all(b["base"] * 0.88 - 0.01 <= b["usd"] <= b["base"] * 1.12 + 0.01 for b in moved))
ok("أسماء وصور من الإعدادات", moved[0]["name"] == cfg["profiles"][0]["name"])

W({"message": {"chat": {"id": 555, "type": "private"}, "from": {"id": 555}, "text": "/admin"}})
txt = CALLS[-1][1]["text"]
c.post("/api/admin/verify", json={"token": txt.split("token=")[1].split("\n")[0].strip(), "code": txt.split("<code>")[1].split("</code>")[0]})
g = c.get("/api/admin/leaderboard").json()
ok("الأدمن: استيراد الأسماء الحالية", len(g["default_profiles"]) == 20 and g["profiles"][0]["name"])
r = c.put("/api/admin/leaderboard", json={"count": 2, "elite_count": 1, "elite_min": 400000, "elite_max": 500000,
                                          "profiles": [{"name": "Nour", "avatar": "girl", "tier": "master"}, {"name": "Ali", "avatar": "boy"}]})
ok("الأدمن: حفظ الأسماء والنطاقات", r.status_code == 200 and [p_["name"] for p_ in r.json()["profiles"]] == ["Nour", "Ali"])
ok("نطاق غير منطقي مرفوض", c.put("/api/admin/leaderboard", json={"base_min": 9, "base_max": 1}).status_code == 422)
lb = c.get("/api/leaderboard", params={"init_data": init_data()}).json()
sims = [r for r in lb["rows"] if r["simulated"]]
ok("تغيير الإعدادات يطبَّق فورًا", sorted(r["name"] for r in sims) == ["Ali", "Nour"] and max(r["usd"] for r in sims) >= 400000)
r = c.put("/api/admin/leaderboard", json={"mode": "group", "group_size": 4, "profiles": [
    {"name": "A1", "base_usd": 5000}, {"name": "A2", "base_usd": 900}, {"name": "A3", "base_usd": 100, "photo": "https://example.test/api/media/avatars/lb_x.webp"}, {"name": "A4", "base_usd": 50}]})
lb = c.get("/api/leaderboard", params={"init_data": init_data()}).json()
ok("المجموعة المغلقة: العدد ثابت ويشمل المستخدم الحقيقي", len(lb["rows"]) == 4 and sum(r["you"] for r in lb["rows"]) == 1 and lb["mode"] == "group")
ok("المستخدم الحقيقي مرتب بين الأسماء بنفس المنطق", [r["name"] for r in lb["rows"]] == ["A1", "Ahmed", "A2", "A3"] and lb["me"]["rank"] == 2)
ok("القيمة الأساسية المؤكَّدة تُعرض كما هي + الصورة لكل إدخال", [r["usd"] for r in lb["rows"] if r["simulated"]] == [5000, 900, 100] and lb["rows"][3]["photo"].endswith(".webp"))
ok("المستخدمون الحقيقيون الآخرون خارج المجموعة", all(r["name"] != "Sara" for r in lb["rows"]))
c.put("/api/admin/leaderboard", json={"mode": "open"})
c.post("/api/admin/logout")

# ═════════ 26) صفحة "انشر الآن" لكل منصة ═════════
reset(); add_user(42, referral_code="ABC123")
r = c.post("/api/share/create", json={"init_data": init_data(), "story": JPG, "post": JPG, "caption": "عام",
                                      "captions": {"instagram": "IG <script>x</script> #AWRobot", "facebook": "FB نص", "evil": "x"}}).json()
path = r["page_url"].replace("https://example.test", "")
ig = c.get(path, params={"to": "instagram"}).text
ok("صفحة إنستغرام: صورة القصة + نص المنصة + زر نشر", "_story.jpg" in ig and "IG <\\/script>" not in ig and "#AWRobot" in ig and "navigator.share" in ig and 'id="go"' in ig)
ok("النص داخل JS مؤمّن من </script>", "<\\/script>" in ig and "<script>x</script>" not in ig)
fb = c.get(path, params={"to": "facebook", "lang": "en"}).text
ok("صفحة فيسبوك: صورة المنشور + رابط sharer احتياطي", "_post.jpg" in fb and "facebook.com/sharer" in fb and "Post to Facebook now" in fb)
ok("منصة غير معروفة → صفحة المعاينة", "og:image" in c.get(path, params={"to": "evil"}).text)
ok("لا تُخزَّن منصات غير معروفة", "evil" not in DB.store["shares"][r["id"]]["captions"])

# ═════════ 27) اقتراح خوادم MT5 ═════════
import servers  # noqa: E402
reset(); add_user(42); servers._CACHE["rows"] = None
c.post("/api/register", json=BODY(server="Exness-MT5Trial16"))
ok("الربط الناجح يسجّل الخادم موثّقًا", DB.store["mt5_servers"]["exnessmt5trial16"]["verified"] and DB.store["mt5_servers"]["exnessmt5trial16"]["type"] == "demo")
servers.upsert(DB, "Dukascopy-Demo-MT5", source="import"); servers.upsert(DB, "ICMarketsSC-MT5-2", stype="real")
r = c.get("/api/servers", params={"q": "dukascopy-demo-mt5-1"}).json()["servers"]
ok("خطأ في الكتابة → اقتراح الاسم الصحيح", r and r[0]["name"] == "Dukascopy-Demo-MT5" and r[0]["type"] == "demo")
r = c.get("/api/servers", params={"q": "exness mt5 trial"}).json()["servers"]
ok("تجاهل المسافات والشرطات + الموثّق أولًا", r[0]["name"] == "Exness-MT5Trial16" and r[0]["verified"])
ok("مطابقة تامة معلّمة exact", c.get("/api/servers", params={"q": "icmarketssc-mt5-2"}).json()["servers"][0]["exact"])
ok("parse CSV", servers.parse_import("name,type\nAlpari-MT5-Demo,demo\nFoo-Live , live\n") == [("Alpari-MT5-Demo", "demo"), ("Foo-Live", "real")])

# ═════════ 28) الصور: بروفايل المستخدم ومنافسو الترتيب ═════════
main.AVATAR_DIR = tempfile.mkdtemp()
reset(); add_user(42, status="approved", nickname="Ahmed", report={"weekly_pnl": 10.0})
r = c.post("/api/profile/photo", json={"init_data": init_data(), "photo": JPG}).json()
ok("رفع الصورة الشخصية وتظهر في الحالة", r["photo_url"].startswith("https://example.test/api/media/avatars/u42_") and c.post("/api/status", json={"init_data": init_data()}).json()["photo_url"] == r["photo_url"])
ok("الصورة متاحة للعرض", c.get(r["photo_url"].replace("https://example.test", "")).status_code == 200)
ok("ليست JPEG → 422", c.post("/api/profile/photo", json={"init_data": init_data(), "photo": _b64.b64encode(b"<svg>").decode()}).status_code == 422)
ok("حذف الصورة", c.post("/api/profile/photo", json={"init_data": init_data(), "photo": ""}).json()["photo_url"] is None)
clean = leaderboard.clean_config({"profiles": [{"name": "A", "photo": "https://example.test/api/media/avatars/lb_x.jpg"}, {"name": "B", "photo": "javascript:alert(1)"}]})
ok("صور المنافسين: روابط https فقط", clean["profiles"][0]["photo"].startswith("https://") and clean["profiles"][1]["photo"] is None)

# ═════════ 29) فريق العمل والصلاحيات وسجل العمليات ولوحة CEO ═════════
import admin_access  # noqa: E402
def admin_login(uid, ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 Safari/604.1"):
    c.cookies.clear()
    W({"message": {"chat": {"id": uid, "type": "private"}, "from": {"id": uid}, "text": "/admin"}})
    txt_ = CALLS[-1][1]["text"]
    return c.post("/api/admin/verify", json={"token": txt_.split("token=")[1].split("\n")[0].strip(), "code": txt_.split("<code>")[1].split("</code>")[0]},
                  headers={"User-Agent": ua, "X-Forwarded-For": "203.0.113.7, 10.0.0.1"})
reset(); admin_access.invalidate()
admin_login(555)
ok("المالك يرى صلاحياته", c.get("/api/admin/me").json()["role"] == "owner")
ok("المالك يضيف عضو دعم", c.put("/api/admin/staff", json={"id": "7777", "role": "support", "name": "Mona"},
                                 headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile", "X-Forwarded-For": "203.0.113.7"}).status_code == 200)
log_ = c.get("/api/admin/audit").json()["rows"]
ok("سجل العمليات: الفعل + IP + الجهاز", log_[0]["action"] == "إضافة/تعديل عضو فريق" and log_[0]["ip"] == "203.0.113.7" and log_[0]["device"]["os"] == "iOS" and '"name": "Mona"' in log_[0]["body"])
ok("تسجيل الدخول مسجّل", any(x["action"] == "تسجيل دخول" for x in log_))
c.put("/api/admin/settings", json={"kill_switch": True})
ok("كل تعديل يُسجَّل", c.get("/api/admin/audit").json()["rows"][0]["action"] == "تعديل الإعدادات العامة")

CALLS.clear(); admin_login(7777, ua="Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 Chrome/126 Mobile Safari/537.36")
me = c.get("/api/admin/me").json()
ok("عضو الدعم يدخل بدوره", me["role"] == "support" and me["name"] == "Mona")
ok("الدعم لا يعدّل الإعدادات", c.put("/api/admin/settings", json={"kill_switch": False}).status_code == 403)
ok("الدعم لا يدير الفريق", c.get("/api/admin/staff").status_code == 403)
ok("الدعم يرى CEO", c.get("/api/admin/ceo").status_code == 200)
admin_login(555)
ok("الجهاز والطراز من User-Agent", admin_access.parse_device("Mozilla/5.0 (Linux; Android 14; SM-S918B) Chrome/126 Mobile")["model"] == "SM-S918B")
ok("إخفاء القيم الحساسة في السجل", "•••" in admin_access.summarize_body(b'{"code":"123456","photo":"abc"}'))
c.delete("/api/admin/staff/7777")
ok("إزالة العضو تمنع دخوله", admin_access.role_of(DB, main.ADMIN_IDS, 7777) is None)

reset(); admin_login(555)
now_ = time.time()
add_user(1, status="approved", subscription={"expires_at": now_ + 86400}); add_user(2, status="approved", referred_by="1"); add_user(3)
add_package("p1")
DB.store["payments"] = {"a": {"uid": 1, "package_id": "p1", "status": "finished", "amount_usd": 29.0, "method": "nowpayments", "confirmed_at": now_},
                        "b": {"uid": 1, "package_id": "p1", "status": "finished", "amount_ton": 10, "ton_rate_usd": 3.0, "method": "ton", "confirmed_at": now_},
                        "c": {"uid": 2, "package_id": "p1", "status": "waiting", "amount_usd": 29.0}}
ceo = c.get("/api/admin/ceo").json()
ok("CEO: المستخدمون والاشتراكات", ceo["users"]["total"] == 3 and ceo["users"]["linked"] == 2 and ceo["subscriptions"]["active"] == 1 and ceo["subscriptions"]["conversion_pct"] == 50.0)
ok("CEO: الإيرادات بالدولار (TON × سعره)", ceo["revenue"]["total_usd"] == 59.0 and ceo["revenue"]["orders"] == 2 and ceo["by_method"] == {"nowpayments": 1, "ton": 1})
ok("CEO: منحنى 30 يومًا", len(ceo["series"]) == 30 and ceo["series"][-1]["revenue"] == 59.0)
c.post("/api/admin/logout")

# ═════════ 30) الإشعارات (🔔): تلقائية + بث من الأدمن ═════════
import notifications  # noqa: E402
reset(); admin_access.invalidate()
add_user(42, status="approved", language="ar", subscription={"expires_at": time.time() + 86400}, live={"balance": 50.0})
add_user(43, status="approved", language="en", live={"balance": 5000.0}, phone_prefix="9665")
add_user(44, status="none", language="ar")
notifications.push(DB, 42, "deposit", "إيداع", "Deposit", "+100", "+100")
n = c.get("/api/notifications", params={"init_data": init_data()}).json()
ok("إشعار وارد تلقائي محفوظ كسجل", n["unread"] == 1 and n["items"][0]["kind"] == "deposit")
admin_login(555)
ok("معاينة عدد المستلمين بالفلتر", c.post("/api/admin/notifications/preview", json={"target": "filter", "filter": {"low_balance": 100}}).json()["count"] == 1)
ok("فلتر الدولة (رمز الهاتف)", c.post("/api/admin/notifications/preview", json={"target": "filter", "filter": {"phone_prefix": "+966"}}).json()["count"] == 1)
r = c.post("/api/admin/notifications/broadcast", json={"target": "filter", "filter": {"active": True}, "title_ar": "عرض", "title_en": "Offer", "body_ar": "خصم", "via_bot": True})
ok("بث لمجموعة بفلتر (النشطين)", r.status_code == 200 and r.json()["count"] == 1)
c.post("/api/admin/notifications/broadcast", json={"target": "all", "title_ar": "للجميع"})
c.post("/api/admin/notifications/broadcast", json={"target": "user", "uid": "43", "title_ar": "خاص"})
n42 = c.get("/api/notifications", params={"init_data": init_data()}).json()
n43 = c.get("/api/notifications", params={"init_data": init_data(43)}).json()
ok("كل مستخدم يرى ما يخصه فقط", {x["title_ar"] for x in n42["items"]} == {"إيداع", "عرض", "للجميع"} and {x["title_ar"] for x in n43["items"]} == {"للجميع", "خاص"})
c.post("/api/notifications/read", json={"init_data": init_data()})
ok("تعليم الكل كمقروء", c.get("/api/notifications", params={"init_data": init_data()}).json()["unread"] == 0)
ok("سجل البث في اللوحة", len(c.get("/api/admin/notifications/broadcasts").json()["rows"]) == 3)

# ═════════ 31) نافذة "ما الجديد" ═════════
import announcements  # noqa: E402
announcements.seed_default(DB)
a = c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"]
ok("نافذة الإطلاق الافتراضية تظهر عند الدخول", a and a["id"] == "launch" and len(a["features"]) == 5)
c.post("/api/announcements/seen", json={"init_data": init_data(), "id": "launch"})
ok("مرة واحدة فقط (once)", c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"] is None)
c.put("/api/admin/announcements/launch", json={"frequency": "every_open"})
ok("كل دخول (every_open)", c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"] is not None)
c.post("/api/announcements/seen", json={"init_data": init_data(), "id": "launch", "dismiss": True})
ok("لا تظهر مرة أخرى", c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"] is None)
c.put("/api/admin/announcements/launch", json={"reset_views": True, "audience": "expired"})
ok("الجمهور: منتهية اشتراكاتهم فقط", c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"] is None)
c.put("/api/admin/announcements/launch", json={"audience": "all", "frequency": "daily", "starts_at": time.time() + 3600})
ok("تاريخ بداية العرض", c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"] is None)
c.put("/api/admin/announcements/launch", json={"starts_at": 0})
ok("إعادة العرض للجميع بعد reset_views", c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"]["id"] == "launch")
ok("إيقاف كامل (On/Off)", c.put("/api/admin/announcements/launch", json={"enabled": False}).status_code == 200 and c.get("/api/announcements", params={"init_data": init_data()}).json()["announcement"] is None)
ok("تحقق من المدخلات", c.put("/api/admin/announcements/launch", json={"frequency": "hourly"}).status_code == 422)

# ═════════ 32) سجل الأخطاء + الدعم الذكي (مركز الدعم داخل التطبيق) ═════════
er = c.post("/api/errors", json={"init_data": init_data(), "kind": "operation", "code": "ton_payment_failed", "message": "TON payment failed", "page": "plans", "online": True}).json()
ok("الخطأ يُسجَّل برقم مرجعي + أولوية تلقائية", er["ref"].startswith("ERR-") and er["priority"] == "critical")
ok("خطأ بلا هوية (انقطاع/قبل الدخول) يُقبل", c.post("/api/errors", json={"kind": "network", "code": "timeout"}).json()["ref"])
main._ERR_RL.clear()
ok("حد تقارير الأخطاء لكل IP", [c.post("/api/errors", json={"kind": "ui"}).status_code for _ in range(main.ERR_RL_MAX + 1)][-1] == 429)
main._ERR_RL.clear()
SS = lambda uid, text="", lang="ar", **kw: c.post("/api/support/send", json={"init_data": init_data(uid, lang=lang), "text": text, "lang": lang, **kw})  # noqa: E731
TH = lambda uid, lang="ar": c.get("/api/support/thread", params={"init_data": init_data(uid, lang=lang), "lang": lang}).json()  # noqa: E731
ACT = lambda uid, kind, tid, arg=None: c.post("/api/support/action", json={"init_data": init_data(uid), "kind": kind, "tid": tid, "arg": arg})  # noqa: E731
th0 = TH(41)
ok("مركز الدعم: محادثة فارغة + رسالة ترحيب وردود سريعة من الإعدادات", th0["ticket"] is None and th0["config"]["enabled"] and th0["config"]["welcome"] and th0["config"]["quick"])
ok("مركز الدعم يتطلب هوية تلجرام صحيحة", c.get("/api/support/thread", params={"init_data": "x=1"}).status_code in (401, 403))
ok("رسالة فارغة مرفوضة", SS(41).status_code == 422)
CALLS.clear()
ok("فتح الدعم من شاشة الخطأ برقمه", SS(42, error_ref=er["ref"]).status_code == 200)
t42 = support.open_ticket_for(DB, 42)
ok("تذكرة فورية مربوطة بالخطأ وأولوية حرجة", t42 and t42["error_ref"] == er["ref"] and t42["priority"] == "critical" and t42["channel"] == "app")
th = TH(42)
ok("رد أولي فوري داخل التطبيق: رقم التذكرة + الوقت المتوقع", any(f"#{t42['id']}" in m_["text"] and "خلال" in m_["text"] for m_ in th["messages"] if m_["role"] == "notice"))
ok("لا شيء يُرسل للمستخدم في البوت (الدعم داخل التطبيق فقط)", not any(str(p_.get("chat_id")) == "42" for m_, p_ in CALLS if m_ == "sendMessage"))
ok("بلا مساعد ذكي ولا إجابة: تحويل للبشري", support.get_ticket(DB, t42["id"])["status"] == "escalated")

from types import SimpleNamespace as NS  # noqa: E402,F401
support.ai_available = lambda *a: True
SCRIPT = []
def fake_llm(cfg, system, messages):
    SCRIPT_SEEN.append(messages)
    return SCRIPT.pop(0)
SCRIPT_SEEN = []
support.llm = fake_llm
tool = lambda name, inp, id_="tu1": {"functionCall": {"name": name, "args": inp}, "thoughtSignature": "sig-" + id_}  # noqa: E731
txt = lambda t_: {"text": t_}  # noqa: E731
G = lambda *parts: {"role": "model", "parts": list(parts)}  # noqa: E731 — محتوى مرشّح Gemini
add_user(46, status="approved", language="en", sync={"state": "error", "fails": 3}, mt5_password="SECRET-PW", mt5_login="99887766")
SCRIPT[:] = [G(tool("get_user_context", {}, "a"), tool("run_auto_fix", {"action": "resync_account", "reason": "sync error"}, "b")),
             G(txt("I've re-synced your account. Data will refresh in a few minutes."))]
PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\0" * 64).decode()
ok("إرسال رسالة مع لقطة شاشة", SS(46, "My data is not updating", "en", image=PNG).status_code == 200)
t46 = support.open_ticket_for(DB, 46)
ok("المساعد: يقرأ بيانات المستخدم وينفّذ إصلاحًا مسموحًا", DB.store["users"]["46"]["sync"]["state"] == "new")
ok("المساعد يرى الصورة المرفقة (inlineData بنوعها الصحيح)", any(p_.get("inlineData", {}).get("mimeType") == "image/png" for c_ in SCRIPT_SEEN[0] for p_ in c_["parts"]))
ok("Gemini: نتيجة الأدوات تعود كـ functionResponse مع حفظ thoughtSignature", any(
    c_["role"] == "user" and "functionResponse" in c_["parts"][0] for c_ in SCRIPT_SEEN[-1]) and any(
    c_["role"] == "model" and c_["parts"][0].get("thoughtSignature") for c_ in SCRIPT_SEEN[-1]))
ok("الإصلاح الآلي مسجَّل", any(x["action"] == "resync_account" and x["uid"] == "46" for x in DB.store["auto_fix_log"].values()))
ok("سياق المساعد لا يكشف كلمة المرور ولا رقم الحساب كاملًا", "SECRET-PW" not in json.dumps(SCRIPT_SEEN, default=str) and "99887766" not in json.dumps(support.user_context(DB, 46)))
th = TH(46, "en")
img = next((m_ for m_ in th["messages"] if m_["role"] == "user"), {})
ok("الصورة محفوظة برابط عشوائي وتُعرض", (img.get("image") or "").startswith("/api/support/media/") and c.get(img["image"]).status_code == 200)
ok("اسم ملف غير صالح مرفوض (لا تجوّل في المسارات)", c.get("/api/support/media/..%2f.env").status_code == 404)
ok("ملف ليس صورة مرفوض", SS(46, "x", "en", image=base64.b64encode(b"<?php").decode()).status_code == 422)
ai_m = [m_ for m_ in th["messages"] if m_["role"] == "ai"]
ok("الرد بلغة المستخدم + زر موظف داخل التطبيق", ai_m and ai_m[-1]["text"].startswith("I've re-synced") and any(b["kind"] == "human" for b in ai_m[-1].get("buttons") or []))
ok("لا تكرار للرد في المحادثة", sum(1 for m_ in th["messages"] if m_["text"].startswith("I've re-synced")) == 1)
ok("مؤشر «يكتب…» ينطفئ بعد الرد", th["ticket"]["typing"] is False)
ok("إصلاح خارج القائمة البيضاء مرفوض", support.run_fix(DB, 46, "extend_subscription")["reason"] == "not_allowed")
ok("reset_stuck_link لا يلمس حسابًا غير عالق", support.run_fix(DB, 46, "reset_stuck_link")["ok"] is False)
DB.store.setdefault("config", {})["support"] = {"ai_actions": {"resync_account": False}}; support.invalidate()
DB.store["users"]["46"]["sync"] = {"state": "error"}
ok("إجراء معطّل من اللوحة لا ينفّذه المساعد", "disabled" in support._tool(DB, support.get_config(DB), 46, t46["id"], "run_auto_fix", {"action": "resync_account"}, {})
   and DB.store["users"]["46"]["sync"]["state"] == "error")
DB.store["config"]["support"] = {}; support.invalidate()
SCRIPT[:] = [G(tool("mark_resolved", {"summary": "resync fixed it"})), G(txt("Great, glad it's fixed! Your data will keep syncing automatically now."))]
SS(46, "yes it works now thanks", "en")
th = TH(46, "en")
ok("الحل + إشعار الحالة + طلب التقييم بأزرار", support.get_ticket(DB, t46["id"])["status"] == "resolved"
   and any(b["kind"] == "csat" for m_ in th["messages"] for b in m_.get("buttons") or []))
ok("إشعار داخل التطبيق بتغير حالة التذكرة", any(x.get("kind") == "support" and x["uid"] == "46" for x in DB.store["notifications"].values()))
sug = DB.store.get("support_kb_suggestions", {}).get(t46["id"])
ok("التعلّم: التذكرة المحلولة تقترح سؤالًا/جوابًا لقاعدة المعرفة", sug and sug["status"] == "pending" and "not updating" in sug["q"])
ok("تذكرة مستخدم آخر لا يمكن التحكم بها", ACT(47, "csat", t46["id"], "1").status_code == 404)
ok("تقييم الرضا من زر التطبيق", ACT(46, "csat", t46["id"], "5").status_code == 200 and support.get_ticket(DB, t46["id"])["csat"]["score"] == 5
   and DB.store["support_kb_suggestions"][t46["id"]]["score"] == 5)
ok("الأدمن: اقتراحات التعلّم", any(r_["id"] == t46["id"] for r_ in c.get("/api/admin/support/suggestions").json()["rows"]))
ok("اعتماد الاقتراح يضيفه لقاعدة المعرفة", c.post(f"/api/admin/support/suggestions/{t46['id']}/approve", json={"q": "data not updating", "a": "We re-sync your account automatically."}).status_code == 200
   and any(x["a"] == "We re-sync your account automatically." for x in support.search_kb(DB, "data not updating"))
   and not any(r_["id"] == t46["id"] for r_ in c.get("/api/admin/support/suggestions").json()["rows"]))

DB.store["config"]["support"] = {"escalation_threshold": 2, "support_chat_id": "9001"}; support.invalidate()
SCRIPT[:] = [G(txt("Try restarting the app.")), G(txt("Try again later."))]
for m in ("app crashes", "still crashes"):
    SS(47, m, "en")
CALLS.clear()
SS(47, "not fixed", "en")
t47 = support.open_ticket_for(DB, 47)
esc = [p_ for m_, p_ in CALLS if m_ == "sendMessage" and str(p_.get("chat_id")) == "9001"]
ok("تصعيد تلقائي بعد حد المحاولات مع ملخص للموظف في البوت", t47["status"] == "escalated" and esc and "تصعيد تذكرة" in esc[0]["text"] and "الأولوية" in esc[0]["text"])
CALLS.clear()
SS(47, "any update?", "en")
ok("رسالة على تذكرة مصعّدة → تنبيه الموظف فقط (بلا رد آلي)", any("رسالة جديدة" in p_.get("text", "") for m_, p_ in CALLS if str(p_.get("chat_id")) == "9001")
   and TH(47, "en")["messages"][-1]["role"] == "user")
CALLS.clear()
ok("رد الأدمن من اللوحة", c.post(f"/api/admin/support/tickets/{t47['id']}/reply", json={"text": "Please update to the latest version."}).status_code == 200)
ok("رد الموظف يظهر في التطبيق + التذكرة قيد المعالجة", any(m_["role"] == "agent" and "latest version" in m_["text"] for m_ in TH(47, "en")["messages"])
   and support.get_ticket(DB, t47["id"])["status"] == "in_progress")
push = [p_ for m_, p_ in CALLS if m_ == "sendMessage" and str(p_.get("chat_id")) == "47"]
ok("تنبيه في البوت بالرد مع زر يفتح مركز الدعم", push and "view=support" in json.dumps(push[0].get("reply_markup")))
support.llm = lambda *a: (_ for _ in ()).throw(RuntimeError("provider down"))
SS(48, "كيف أغير اللغة")
t48 = support.open_ticket_for(DB, 48)
ok("تعطل المزوّد: البحث في قاعدة المعرفة أولًا", t48 and any("الإعدادات" in (m_.get("text") or "") and m_["role"] == "ai" for m_ in support.messages_of(DB, t48["id"])))
support._RL.clear(); DB.store["config"]["support"]["rate_limit_count"] = 2; support.invalidate()
SS(49, "مرحبا")
for _ in range(4):
    SS(49, "سبام")
ok("حماية من السبام: تنبيه واحد فقط", sum(1 for m_ in TH(49)["messages"] if "رسائل كثيرة" in m_["text"]) == 1)
support._RL.clear(); DB.store["config"]["support"] = {"escalation_threshold": 5}; support.invalidate()
ok("طلب موظف من زر التطبيق", ACT(48, "human", t48["id"]).status_code == 200 and support.get_ticket(DB, t48["id"])["status"] in ("escalated",)
   or support.get_ticket(DB, t48["id"])["status"] == "escalated")

# تأكيد نعم/لا قبل إلغاء الربط (من مركز الدعم)
add_user(51, status="approved", language="ar", mt5_login="77441234", mt5_server="Exness-Real9", last_unlink_at=0)
support.llm = fake_llm
SCRIPT[:] = [G(tool("request_confirmation", {"action": "unlink_account", "question": "هل تريد إلغاء ربط حسابك ***234 على Exness-Real9؟"})),
             G(txt("سأطلب تأكيدك أولًا."))]
SS(51, "الغي ربط حسابي")
t51 = support.open_ticket_for(DB, 51)
ok("طلب إجراء حساس → سؤال تأكيد بأزرار نعم/لا، بلا تنفيذ", t51["pending_action"]["action"] == "unlink_account" and DB.store["users"]["51"]["status"] == "approved"
   and any(b["kind"] == "act" and b["arg"] == "yes" for m_ in TH(51)["messages"] for b in m_.get("buttons") or []))
ACT(51, "act", t51["id"], "yes")
ok("بعد «نعم»: تنفيذ فعلي + رسالة نتيجة واضحة ببيانات الحساب", DB.store["users"]["51"]["status"] == "unlinked"
   and any("تم إلغاء ربط" in m_["text"] and "•••••234" in m_["text"] for m_ in TH(51)["messages"]))
ok("التنفيذ بعد التأكيد مسجّل", any(x["action"] == "unlink_account" and x["by"] == "user_confirmed" for x in DB.store["auto_fix_log"].values()))
add_user(52, status="approved", language="ar", mt5_login="55667788", mt5_server="Exness-Real9")
SCRIPT[:] = [G(tool("request_confirmation", {"action": "relink_account", "question": "هل تريد ربط حساب جديد بدل الحالي؟"})), G(txt("."))]
SS(52, "أريد ربط حساب جديد")
SS(52, "لا")
ok("«لا» يلغي بلا أي تغيير", DB.store["users"]["52"]["status"] == "approved")
SCRIPT[:] = [G(tool("request_confirmation", {"action": "relink_account", "question": "هل تريد ربط حساب جديد بدل الحالي؟"})), G(txt("."))]
SS(52, "أريد ربط حساب جديد")
SS(52, "نعم")
ok("إعادة الربط: فكّ الحالي + زر يفتح شاشة الربط (لا بيانات دخول في الشات)", DB.store["users"]["52"]["status"] == "unlinked"
   and any(b["kind"] == "url" and "view=link" in b["url"] for m_ in TH(52)["messages"] for b in m_.get("buttons") or []))
FakeClient.mode = "ok"
r = c.post("/api/register", json=BODY(52, login="99001122", server="Exness-MT5Trial16"))
ok("بعد الربط من التطبيق: تأكيد في مركز الدعم ببيانات الحساب الجديد", r.status_code == 200
   and any("تم ربط الحساب الجديد" in m_["text"] and "•••••122" in m_["text"] for m_ in TH(52)["messages"]))

# البوت: أي رسالة نصية → زر يفتح مركز الدعم (مع رقم الخطأ إن وُجد)
CALLS.clear()
W({"message": {"chat": {"id": 62, "type": "private"}, "from": {"id": 62, "language_code": "en"}, "text": "help " + er["ref"]}})
bt = json.dumps(CALLS[-1][1])
ok("البوت يوجّه لمركز الدعم داخل التطبيق برقم الخطأ", "web_app" in bt and "view=support" in bt and er["ref"] in bt and not support.open_ticket_for(DB, 62))
st = c.post("/api/status", json={"init_data": init_data()}).json()["settings"]
ok("وضع الدعم = داخل التطبيق (لا بوت ولا حسابات)", st["support_mode"] == "app" and not st["support_url"])
ok("مسارات الدعم القديمة أُزيلت", c.post("/api/support-webhook", json={}).status_code in (404, 405) and c.get("/api/admin/support/accounts").status_code in (404, 405))
support.ai_available = lambda *a: False

g = c.get("/api/admin/support/config").json()
ok("الأدمن: System Prompt افتراضي كامل + المفاتيح لا تُعاد", g["prompt_is_default"] and "escalate_to_human" in g["system_prompt"] and "gemini_api_key" not in g and "support_bot_token" not in g)
ok("الأدمن: إعدادات مركز الدعم وصلاحيات المساعد", "ai_actions" in g and "welcome_ar" in g and "sounds_enabled" in g)
ok("مفتاح Gemini بالصيغة الأحدث (نقطة/أطول) + مسافات منسوخة يُقبل", c.put("/api/admin/support/config", json={"gemini_api_key": " AQ.Ab8RN6" + "k" * 60 + "_aRSg\n"}).status_code == 200
   and support.api_key(support.get_config(DB)) == "AQ.Ab8RN6" + "k" * 60 + "_aRSg")
ok("مفتاح بمحارف غير صالحة مرفوض", c.put("/api/admin/support/config", json={"gemini_api_key": "AIza<script>" + "x" * 30}).status_code == 422)
ok("مفتاح Gemini يُحفظ مشفّرًا ولا يُعاد", c.put("/api/admin/support/config", json={"gemini_api_key": "AIza" + "x" * 35}).json()["has_gemini_key"]
   and DB.store["config"]["support"]["gemini_api_key"].startswith("enc:") and support.api_key(support.get_config(DB)) == "AIza" + "x" * 35)
r = c.put("/api/admin/support/config", json={"ai_actions": {"resync_account": False, "hack": True}, "quick_ar": ["سؤال"] * 20, "support_phone": "+966 50 000 0000"})
ok("صلاحيات المساعد: القائمة البيضاء فقط + حد الردود السريعة", r.status_code == 200 and support.get_config(DB)["ai_actions"] == {**support.DEFAULT_CONFIG["ai_actions"], "resync_account": False}
   and len(support.get_config(DB)["quick_ar"]) <= 8)
ok("سجل التدقيق يخفي المفتاح", "x" * 35 not in json.dumps(c.get("/api/admin/audit").json()))
DB.store["config"]["support"]["attachments_enabled"] = False; support.invalidate()
ok("إيقاف المرفقات من اللوحة", SS(53, "hi", image=PNG).status_code == 403)
DB.store["config"]["support"]["attachments_enabled"] = True; support.invalidate()
rows = c.get("/api/admin/support/tickets", params={"status": "active"}).json()
ok("صندوق التذاكر + الإحصاءات", rows["stats"]["open"] >= 2 and rows["stats"]["csat_avg"] == 5)
ok("تفاصيل التذكرة + سياق المستخدم", any(m_["role"] == "agent" for m_ in c.get(f"/api/admin/support/tickets/{t47['id']}").json()["messages"]))
ok("سجل الأخطاء في اللوحة بحث", len(c.get("/api/admin/errors", params={"q": "ton_payment"}).json()["rows"]) == 1)
ok("قاعدة المعرفة: إضافة", c.post("/api/admin/support/kb", json={"q": "ساعات العمل", "a": "الدعم 24/7"}).status_code == 200 and support.search_kb(DB, "ساعات العمل")[0]["a"] == "الدعم 24/7")
al = c.get("/api/admin/alerts").json()
ok("تنبيهات فورية: خطأ حرج + تذكرة مصعّدة", any(x["type"] == "error" for x in al["alerts"]) and any(x["type"] == "ticket" for x in al["alerts"]))

# ═════════ 33) محفظة TON من اللوحة + OTP ═════════
import tonadmin  # noqa: E402
ton.TON_WALLET = "UQ_PROJECT_WALLET"
tonadmin.balance_nano = lambda: 12_500_000_000
ton.usd_rate = lambda: 2.0
ton.fetch_transactions = lambda limit=100: [{"hash": "h1", "lt": "1", "utime": 1, "source": "EQsrc", "value": 3_000_000_000, "comment": "x-order"}]
ov = c.get("/api/admin/ton/overview").json()
ok("الرصيد والتحويلات الواردة", ov["balance_ton"] == 12.5 and ov["balance_usd"] == 25.0 and ov["incoming"][0]["ton"] == 3.0)
ton.fetch_transactions = lambda limit=100: [{"hash": "h9", "lt": "2", "utime": 1, "source": "EQs", "value": 1, "comment": "gift/for you"},
                                              {"hash": "h8", "lt": "3", "utime": 1, "source": "EQs", "value": 1, "comment": "__x__"}]
ok("تعليق حر فيه / لا يُسقط الصفحة", c.get("/api/admin/ton/overview").status_code == 200)
from retry import RetryableError  # noqa: E402
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("ton_real", os.path.join(os.path.dirname(os.path.abspath(__file__)), "ton.py"))
_ton_real = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_ton_real)
_ton_real.TON_WALLET = ton.TON_WALLET
_orig_get = _ton_real._get_transactions
ton.fetch_transactions = _ton_real.fetch_transactions
_ton_real._get_transactions = lambda limit: (_ for _ in ()).throw(RetryableError("429"))
ov = c.get("/api/admin/ton/overview")
ok("حد toncenter (429): الصفحة تعمل وتعرض السبب", ov.status_code == 200 and "rate limit" in ov.json()["error"])
_ton_real._get_transactions = _orig_get
NEW = "UQ" + "B" * 46
CALLS.clear()
otp = c.post("/api/admin/ton/otp", json={"action": "set_wallet", "params": {"address": NEW}}).json()
code_msg = [p_["text"] for m_, p_ in CALLS if m_ == "sendMessage" and p_.get("chat_id") == 555][-1]
code = re.search(r"الرمز: (\d{6})", code_msg).group(1)
ok("OTP يُرسل للأدمن عبر البوت", otp["sent"] and "تغيير محفظة الاستلام" in code_msg)
ok("رمز خاطئ مرفوض", c.post("/api/admin/ton/execute", json={"otp_id": otp["otp_id"], "code": "000000" if code != "000000" else "111111"}).status_code == 403)
ok("لا تنفيذ قبل الرمز الصحيح", ton.TON_WALLET == "UQ_PROJECT_WALLET")
ok("الرمز الصحيح ينفّذ", c.post("/api/admin/ton/execute", json={"otp_id": otp["otp_id"], "code": code}).json()["ok"] and ton.TON_WALLET == NEW)
ok("الرمز للاستخدام مرة واحدة", c.post("/api/admin/ton/execute", json={"otp_id": otp["otp_id"], "code": code}).status_code == 403)
ok("عنوان غير صالح مرفوض", c.post("/api/admin/ton/otp", json={"action": "set_wallet", "params": {"address": "bad"}}).status_code == 422)
CALLS.clear()
otp = c.post("/api/admin/ton/otp", json={"action": "transfer", "params": {"to": "EQ" + "C" * 46, "amount_ton": 1.5, "comment": "payout"}}).json()
code = re.search(r"الرمز: (\d{6})", [p_["text"] for m_, p_ in CALLS if m_ == "sendMessage"][-1]).group(1)
tx = c.post("/api/admin/ton/execute", json={"otp_id": otp["otp_id"], "code": code}).json()["transaction"]
ok("التحويل: طلب TON Connect يوقّعه الأدمن (الخادم بلا مفتاح)", tx["messages"][0]["amount"] == "1500000000" and tx["messages"][0]["payload"])
c.post("/api/admin/ton/transfer-result", json={"otp_id": otp["otp_id"], "ok": True, "boc": "te6cc"})
lg = c.get("/api/admin/ton/log").json()["rows"]
c.put("/api/admin/settings", json={"pay_ton_enabled": False})
ok("تشغيل/إيقاف TON لا يتجاوز OTP عبر الإعدادات العامة", billing.get_settings(DB).get("pay_ton_enabled", True) is True)
ok("سجل كل محاولة (ناجحة وفاشلة)", {x["event"] for x in lg} >= {"otp_requested", "otp_wrong", "executed", "transfer_signed", "otp_expired"})
ton.TON_WALLET = ""
c.post("/api/admin/logout")
admin_access.invalidate(); admin_login(555); c.put("/api/admin/staff", json={"id": "7777", "role": "support", "name": "Mona"})
admin_login(7777)
ok("صلاحيات: الدعم يرى التذاكر ولا يلمس محفظة TON", c.get("/api/admin/support/tickets").status_code == 200 and c.get("/api/admin/ton/overview").status_code == 403)
ok("صلاحيات: الدعم لا يرسل إشعارات", c.post("/api/admin/notifications/broadcast", json={"target": "all", "title_ar": "x"}).status_code == 403)
c.post("/api/admin/logout")

# ═════════ 34) النمو: كوبونات، هدايا، حملات، أتمتة، قمع، إحالة متدرّجة، باقات خاصة، صيانة، تصدير ═════════
import growth  # noqa: E402
reset(); admin_access.invalidate(); support.invalidate()
admin_login(555)
add_package("p1")
add_user(42, status="approved", language="ar", nickname="Ahmed Ali")
payments.create_invoice = lambda **kw: CALLS.append(("np", kw)) or {"id": "inv9", "invoice_url": "https://np/inv9"}
ok("كوبون: إنشاء من اللوحة", c.post("/api/admin/growth/coupons", json={"code": "black20", "type": "discount", "value": 20, "max_uses": 1, "valid_hours": 48}).status_code == 200)
red = c.post("/api/coupons/redeem", json={"init_data": init_data(), "code": "BLACK20"}).json()
ok("استرداد الكوبون → مكافأة في المحفظة", red["type"] == "discount" and DB.store["scratch_cards"][red["reward_id"]]["prize"]["value"] == 20)
ok("مرة واحدة لكل مستخدم", c.post("/api/coupons/redeem", json={"init_data": init_data(), "code": "BLACK20"}).status_code == 409)
add_user(43, status="approved")
ok("حد الاستخدامات", c.post("/api/coupons/redeem", json={"init_data": init_data(43), "code": "BLACK20"}).json()["detail"] == "coupon_exhausted")
CALLS.clear()
c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1", "reward_id": red["reward_id"]})
ok("الكوبون يُطبَّق في الدفع تلقائيًا", [p_ for m_, p_ in CALLS if m_ == "np"][-1]["amount_usd"] == 23)
ok("المبلغ المعروض للعملات المستقرة بلا كسور", payments.display_amount("usdttrc20", "12.000850", 1.0) == "12"
   and payments.display_amount("usdttrc20", "12.4", 1.0) == "12.40" and payments.display_amount("btc", "0.000123400", 1.0) == "0.0001234")
DB.store["payments"]["np1"] = {"uid": 42, "package_id": "p1", "status": "waiting", "amount_usd": 12, "method": "nowpayments",
                               "np_payment_id": "5001", "np_pay": {"pay_amount": 12.00085}, "created_at": time.time()}
main.process_nowpayments({"order_id": "np1", "payment_status": "partially_paid", "actually_paid": 12, "pay_amount": 12.00085})
ok("دفع المبلغ المعروض (12) يُقبل ضمن الهامش", DB.store["payments"]["np1"]["status"] == "finished" and DB.store["payments"]["np1"]["accepted_partial"])
DB.store["payments"]["np2"] = {"uid": 42, "package_id": "p1", "status": "waiting", "amount_usd": 12, "method": "nowpayments",
                               "np_payment_id": "5002", "np_pay": {"pay_amount": 12}, "created_at": time.time()}
main.process_nowpayments({"order_id": "np2", "payment_status": "partially_paid", "actually_paid": 10, "pay_amount": 12})
ok("دفع ناقص فعلًا لا يُقبل", DB.store["payments"]["np2"]["status"] == "partially_paid")
payments.get_payment = lambda pid: {"payment_status": "finished", "actually_paid": 12, "pay_amount": 12}
main.reconcile_nowpayments()
ok("المطابقة الدورية تفعّل الدفعات حتى لو ضاع الـ webhook", DB.store["payments"]["np2"]["status"] == "finished")
c.put("/api/admin/settings", json={"np_payout_address": "TXyz1234567890abcdefghijkLMNOP", "np_payout_currency": "usdttrc20"})
_seen_np = {}
_pspec = _ilu.spec_from_file_location("payments_real", os.path.join(os.path.dirname(os.path.abspath(__file__)), "payments.py"))
_pay_real = _ilu.module_from_spec(_pspec); _pspec.loader.exec_module(_pay_real)
payments.create_direct_payment = _pay_real.create_direct_payment
_pay_real._np = lambda method, path, body=None: (_seen_np.update(body or {}) or NS(status_code=201, json=lambda: {"payment_id": "p9", "pay_address": "TAddr", "pay_amount": 23.0004, "pay_currency": "usdttrc20"}))
rr = c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1", "pay_currency": "usdttrc20"}).json()
ok("تحويل تلقائي لمحفظتك المحددة + مبلغ معروض بلا كسور", _seen_np.get("payout_address") == "TXyz1234567890abcdefghijkLMNOP" and rr["display_amount"] == "23")

g = c.post("/api/admin/growth/gifts", json={"type": "days", "value": 5, "max_claims": 10, "title": "هدية الإطلاق"}).json()
ok("رابط هدية: رابط البوت جاهز", g["bot_link"].endswith(f"start=gift_{g['id']}"))
CALLS.clear()
W({"message": {"chat": {"id": 44, "type": "private"}, "from": {"id": 44, "language_code": "ar"}, "text": f"/start gift_{g['id']}"}})
ok("فتح رابط الهدية يمنح الأيام تلقائيًا", DB.store["users"]["44"]["subscription"]["expires_at"] > time.time() + 4 * 86400
   and any("5 يوم" in (p_.get("text") or "") for m_, p_ in CALLS))
ok("الهدية مرة واحدة", c.post("/api/gifts/claim", json={"init_data": init_data(44), "code": g["id"]}).json()["detail"] == "already_claimed")

c.post("/api/admin/growth/campaigns", json={"slug": "fb-sept", "name": "فيسبوك سبتمبر", "source": "facebook", "gift_code": g["id"]})
W({"message": {"chat": {"id": 45, "type": "private"}, "from": {"id": 45, "language_code": "en"}, "text": "/start c_fb-sept"}})
ok("رابط الحملة: نسب المستخدم + نقرة + هدية الحملة", DB.store["users"]["45"]["campaign"] == "fb-sept"
   and DB.store["campaigns"]["fb-sept"]["clicks"] == 1 and DB.store["users"]["45"]["subscription"]["expires_at"] > time.time())
W({"message": {"chat": {"id": 45, "type": "private"}, "from": {"id": 45}, "text": "/start c_other"}})
ok("أول لمسة فقط", DB.store["users"]["45"]["campaign"] == "fb-sept")
DB.store["payments"]["x1"] = {"uid": 45, "status": "finished", "amount_usd": 129.0, "method": "nowpayments"}
DB.store["users"]["45"]["status"] = "approved"
camp = [r_ for r_ in c.get("/api/admin/growth/campaigns").json()["rows"] if r_["id"] == "fb-sept"][0]
ok("قمع الحملة: فتح ← ربط ← دفع + الإيرادات", camp["funnel"]["opened"] == 1 and camp["funnel"]["paid"] == 1 and camp["funnel"]["revenue_usd"] == 129.0)
fn = c.get("/api/admin/growth/funnel").json()
ok("القمع العام ونقاط التسرب", fn["opened"] >= 4 and fn["dropoff"]["linked_not_paid"] >= 1 and c.get("/api/admin/ceo").json()["funnel"]["paid"] >= 1)

# الأتمتة: ربط ولم يشترك منذ يوم
DB.store["users"]["42"]["decided_at"] = time.time() - 2 * 86400
DB.store["users"]["42"].pop("subscription", None)
auto = c.get("/api/admin/growth/automations").json()
ok("قواعد الاسترجاع الافتراضية موقوفة حتى يفعّلها الأدمن", {r_["id"] for r_ in auto["rows"]} >= {"winback_linked", "winback_expired"} and not any(r_["enabled"] for r_ in auto["rows"]))
rule = [r_ for r_ in auto["rows"] if r_["id"] == "winback_linked"][0]
c.put("/api/admin/growth/automations/winback_linked", json={**rule, "enabled": True})
CALLS.clear()
ok("تشغيل الأتمتة: رسالة + عرض خاص", c.post("/api/admin/growth/automations/run").json()["sent"] >= 1
   and any("Ahmed" in (p_.get("text") or "") and "10%" in (p_.get("text") or "") for m_, p_ in CALLS)
   and any(k.startswith("42_auto_winback_linked") for k in DB.store["scratch_cards"]))
CALLS.clear()
c.post("/api/admin/growth/automations/run")
ok("لا تكرار لنفس المستخدم في نفس الدورة", not any(p_.get("chat_id") in (42, "42") for m_, p_ in CALLS if m_ == "sendMessage"))
ok("سجل الأتمتة", len(c.get("/api/admin/growth/automations").json()["log"]) >= 1)

# الإحالة المتدرّجة
c.put("/api/admin/settings", json={"referral_enabled": True, "referral_days": 7, "referral_tiers": [{"min": 0, "days": 7}, {"min": 2, "days": 20}]})
add_user(100, status="approved", referral_paid_count=2)
add_user(101, status="approved", referred_by="100")
DB.store["payments"]["r1"] = {"uid": 101, "package_id": "p1", "status": "waiting", "amount_usd": 29.0, "method": "nowpayments"}
main.activate_payment("r1")
ok("المُحيل في المستوى الثاني يحصل على 20 يومًا", DB.store["users"]["100"]["referral_earned_days"] == 20 and DB.store["users"]["100"]["referral_paid_count"] == 3)
st_ = c.get("/api/referral/stats", params={"init_data": init_data(100)}).json()
ok("لوحة أرباح الإحالة للمستخدم", st_["earned_days"] == 20 and st_["tier"]["days"] == 20 and st_["next"] is None)
ok("مستويات غير صالحة مرفوضة", c.put("/api/admin/settings", json={"referral_tiers": [{"min": 3, "days": 5}]}).status_code == 422)

# باقة خاصة لمستخدم واحد
CALLS.clear()
pp = c.post("/api/admin/packages/private", json={"uid": "42", "name_ar": "عرض VIP", "price_usd": 49, "duration_days": 10, "offer_hours": 24}).json()
mine = [p_["id"] for p_ in c.get("/api/packages", params={"init_data": init_data()}).json()["packages"]]
others = [p_["id"] for p_ in c.get("/api/packages", params={"init_data": init_data(43)}).json()["packages"]]
ok("الباقة الخاصة تظهر لصاحبها فقط + إشعار", pp["id"] in mine and pp["id"] not in others and pp["id"] not in [p_["id"] for p_ in c.get("/api/packages").json()["packages"]]
   and any(n_["kind"] == "broadcast" and n_["uid"] == "42" for n_ in DB.store["notifications"].values()))
ok("غير صاحبها لا يستطيع شراءها", c.post("/api/payments/create", json={"init_data": init_data(43), "package_id": pp["id"]}).status_code == 404)
r = c.post("/api/payments/create", json={"init_data": init_data(), "package_id": pp["id"]}).json()
main.activate_payment(r["order_id"])
ok("لمرة واحدة: تختفي بعد الشراء", pp["id"] not in [p_["id"] for p_ in c.get("/api/packages", params={"init_data": init_data()}).json()["packages"]])

# وضع الصيانة
c.put("/api/admin/settings", json={"maintenance": True})
ok("الصيانة توقف الدفع والتسجيل وتظهر للتطبيق", c.post("/api/payments/create", json={"init_data": init_data(), "package_id": "p1"}).status_code == 503
   and c.post("/api/register", json=BODY(46)).status_code == 503 and c.post("/api/status", json={"init_data": init_data()}).json()["settings"]["maintenance"])
c.put("/api/admin/settings", json={"maintenance": False})

# التصدير
ex = c.get("/api/admin/export/users")
ok("تصدير CSV (Excel) + تسجيله في السجل", ex.status_code == 200 and ex.text.startswith("﻿") and "telegram_id" in ex.text
   and c.get("/api/admin/audit").json()["rows"][0]["action"] == "تصدير بيانات المستخدمين")
ok("تصدير المدفوعات والتذاكر", c.get("/api/admin/export/payments").status_code == 200 and c.get("/api/admin/export/tickets").status_code == 200)
c.post("/api/admin/logout")

# ═════════ 35) المراقبة الخارجية + إصلاح جسر MT5 ═════════
import uptime_monitor  # noqa: E402
uptime_monitor.STATE = os.path.join(tempfile.mkdtemp(), "state.json")
SENTU = []
t0 = 1_000_000.0
uptime_monitor.run(t0, {"api": (False, "ConnectionRefused")}, SENTU.append)
ok("فحص فاشل واحد لا يُنبّه (إعادة تشغيل عادية)", SENTU == [])
uptime_monitor.run(t0 + 60, {"api": (False, "ConnectionRefused")}, SENTU.append)
ok("فحصان متتاليان → تنبيه فوري", len(SENTU) == 1 and "تعطّل" in SENTU[0] and "الـ API" in SENTU[0])
uptime_monitor.run(t0 + 120, {"api": (False, "x")}, SENTU.append)
ok("لا تكرار قبل 30 دقيقة", len(SENTU) == 1)
uptime_monitor.run(t0 + 60 + 1801, {"api": (False, "x")}, SENTU.append)
ok("تذكير كل 30 دقيقة ما دام متوقفًا", len(SENTU) == 2 and "ما زال" in SENTU[1])
uptime_monitor.run(t0 + 2000, {"api": (True, "HTTP 200")}, SENTU.append)
ok("رسالة التعافي", len(SENTU) == 3 and "عاد للعمل" in SENTU[2])
rows_ = sync_worker.read_rows([NS(login=5, balance=1.5)], ("login", "balance"))
ok("قراءة صفوف MT5 بلا اتصال بعيد (الطريق الآمن)", rows_ == [{"login": 5, "balance": 1.5}])
class _FakeConn:
    def __init__(self): self.namespace = {}
    def eval(self, expr): return eval(expr, {}, self.namespace)
ok("بناء الصفوف على الجهة البعيدة (بلا pickle لكائنات MT5)", sync_worker.read_rows([NS(login=7, balance=2.0)], ("login", "balance"), _FakeConn()) == [{"login": 7, "balance": 2.0}])

# ═════════ 36) معادلات حركة المتصدرين + شكل نافذة التحديثات ═════════
import lbscript  # noqa: E402
reset(); admin_login(555)
ok("معادلة غير آمنة مرفوضة", c.put("/api/admin/leaderboard", json={"script": "__import__('os').system('x')"}).status_code == 422)
pv = c.post("/api/admin/leaderboard/script/preview", json={"script": "base * (1 + 0.1 * wave(86400, i / n))", "interval_sec": 3600}).json()
ok("معاينة المعادلة على أسبوع", len(pv["names"]) == 8 and len(pv["series"][0]) > 50)
c.put("/api/admin/leaderboard", json={"enabled": True, "dynamic": True, "script_enabled": True, "script": "base * 2",
                                      "profiles": [{"name": "S1", "base_usd": 100}, {"name": "S2", "base_usd": 50}]})
leaderboard.tick(DB, leaderboard.get_config(DB), now=time.time())
leaderboard.tick(DB, leaderboard.get_config(DB), now=time.time(), force=True)
ok("المعادلة تتحكم بالحركة فعليًا", [b["usd"] for b in DB.store["leaderboard"]["sim"]["bots"]] == [200.0, 100.0])
c.put("/api/admin/leaderboard", json={"script": "cur / (rank - rank)"})
leaderboard.tick(DB, leaderboard.get_config(DB), now=time.time(), force=True)
ok("خطأ حسابي لا يُسقط الترتيب", all(b["usd"] >= 0 for b in DB.store["leaderboard"]["sim"]["bots"]))
announcements.seed_default(DB)
r = c.put("/api/admin/announcements/launch", json={"style": {"accent": "#22c55e", "width": 520, "position": "center", "radius": 12, "evil": "x"}})
ok("شكل النافذة قابل للتحكم ويُتحقق منه", r.status_code == 200 and r.json()["style"]["accent"] == "#22c55e" and r.json()["style"]["position"] == "center" and "evil" not in r.json()["style"])
ok("لون غير صالح مرفوض", c.put("/api/admin/announcements/launch", json={"style": {"bg": "red;}"}}).status_code == 422)
r = c.put("/api/admin/announcements/launch", json={"style": {"position": "fullscreen", "theme": "app", "image_mode": "background", "image_height": 999,
                                                                "overlay": 40, "cta_place": "sticky", "animation": "zoom", "show_close": False}})
ok("تخصيص كامل: ملء الشاشة + وضع التطبيق + صورة خلفية + زر مثبّت + حركة", r.status_code == 200 and r.json()["style"]["position"] == "fullscreen"
   and r.json()["style"]["theme"] == "app" and r.json()["style"]["image_height"] == 420 and r.json()["style"]["show_close"] is False)
ok("خيار شكل غير صالح مرفوض", c.put("/api/admin/announcements/launch", json={"style": {"animation": "explode"}}).status_code == 422)
c.put("/api/admin/announcements/launch", json={"style": {"position": "center", "theme": "custom", "image_mode": "top", "cta_place": "inline", "animation": "slide", "show_close": True}})
c.post("/api/admin/logout")

# ═════════ 37) بوابة الدفع الخاصة AW Pay (TRON / BSC / TON) ═════════
import gateway, gw_chains, chain_crypto  # noqa: E402,E401
raw_, h_ = chain_crypto.sign_legacy_tx(bytes.fromhex("46" * 32), nonce=9, gas_price=20 * 10**9, gas=21000,
                                       to="0x3535353535353535353535353535353535353535", value=10**18, data=b"", chain_id=1)
ok("توقيع EIP-155 مطابق للمتجه الرسمي", raw_.endswith("25a028ef61340bd939bc2195fe537567866003e1a15d3c71ff63e1590620aa636276a067cbe9d8997f761aecb703304b3800ccf555c9f3dc64214b297fb1966a3b6d83"))
ok("عنوان ETH مطابق للمتجه المعروف", chain_crypto.eth_address(bytes.fromhex("4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318")) == "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23")
ok("تحقق عناوين TRON (checksum)", chain_crypto.is_tron_address(gw_chains.USDT_TRC20) and not chain_crypto.is_tron_address("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6u"))
ok("قراءة تعليق TON من BOC", chain_crypto.payload_comment(ton.comment_payload("AWTEST1")) == "AWTEST1")
# بيانات حقيقية: سحب USDT من Binance إلى عنوان الاستلام (toncenter يعيد التعليق فارغًا، tonapi يعيده)
OWNER_ = "UQA6upacy-O8MSNlwbSUCNYiTjwUIzeCjs6tKIaDDboYAWqx"
ME_RAW_ = "0:3aba969ccbe3bc312365c1b49408d6224e3c142337828ecead2886830dba1801"
USDT_RAW_ = "0:b113a994b5024a16719f69139328eb759596c38a25f59028b146fecdc3621dfe"
ok("تحويل عنوان TON للصيغة الخام (checksum)", chain_crypto.ton_raw(OWNER_) == ME_RAW_ and chain_crypto.ton_raw(gw_chains.USDT_TON_MASTER) == USDT_RAW_)
def _jt(recipient, jetton, amount, comment, status="ok"):
    return {"type": "JettonTransfer", "status": status, "JettonTransfer": {
        "sender": {"address": "0:ca1d9edeef40b3a9dbd9082f3767859547c3ce0bf641d09d58e33a3cf06fb309", "name": "Binance Hot Wallet"},
        "recipient": {"address": recipient}, "amount": amount, "comment": comment, "jetton": {"address": jetton, "symbol": "USD₮", "decimals": 6}}}
TONAPI_ = {"events": [{"event_id": "da3c12a9d144591ba741364c61cf6545404953585eaa16cd86788f7bd317f07b", "timestamp": 1790373601, "actions": [
    _jt("0:5f0000000000000000000000000000000000000000000000000000000000abcd", USDT_RAW_, "59700000", "UQAWV6OX7GR8DAAia34M0c8EjEICy"),
    _jt(ME_RAW_, USDT_RAW_, "10000000", "AWF9LER9W"),
    _jt(ME_RAW_, "0:" + "1" * 64, "10000000", "AWFAKE000"),
    _jt(ME_RAW_, USDT_RAW_, "10000000", "AWFAILED0", status="failed")]}]}
TONCENTER_ = {"jetton_transfers": [{"amount": "10000000", "transaction_hash": "x/KWrH1IX0FPXa8ZOJKCYCsMkUJkrrlz9hx3cYpouTI=", "transaction_now": 1790373601,
                                    "transaction_aborted": False, "forward_payload": None, "decoded_forward_payload": None, "source": "0:ca1d"}]}
_http_ = dict(gw_chains.HTTP)
gw_chains.HTTP["get"] = lambda url, params=None, headers=None: TONAPI_ if "tonapi" in url else TONCENTER_
got_ = gw_chains.ton_jetton_incoming(OWNER_, gw_chains.USDT_TON_MASTER)
ok("USDT على TON من Binance: التعليق يُقرأ (tonapi)", [(t["amount"], t["comment"]) for t in got_] == [(10_000_000, "AWF9LER9W")])
ok("…ويُتجاهل: تحويل لعنوان آخر، توكن مزيف بنفس الاسم، تحويل فاشل", len(got_) == 1)
def _tonapi_down(url, params=None, headers=None):
    if "tonapi" in url:
        raise RuntimeError("tonapi down")
    return TONCENTER_
gw_chains.HTTP["get"] = _tonapi_down
ok("tonapi متوقف: toncenter احتياطيًا", [t["amount"] for t in gw_chains.ton_jetton_incoming(OWNER_, gw_chains.USDT_TON_MASTER)] == [10_000_000])
gw_chains.HTTP.update(_http_)

reset(); admin_login(555)
BAL = {}
gw_chains.tron_trc20_balance = lambda contract, addr: BAL.get(("usdttrc20", addr), 0)
gw_chains.tron_trx_balance = lambda addr: BAL.get(("trx", addr), 0)
gw_chains.bsc_token_balance = lambda contract, addr, confs=0: BAL.get(("usdtbsc", addr), 0)
gw_chains.bsc_native_balance = lambda addr, confs=0: BAL.get(("bnbbsc", addr), 0)
gw_chains.usd_rates = lambda ttl=60: {"trx": 0.25, "bnb": 600.0, "ton": 5.0}
TONTX, JTX, SENT, TXST = [], [], [], {}
gw_chains.ton_incoming = lambda address, limit=100: list(TONTX)
gw_chains.ton_jetton_incoming = lambda owner, master, limit=100: list(JTX)
def _gw_trx(priv, to, amt):
    SENT.append(("trx", chain_crypto.tron_address(priv), to, amt)); return f"tx{len(SENT)}"
def _gw_usdt(priv, contract, to, amt, fl):
    SENT.append(("usdt", chain_crypto.tron_address(priv), to, amt)); return f"tx{len(SENT)}"
gw_chains.tron_send_trx, gw_chains.tron_send_trc20 = _gw_trx, _gw_usdt
gw_chains.tron_trc20_fee_sun = lambda frm, contract, to, amt: 20_000_000
gw_chains.tron_tx_status = lambda tx: TXST.get(tx, "success")
gw_chains.bsc_gas_price = lambda: 1_000_000_000

ok("البوابة موقوفة افتراضيًا: العملات من NOWPayments", c.get("/api/payments/currencies").json()["provider"] == "nowpayments")
os.environ.pop("GATEWAY_MASTER_KEY", None)
ok("لا تشغيل بلا مفتاح رئيسي في .env", c.put("/api/admin/gateway", json={"enabled": True}).status_code == 422)
os.environ["GATEWAY_MASTER_KEY"] = "11" * 32
PAY_TRON = chain_crypto.tron_address(bytes.fromhex("22" * 32))
PAY_TON = "UQ" + "D" * 46
def _otp_exec(params):
    CALLS.clear()
    o_ = c.post("/api/admin/ton/otp", json={"action": "gw_payout", "params": params})
    if o_.status_code != 200:
        return o_.status_code
    code_ = re.search(r"الرمز: (\d{6})", [p_["text"] for m_, p_ in CALLS if m_ == "sendMessage"][-1]).group(1)
    return c.post("/api/admin/ton/execute", json={"otp_id": o_.json()["otp_id"], "code": code_}).status_code
ok("عنوان استلام غير صالح للشبكة مرفوض", _otp_exec({"network": "tron", "address": "0x2c7536E3605D9C16a7a3D7b1898e529396a65c23"}) == 422)
c.put("/api/admin/gateway", json={"payout": {"tron": "TATTACKER"}})
ok("عنوان الاستلام لا يتغير من الإعدادات العامة", gateway.get_config(DB)["payout"]["tron"] == "")
ok("تغيير عنوان الاستلام برمز OTP فقط", _otp_exec({"network": "tron", "address": PAY_TRON}) == 200 and _otp_exec({"network": "ton", "address": PAY_TON}) == 200
   and gateway.get_config(DB)["payout"]["tron"] == PAY_TRON)
ov_ = c.put("/api/admin/gateway", json={"enabled": True, "sweep_min_usd": {"tron": 10}}).json()
ok("تشغيل البوابة", ov_["active"] and ov_["ready"] == {"tron": True, "bsc": False, "ton": True})
cur_ = c.get("/api/payments/currencies").json()
ok("العملات المتاحة حسب الشبكات الجاهزة فقط", cur_["provider"] == "aw" and {x["code"] for x in cur_["currencies"]} == {"usdttrc20", "trx", "ton", "usdtton"})

add_package("p1", price_usd=12.0)
add_user(42, status="approved", language="ar")
r_ = c.post("/api/payments/create", json={"init_data": init_data(42), "package_id": "p1", "pay_currency": "usdttrc20"}).json()
DEP = gateway.address_of("tron", gateway.deposit_key("tron", 42))
ok("عنوان إيداع خاص بالمستخدم + مبلغ نظيف", r_["pay_address"] == DEP and r_["display_amount"] == "12" and r_["provider"] == "aw")
ok("نفس العنوان دائمًا لنفس المستخدم (اشتقاق حتمي)", gateway.address_of("tron", gateway.deposit_key("tron", 42)) == DEP != gateway.address_of("tron", gateway.deposit_key("tron", 43)))
oid_ = r_["order_id"]
BAL[("usdttrc20", DEP)] = 5_000_000
CALLS.clear(); main.run_gateway_tick()
p_ = DB.store["payments"][oid_]
ok("دفعة ناقصة: الحالة + رسالة بالمتبقي للمستخدم + تنبيه الأدمن", p_["status"] == "partially_paid"
   and any("المتبقي 7" in x[1].get("text", "") for x in CALLS if x[1].get("chat_id") == 42) and any(x[1].get("chat_id") == 555 for x in CALLS))
r2_ = c.post("/api/payments/create", json={"init_data": init_data(42), "package_id": "p1", "pay_currency": "usdttrc20"}).json()
ok("طلب جديد أثناء دفعة ناقصة يعيد نفس الفاتورة لإكمالها", r2_["order_id"] == oid_ and r2_["remaining"] == "7")
BAL[("usdttrc20", DEP)] = 11_950_000  # نقص 0.4% ضمن هامش 1%
main.run_gateway_tick()
ok("اكتمال الدفع ضمن الهامش يفعّل الاشتراك", DB.store["payments"][oid_]["status"] == "finished" and DB.store["users"]["42"].get("subscription"))
ok("العنوان يُعلَّم للتجميع", DB.store["gw_addresses"]["tron-42"]["dirty"] and not DB.store["gw_addresses"]["tron-42"]["open_order"])

# التجميع: تمويل الغاز من الخزان ثم تحويل USDT لعنوان الاستلام
GAS = gateway.address_of("tron", gateway.gas_key("tron"))
main.run_gateway_sweeps()
ok("تمويل الغاز من الخزان أولًا", SENT[-1][0] == "trx" and SENT[-1][1] == GAS and SENT[-1][2] == DEP)
TXST[f"tx{len(SENT)}"] = "pending"
main.run_gateway_sweeps()
ok("انتظار تأكيد الشبكة قبل الخطوة التالية", len(SENT) == 1)
TXST[f"tx{len(SENT)}"] = "success"; BAL[("trx", DEP)] = 21_000_000
main.run_gateway_sweeps()
ok("تحويل كامل رصيد USDT إلى عنوان الاستلام", SENT[-1] == ("usdt", DEP, PAY_TRON, 11_950_000))
main.run_gateway_sweeps()
sw_ = list(DB.store["gw_sweeps"].values())
ok("تسجيل عملية التجميع", len(sw_) == 1 and sw_[0]["amount"] == "11.95" and sw_[0]["to"] == PAY_TRON)
BAL[("usdttrc20", DEP)] = 0; BAL[("trx", DEP)] = 900_000
main.run_gateway_sweeps(); main.run_gateway_sweeps()
ok("لا تجميع دون الحد الأدنى + العنوان يعود هادئًا", len(SENT) == 2 and not DB.store["gw_addresses"]["tron-42"]["dirty"])

# لا تجميع أثناء فاتورة مفتوحة، ولا فاتورة أثناء تجميع جارٍ
r3_ = c.post("/api/payments/create", json={"init_data": init_data(42), "package_id": "p1", "pay_currency": "usdttrc20"}).json()
BAL[("usdttrc20", DEP)] = 30_000_000
DB.store["gw_addresses"]["tron-42"]["dirty"] = True
ok("لا تجميع أثناء فاتورة مفتوحة", gateway.sweep_address(DB, "tron", 42, main.gw_hooks())["state"] == "open_invoice")
ok("الرصيد القديم لا يُحسب دفعًا للفاتورة الجديدة", DB.store["payments"][r3_["order_id"]]["baseline_units"] == 0)
main.run_gateway_tick()
ok("…لكن التحويل الجديد يُحسب", DB.store["payments"][r3_["order_id"]]["status"] == "finished")
DB.store["gw_addresses"]["tron-42"]["op"] = {"stage": "sweeping", "tx": "txZ", "at": time.time(), "asset": "usdttrc20"}
TXST["txZ"] = "pending"
ok("فاتورة جديدة أثناء تجميع جارٍ: انتظر قليلًا", c.post("/api/payments/create", json={"init_data": init_data(42), "package_id": "p1", "pay_currency": "usdttrc20"}).status_code == 409)
DB.store["gw_addresses"]["tron-42"]["op"] = None

# TON: الدفع المباشر لعنوانك بتعليق فريد
add_user(77, status="approved", language="en")
rt_ = c.post("/api/payments/create", json={"init_data": init_data(77), "package_id": "p1", "pay_currency": "ton"}).json()
ok("TON: عنوانك مباشرة + تعليق فريد + رابط المحفظة", rt_["pay_address"] == PAY_TON and rt_["payin_extra_id"].startswith("AW")
   and rt_["display_amount"] == "2.4" and "text=" + rt_["payin_extra_id"] in rt_["wallet_link"])
gateway._TON_CACHE.clear(); TONTX.append({"hash": "hx", "utime": int(time.time()), "amount": 2_400_000_000, "comment": "wrong", "source": "EQs"})
main.run_gateway_tick()
ok("تحويل بتعليق آخر لا يُحتسب", DB.store["payments"][rt_["order_id"]]["status"] == "waiting")
gateway._TON_CACHE.clear(); TONTX.append({"hash": "hy", "utime": int(time.time()), "amount": 2_400_000_000, "comment": rt_["payin_extra_id"].lower(), "source": "EQs"})
main.run_gateway_tick()
ok("تحويل بالتعليق الصحيح يفعّل الاشتراك", DB.store["payments"][rt_["order_id"]]["status"] == "finished" and DB.store["payments"][rt_["order_id"]]["tx_hashes"] == ["hy"])
ru_ = c.post("/api/payments/create", json={"init_data": init_data(77), "package_id": "p1", "pay_currency": "usdtton"}).json()
gateway._TON_CACHE.clear(); JTX.append({"hash": "hj", "utime": int(time.time()), "amount": 12_000_000, "comment": ru_["payin_extra_id"], "source": "EQs"})
main.run_gateway_tick()
ok("USDT على TON بالتعليق", DB.store["payments"][ru_["order_id"]]["status"] == "finished")

# انتهاء المهلة + القبول المتأخر + الإغلاق بدفع ناقص وقرار الأدمن
add_user(88, status="approved", language="ar")
rl_ = c.post("/api/payments/create", json={"init_data": init_data(88), "package_id": "p1", "pay_currency": "trx"}).json()
ok("TRX بسعر السوق", rl_["display_amount"] == "48")
DEP88 = rl_["pay_address"]
DB.store["payments"][rl_["order_id"]]["expires_at"] = time.time() - 10
main.run_gateway_tick()
ok("انتهاء المهلة", DB.store["payments"][rl_["order_id"]]["status"] == "expired")
BAL[("trx", DEP88)] = 48_000_000
main.run_gateway_tick()
ok("دفعة متأخرة ضمن نافذة القبول تُفعَّل", DB.store["payments"][rl_["order_id"]]["status"] == "finished" and DB.store["payments"][rl_["order_id"]].get("late"))
add_user(89, status="approved", language="ar")
rb_ = c.post("/api/payments/create", json={"init_data": init_data(89), "package_id": "p1", "pay_currency": "usdttrc20"}).json()
BAL[("usdttrc20", rb_["pay_address"])] = 3_000_000
main.run_gateway_tick()
DB.store["payments"][rb_["order_id"]]["expires_at"] = time.time() - 49 * 3600
CALLS.clear(); main.run_gateway_tick()
ok("إغلاق بدفع ناقص بعد نافذة القبول + تنبيه الأدمن", DB.store["payments"][rb_["order_id"]]["status"] == "underpaid" and any("تحتاج قرارك" in x[1].get("text", "") for x in CALLS))
inv_ = c.get("/api/admin/gateway/invoices?status=underpaid").json()["rows"]
ok("قائمة الفواتير في اللوحة", len(inv_) == 1 and inv_[0]["received"] == "3" and inv_[0]["amount"] == "12")
ok("قبول يدوي من الأدمن يفعّل الاشتراك", c.post(f"/api/admin/gateway/invoices/{rb_['order_id']}/accept", json={"note": "agreed"}).status_code == 200
   and DB.store["payments"][rb_["order_id"]]["status"] == "finished" and DB.store["users"]["89"].get("subscription"))
ov2_ = c.get("/api/admin/gateway").json()
ok("نظرة عامة: الإحصاءات + خزان الغاز", ov2_["stats"]["finished_30d"] >= 5 and ov2_["gas"]["tron"]["address"] == GAS)
ok("قائمة عناوين الإيداع والتجميعات", len(c.get("/api/admin/gateway/addresses").json()["rows"]) >= 2 and len(c.get("/api/admin/gateway/sweeps").json()["rows"]) == 1)
CALLS.clear(); W({"message": {"chat": {"id": 555, "type": "private"}, "from": {"id": 555}, "text": "/gateway"}})
ok("ملخص البوابة في البوت للأدمن (/gateway)", "AW Pay" in CALLS[-1][1]["text"])
c.put("/api/admin/staff", json={"id": "7778", "role": "support", "name": "S"}); c.post("/api/admin/logout")
admin_access.invalidate(); admin_login(7778)
ok("صلاحيات: الدعم لا يصل لبوابة الدفع", c.get("/api/admin/gateway").status_code == 403)
c.post("/api/admin/logout"); admin_access.invalidate(); admin_login(555)
c.put("/api/admin/gateway", json={"enabled": False})
c.post("/api/admin/logout")

# ═════════ 38) التحليلات وتتبّع الزوار والأداء + البكسلات ═════════
TR = lambda uid, sid, events, **kw: c.post("/api/track", json={"init_data": init_data(uid) if uid else "", "sid": sid, "events": events, **kw},  # noqa: E731
                                           headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604.1"})
admin_login(555)
r = TR(301, "sess-aaaa-0001", [{"type": "session_start"}, {"type": "page_view", "page": "home"}, {"type": "event", "name": "checkout_open", "props": {"pkg": "p1", "x" * 40: "y" * 500}},
                               {"type": "perf", "props": {"ttfb": 120, "fcp": 800, "lcp": 1400, "load": 1600}}, {"type": "page_view", "page": "plans"}],
       device={"tg_platform": "ios", "tg_version": "8.0", "w": 390, "h": 844, "theme": "dark"}, source={"start_param": "c_summer"}, lang="ar")
ok("تتبّع: دفعة أحداث تُحفظ", r.status_code == 200 and r.json()["saved"] == 5)
s1 = DB.store["an_sessions"]["sess-aaaa-0001"]
ok("الجلسة: الجهاز والمصدر/الحملة والصفحات", s1["device"]["os"] == "iOS" and s1["device"]["platform"] == "ios" and s1["device"]["type"] == "mobile"
   and s1["source"] == {"src": "campaign", "campaign": "summer", "medium": "", "start_param": "c_summer"} and s1["pages"] == 2 and s1["entry"] == "home" and s1["exit"] == "plans")
ev_ = [e for e in DB.store["an_events"].values() if e["name"] == "checkout_open"][0]
ok("الخصائص مقيّدة الطول (لا تضخم)", all(len(k) <= 32 and len(str(v)) <= 120 for k, v in ev_["props"].items()))
ok("لا IP ولا بيانات دخول محفوظة", "init_data" not in json.dumps(DB.store["an_sessions"]) and "testclient" not in json.dumps(DB.store["an_sessions"]))
ok("اسم حدث غير صالح يُتجاهل", TR(301, "sess-aaaa-0001", [{"type": "event", "name": "<script>"}]).json()["saved"] == 0)
ok("معرّف جلسة لمستخدم آخر لا يُختطف", TR(302, "sess-aaaa-0001", [{"type": "page_view", "page": "x"}]).json()["saved"] == 0)
ok("زائر مجهول (خارج تلجرام) يُتتبّع بمعرّفه", TR(None, "sess-bbbb-0002", [{"type": "page_view", "page": "home"}], vid="anon-visitor-01").json()["saved"] == 1)
ok("بلا معرّف صالح يُرفض بصمت", TR(None, "x", [{"type": "page_view"}]).json()["saved"] == 0)
TR(303, "sess-cccc-0003", [{"type": "page_view", "page": "home"}, {"type": "event", "name": "purchase", "props": {"usd": 29}}])
DB.store["an_visitors"]["u303"]["first_day"] = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 8 * 86400))
DB.store["an_visitors"]["u303"]["days"] = [DB.store["an_visitors"]["u303"]["first_day"], time.strftime("%Y-%m-%d", time.gmtime())]
a_ = c.get("/api/admin/analytics", params={"days": 30}).json()
ok("المتواجدون الآن + DAU/WAU/MAU", a_["live"]["users"] == 3 and a_["active"]["dau"] == 3 and a_["active"]["mau"] == 3)
ok("المصادر والحملات والأجهزة واللغات", any(x["k"] == "campaign" for x in a_["sources"]) and a_["campaigns"][0]["k"] == "summer"
   and any(x["k"] == "iOS" for x in a_["os"]) and any(x["k"] == "ar" for x in a_["langs"]))
ok("أكثر الصفحات + التحويلات", a_["top_pages"][0]["k"] == "home" and a_["conversions"].get("purchase") == 1 and a_["conversions"].get("checkout_open") == 1)
ok("أداء التحميل من الأجهزة (p50)", a_["perf"]["lcp"]["p50"] == 1400)
ok("أداء الخادم: زمن كل مسار API", any(x["route"] == "POST /api/track" and x["p50"] is not None for x in a_["api"]))
ok("الاحتفاظ: أفواج أسبوعية D1/D7", any(row["size"] >= 1 and row["d7"] == 100.0 for row in a_["retention"]))
ok("سلسلة يومية للزوار والجدد", a_["series"][-1]["visitors"] == 3 and len(a_["series"]) == 30)
j_ = c.get("/api/admin/analytics/user/301").json()
ok("رحلة مستخدم كاملة", len(j_["sessions"]) == 1 and [e["type"] for e in j_["events"]].count("page_view") == 2 and j_["visitor"]["sessions"] == 1)
ok("بكسل بمعرّف غير صالح مرفوض", c.put("/api/admin/analytics/config", json={"meta_pixel": "abc<script>"}).status_code == 422)
ok("ضبط البكسلات من اللوحة", c.put("/api/admin/analytics/config", json={"meta_pixel": "123456789012345", "ga4_id": "G-ABC123XYZ", "retention_days": 7}).status_code == 200)
st_ = c.post("/api/status", json={"init_data": init_data(301)}).json()["settings"]
ok("التطبيق يستلم معرّفات البكسلات", st_["pixels"]["meta_pixel"] == "123456789012345" and st_["pixels"]["ga4_id"] == "G-ABC123XYZ" and st_["analytics"])
for e in DB.store["an_events"].values():
    e["at"] -= 8 * 86400
ok("تنظيف الأحداث بعد مدة الاحتفاظ", analytics.cleanup(DB) >= 1 and not DB.store["an_events"])
c.put("/api/admin/analytics/config", json={"enabled": False})
ok("إيقاف التتبّع من اللوحة", TR(301, "sess-aaaa-0009", [{"type": "page_view", "page": "home"}]).json()["saved"] == 0
   and c.post("/api/status", json={"init_data": init_data(301)}).json()["settings"]["pixels"] == {})
c.put("/api/admin/analytics/config", json={"enabled": True, "meta_pixel": "", "ga4_id": "", "retention_days": 90})
c.put("/api/admin/staff", json={"id": "7779", "role": "support", "name": "S2"}); c.post("/api/admin/logout")
admin_access.invalidate(); admin_login(7779)
ok("صلاحيات: الدعم يقرأ التحليلات ولا يعدّل البكسلات", c.get("/api/admin/analytics").status_code == 200 and c.put("/api/admin/analytics/config", json={"enabled": False}).status_code == 403)
c.post("/api/admin/logout"); admin_access.invalidate()

# ═════════ 39) بطاقات GIF المتحركة مع رسائل البوت ═════════
import cards  # noqa: E402
cards.CACHE_DIR = tempfile.mkdtemp()
ok("تصنيف الرسالة: هدية/عرض/اشتراك/دفعة/تذكير/دعم/تنبيه", [cards.classify(x) for x in (
    "🎁 هديتك جاهزة", "خصم 20% لفترة محدودة", "✅ تم تفعيل اشتراكك", "Payment received", "🔔 اشتراكك ينتهي غدًا", "💬 رد جديد على تذكرتك", "❌ فشل الدفع")]
   == ["gift", "offer", "package", "payment", "reminder", "support", "alert"])
sp_ = cards.spec_for("🎁 هديتك: خصم 15% صالح 48 ساعة", "ar")
ok("القيمة البارزة تُستخرج + عنوان ثابت لكل نوع (إعادة استخدام عالية)", sp_["hl"] == "15%" and sp_["title"] == "هدية خاصة لك"
   and cards.cache_key(sp_) == cards.cache_key(cards.spec_for("🎁 مرحبًا سارة، هديتك: خصم 15%", "ar")))
gif_ = cards.render(sp_)
from PIL import Image as _Img  # noqa: E402
import io as _io  # noqa: E402
im_ = _Img.open(_io.BytesIO(gif_))
ok("GIF متحرك بعدة إطارات ومقاس البطاقة", gif_[:6] == b"GIF89a" and im_.n_frames == cards.FRAMES and im_.size == (cards.W, cards.H) and len(gif_) < 2_000_000)
cards.RAQM, _raqm = False, cards.RAQM
ok("مسار بديل بلا libraqm (تشكيل + ترتيب يمين-يسار)", cards.render(cards.spec_for("💬 رد جديد", "ar"))[:6] == b"GIF89a" and cards._visual("abc 15%") == "abc 15%")
cards.RAQM = _raqm
UP, SENT = [], []
main._tg_upload = lambda method, params, field, path, mime: (UP.append((method, params, path)) or {"ok": True, "result": {"message_id": 1, "animation": {"file_id": "FID-1"}}})
_orig_call = main._tg_call
main._tg_call = lambda method, params: (SENT.append((method, params)) or {"ok": True, "result": {"message_id": 2}})
DB.store.setdefault("config", {}).pop("cards", None); main._CARDS_CFG["v"] = None
r_ = main.cards_send({"chat_id": 700, "text": "🎁 هديتك: خصم 15% صالح 48 ساعة", "parse_mode": "HTML", "reply_markup": {"inline_keyboard": []}, "disable_web_page_preview": True})
ok("أول رسالة: توليد البطاقة ورفعها مع النص تعليقًا", r_["ok"] and UP and UP[0][0] == "sendAnimation" and UP[0][1]["caption"].startswith("🎁") and UP[0][1]["parse_mode"] == "HTML"
   and "disable_web_page_preview" not in UP[0][1] and UP[0][2].endswith(".gif"))
main.cards_send({"chat_id": 701, "text": "🎁 مرحبًا علي، هديتك: خصم 15%"})
ok("الرسائل التالية تعيد استخدام file_id (بلا توليد ولا رفع)", len(UP) == 1 and SENT[-1][0] == "sendAnimation" and SENT[-1][1]["animation"] == "FID-1" and SENT[-1][1]["chat_id"] == 701)
ok("لا بطاقات للأدمن ولا القنوات ولا رسائل الدخول", main.cards_send({"chat_id": 555, "text": "🎁 x"}) is None and main.cards_send({"chat_id": -100999, "text": "🎁 x"}) is None
   and main.cards_send({"chat_id": 702, "text": "login token=abc"}) is None)
ok("نص أطول من حد التعليق يُرسل عاديًا", main.cards_send({"chat_id": 702, "text": "x" * 1200}) is None)
ok("تعطيل صريح لرسالة معيّنة", main.cards_send({"chat_id": 702, "text": "🎁 x", "_card": False}) is None)
ok("بطاقة مخصصة لرسالة معيّنة (نوع/عنوان/قيمة)", main.cards_send({"chat_id": 703, "text": "باقة VIP خاصة لك", "_card": {"kind": "package", "title": "باقة VIP خاصة", "hl": "$99"}})["ok"]
   and len(UP) == 2)
main._tg_upload = lambda *a: {"ok": False, "description": "boom"}
ok("فشل الرفع → الرجوع للرسالة النصية", main.cards_send({"chat_id": 704, "text": "⚠️ تنبيه جديد"}) is None)
main._tg_upload = lambda method, params, field, path, mime: (UP.append((method, params, path)) or {"ok": True, "result": {"message_id": 1, "animation": {"file_id": "FID-2"}}})
admin_login(555)
ok("اللوحة: الإعدادات + كتالوج الأنواع", len(c.get("/api/admin/cards").json()["catalog"]) == len(cards.KINDS))
c.put("/api/admin/cards", json={"kinds": {"gift": False}})
ok("تعطيل نوع من اللوحة", main.cards_send({"chat_id": 705, "text": "🎁 هدية"}) is None and main.cards_send({"chat_id": 705, "text": "🔔 تذكير"}) is not None)
pv_ = c.get("/api/admin/cards/preview", params={"text": "Payment received $29", "lang": "en"})
ok("معاينة البطاقة من اللوحة", pv_.status_code == 200 and pv_.headers["content-type"] == "image/gif" and pv_.headers["x-card-kind"] == "payment")
ok("مسح ذاكرة البطاقات", c.delete("/api/admin/cards/cache").json()["cleared"] >= 2 and not DB.store.get("card_files"))
c.put("/api/admin/cards", json={"enabled": False})
ok("إيقاف البطاقات كليًا", main.cards_send({"chat_id": 705, "text": "🔔 تذكير"}) is None)
c.post("/api/admin/logout")
main._tg_call = _orig_call

# ═════════ 40) Gemini: نماذج احتياطية عند الازدحام (503) ═════════
from retry import RetryableError  # noqa: E402
_orig_post = support._gemini_post
SEEN_M = []
def _fake_post(url, key, body):
    m = url.split("/models/")[1].split(":")[0]
    SEEN_M.append(m)
    if m == "gemini-flash-latest":
        raise RetryableError("HTTP 503")
    if m == "gemini-flash-lite-latest":
        raise support.ModelUnavailable("HTTP 404")
    return {"candidates": [{"content": {"role": "model", "parts": [{"text": f"OK from {m}"}]}}]}
support._gemini_post = _fake_post
os.environ["GEMINI_API_KEY"] = "AIza" + "t" * 35
support._GOOD_MODEL.update(m=None, until=0)
support.llm = REAL_LLM
cfg_ = {**support.DEFAULT_CONFIG, "fallback_models": ["gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]}
r_ = support.llm(cfg_, "sys", [{"role": "user", "parts": [{"text": "hi"}]}])
ok("503 على الأساسي و404 على الاحتياطي الأول → رد من الاحتياطي التالي", r_["parts"][0]["text"] == "OK from gemini-2.5-flash"
   and SEEN_M == ["gemini-flash-latest", "gemini-flash-lite-latest", "gemini-2.5-flash"])
SEEN_M.clear(); support.llm(cfg_, "sys", [{"role": "user", "parts": [{"text": "hi"}]}])
ok("الاحتياطي الناجح يُجرَّب أولًا لبضع دقائق (لا انتظار على الأساسي المزدحم)", SEEN_M == ["gemini-2.5-flash"])
support._gemini_post = lambda url, key, body: (_ for _ in ()).throw(RetryableError("HTTP 503"))
try:
    support.llm(cfg_, "sys", [{"role": "user", "parts": [{"text": "hi"}]}]); _failed = False
except support.AiError as e:
    _failed = "gemini-flash-latest" in str(e) and "gemini-2.5-flash-lite" in str(e)
ok("كل النماذج مزدحمة → خطأ واضح بكل المحاولات", _failed)
support._gemini_post = _orig_post
os.environ.pop("GEMINI_API_KEY", None)
support.add_message(DB, "THIST1", "user", "Hi")
support.add_message(DB, "THIST1", "notice", "✅ استلمنا طلبك — تذكرة #THIST1")
support.add_message(DB, "THIST1", "user", "")
support.add_message(DB, "THIST1", "notice", "🔔 تحديث التذكرة")
h_ = support._history(DB, "THIST1")
ok("سجل Gemini ينتهي دائمًا برسالة المستخدم وبلا نص فارغ (لا 400)", h_[-1]["role"] == "user" and all(p_.get("text", "x").strip() for c_ in h_ for p_ in c_["parts"]))
support._GOOD_MODEL.update(m=None, until=0)
admin_login(555)
ok("قائمة النماذج الاحتياطية من اللوحة (تحقق من الصيغة)", c.put("/api/admin/support/config", json={"fallback_models": "gemini-2.5-flash, gemini-2.5-flash-lite"}).json()["fallback_models"] == ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
   and c.put("/api/admin/support/config", json={"fallback_models": ["gpt-4"]}).status_code == 422)
c.post("/api/admin/logout")

# ═════════ 41) إحالة متقدمة + محفّزات المكافآت + رد ذكي على التقييم ═════════
import billing as _b  # noqa: E402
admin_login(555)
ok("إعدادات إحالة غير صالحة مرفوضة", c.put("/api/admin/settings", json={"referral_mode": "weird"}).status_code == 422
   and c.put("/api/admin/settings", json={"referral_milestones": [{"count": 3, "type": "hack", "value": 1}]}).status_code == 422)
r = c.put("/api/admin/settings", json={"referral_enabled": True, "referral_days": 5, "referral_tiers": [{"min": 0, "days": 7}], "referral_mode": "every",
                                       "referral_recurring_days": 2, "referral_min_usd": 10, "referral_monthly_cap": 2, "referral_friend_discount": 15,
                                       "referral_milestones": [{"count": 2, "type": "free_month", "value": 30, "hours": 48}], "referral_share_ar": "انضم عبر {link}"})
ok("حفظ إعدادات الإحالة المتقدمة", r.status_code == 200 and r.json()["referral_mode"] == "every" and r.json()["referral_milestones"][0]["type"] == "free_month")
st_ = c.post("/api/status", json={"init_data": init_data(42)}).json()["settings"]
ok("نص المشاركة المخصص يصل للتطبيق", st_["referral_share_ar"] == "انضم عبر {link}" and st_["referral_friend_discount"] == 15)
S_ = _b.get_settings(DB)
add_user(900, status="approved"); add_user(901, status="approved", referred_by="900"); add_user(902, status="approved", referred_by="900"); add_user(903, status="approved", referred_by="900")
exp0 = lambda u: float(((DB.store["users"][str(u)].get("subscription") or {}).get("expires_at")) or 0)  # noqa: E731
ok("أقل مبلغ: دفعة أقل من الحد لا تُحتسب", _b.referral_on_payment(DB, 901, S_, 5) is None and not DB.store["users"]["901"].get("referral_reward_granted"))
r1 = _b.referral_on_payment(DB, 901, S_, 29)
ok("أول دفعة: الصديق + المُحيل حسب المستوى", r1["first"] and r1["days"] == 7 and exp0(901) > time.time() + 4 * 86400 and exp0(900) > time.time() + 6 * 86400)
r2 = _b.referral_on_payment(DB, 901, S_, 29)
ok("وضع «كل دفعة»: أيام متكررة للمُحيل عن التجديد", r2 and not r2["first"] and r2["days"] == 2)
r3 = _b.referral_on_payment(DB, 902, S_, 29)
ok("الحد الشهري للمُحيل (2) + جائزة الإنجاز عند إحالتين مدفوعتين", r3["capped"] and r3["days"] == 0 and r3["milestone"]["count"] == 2)
ok("جائزة الإنجاز لا تتكرر", (_b.referral_on_payment(DB, 903, S_, 29) or {}).get("milestone") is None)
_b.update_settings(DB, {"referral_mode": "first"})
ok("وضع «أول دفعة فقط»: التجديد لا يُكافأ", _b.referral_on_payment(DB, 902, _b.get_settings(DB), 29) is None)
cf = c.put("/api/admin/rewards/config", json={"streak_days": 5, "max_pending": 2, "triggers": {"first_payment": True, "renewal": True, "link_real": True},
                                              "trigger_prizes": {"first_payment": [{"type": "free_days", "value": 9, "weight": 1, "enabled": True}]}})
ok("مكافآت: طول السلسلة + حد البطاقات + جدول جوائز لكل محفّز", cf.status_code == 200 and cf.json()["streak_days"] == 5 and cf.json()["trigger_prizes"]["first_payment"][0]["value"] == 9)
ok("محفّز غير معروف مرفوض", c.put("/api/admin/rewards/config", json={"trigger_prizes": {"hack": [{"type": "discount", "value": 5, "weight": 1}]}}).status_code == 422)
add_user(910, status="approved")
cid = rewards.grant_card(DB, 910, "first_payment")
ok("بطاقة أول دفعة تُمنح", cid == "910_first_payment")
rewards.grant_card(DB, 910, "renewal_o1")
ok("حد البطاقات المعلّقة (2) يمنع التكديس", rewards.grant_card(DB, 910, "renewal_o2") is None and len(DB.store["users"]["910"]["scratch_pending"]) == 2)
DB.store["users"]["910"].update(phone_verified=True)
cl_ = rewards.claim(DB, {"id": 910, "is_premium": True}, cid, "sec")
ok("جائزة البطاقة من جدول محفّزها الخاص", DB.store[rewards.CARDS][cid]["prize"] == {"type": "free_days", "value": 9})
c.post("/api/admin/logout")
support.llm_text = lambda cfg, system, prompt, max_tokens=400: "شكرًا يا أحمد على كلماتك الجميلة 🌟\nSUPPORT=no"
support.ai_available = lambda *a: True
DB.store.setdefault("config", {})["support"] = {"ai_enabled": True}; support.invalidate()
fb = c.post("/api/feedback", json={"init_data": init_data(911), "rating": 5, "message": "تطبيق رائع", "lang": "ar"}).json()
ok("رد ذكي على التقييم حسب الرسالة (بدون سطر التحكم)", fb["reply"] == "شكرًا يا أحمد على كلماتك الجميلة 🌟" and fb["suggest_support"] is False)
ok("منع إغراق التقييمات", c.post("/api/feedback", json={"init_data": init_data(911), "rating": 5}).status_code == 429)
support.llm_text = lambda *a, **k: (_ for _ in ()).throw(support.AiError("down"))
fb2 = c.post("/api/feedback", json={"init_data": init_data(912), "rating": 2, "message": "التطبيق لا يعمل", "lang": "ar"}).json()
ok("تعطل الذكاء: رد اعتذار جاهز + اقتراح فتح الدعم", "نعتذر" in fb2["reply"] and fb2["suggest_support"] is True)
admin_login(555)
af = c.get("/api/admin/support/feedback").json()
ok("اللوحة: سجل التقييمات + المتوسط والتوزيع", af["stats"]["count"] == 2 and af["stats"]["dist"]["5"] == 1 and af["rows"][0]["reply"])
c.post("/api/admin/logout")
support.ai_available = lambda *a: False

# ═════════ 42) استوديو التصميم + SEO + حالة النظام المفصّلة ═════════
import design  # noqa: E402
pub0 = c.get("/api/design").json()
ok("التصميم العام الافتراضي متاح بلا تسجيل دخول", pub0["tokens"]["dark"]["accent"] == "#ff8a00" and pub0["pages"]["home"]["blocks"][0]["id"] == "who")
ok("الاختصارات الافتراضية لا تكرر الشريط السفلي", not {x["id"] for x in pub0["pages"]["home"]["quick"]["items"]} & {"plans", "rewards", "referral", "analytics", "settings"})
admin_login(555)
ad = c.get("/api/admin/design").json()
ok("اللوحة: مسودة + كتالوج (أيقونات، عناصر، قوالب جاهزة)", "draft" in ad and "rocket" in ad["catalog"]["icons"] and "midnight_gold" in ad["catalog"]["presets"])
d_ = ad["draft"]
bad = json.loads(json.dumps(d_)); bad["tokens"]["dark"]["accent"] = "red;}"
ok("لون غير صالح مرفوض (لا حقن CSS)", c.put("/api/admin/design/draft", json={"design": bad}).status_code == 422)
bad = json.loads(json.dumps(d_)); bad["pages"]["home"]["blocks"].append({"id": "<script>", "visible": True})
ok("عنصر غير معروف مرفوض", c.put("/api/admin/design/draft", json={"design": bad}).status_code == 422)
bad = json.loads(json.dumps(d_)); bad["pages"]["nav"]["items"][0]["icon"] = "evil"
ok("أيقونة غير معتمدة مرفوضة", c.put("/api/admin/design/draft", json={"design": bad}).status_code == 422)
new = json.loads(json.dumps(d_))
new["tokens"]["dark"]["accent"] = "#22C55E"
new["pages"]["home"]["blocks"] = list(reversed(new["pages"]["home"]["blocks"]))
new["pages"]["home"]["blocks"][0]["visible"] = False
new["texts"]["ar"]["balance"] = "رصيدك <b>"
r = c.put("/api/admin/design/draft", json={"design": new}).json()["draft"]
ok("حفظ المسودة: ألوان + ترتيب بالسحب + إخفاء + نص مخصص (منقّى)", r["tokens"]["dark"]["accent"] == "#22c55e" and r["pages"]["home"]["blocks"][0]["id"] == "growth"
   and r["pages"]["home"]["blocks"][0]["visible"] is False and r["texts"]["ar"]["balance"] == "رصيدك b")
ok("المسودة لا تظهر للمستخدمين قبل النشر", c.get("/api/design").json()["tokens"]["dark"]["accent"] == "#ff8a00")
p1 = c.post("/api/admin/design/publish", json={"design": r, "note": "لون أخضر"}).json()
design._PUB["v"] = None
ok("النشر: يظهر للجميع + رقم إصدار", p1["version"] == 1 and c.get("/api/design").json()["tokens"]["dark"]["accent"] == "#22c55e")
r2 = json.loads(json.dumps(r)); r2["tokens"]["radius"] = 28
c.post("/api/admin/design/publish", json={"design": r2, "note": "زوايا"})
hist = c.get("/api/admin/design/history").json()["rows"]
ok("سجل التحديثات", [h["version"] for h in hist][:2] == [2, 1] and hist[1]["note"] == "لون أخضر")
rs = c.post(f"/api/admin/design/history/{hist[1]['id']}/restore").json()
design._PUB["v"] = None
ok("الرجوع عن تحديث (استرجاع إصدار سابق كإصدار جديد)", rs["version"] == 3 and c.get("/api/design").json()["tokens"]["radius"] == 14)
th = c.post("/api/admin/design/themes", json={"name": "صيف", "scopes": ["global", "home"], "tag": "موسمي"}).json()
ok("حفظ قالب لعدة صفحات (مجموعة قوالب)", set(th["scopes"]) == {"global", "home"} and "tokens" not in th["data"] and "dark" in th["data"]["global"])
c.post("/api/admin/design/presets/midnight_gold/apply")
ok("قالب جاهز يُطبَّق على المسودة", c.get("/api/admin/design").json()["draft"]["tokens"]["dark"]["accent"] == "#e5b84b")
ap = c.post(f"/api/admin/design/themes/{th['id']}/apply", json={"scopes": ["global"]}).json()["draft"]
ok("تطبيق قالب محفوظ (صفحة محددة من المجموعة)", ap["tokens"]["dark"]["accent"] == "#22c55e")
support.ai_available = lambda *a: True
support.llm_text = lambda cfg, system, prompt, max_tokens=400: json.dumps({"explanation": "زدت التباين", "patch": {"radius": 20, "card_style": "gradient"}})
ai_ = c.post("/api/admin/design/ai", json={"scope": "global", "question": "اجعلها أفخم"}).json()
ok("اقتراح الذكاء الاصطناعي: شرح + تعديل صالح قبل التطبيق", ai_["explanation"] == "زدت التباين" and ai_["preview"]["tokens"]["radius"] == 20)
support.llm_text = lambda *a, **k: json.dumps({"explanation": "x", "patch": {"dark": {"accent": "javascript:"}}})
ok("اقتراح ذكاء غير صالح يُرفض", c.post("/api/admin/design/ai", json={"scope": "global"}).status_code == 422)
support.llm_text = lambda *a, **k: '{"icon": "rocket", "alternatives": ["bolt", "evil"], "reason": "انطلاقة"}'
ic = c.post("/api/admin/design/ai-icon", json={"label": "الباقات", "current": "plans"}).json()
ok("رأي الذكاء في الأيقونة (من القائمة المعتمدة فقط)", ic["icon"] == "rocket" and ic["alternatives"] == ["bolt"])
support.ai_available = lambda *a: False
tmp_idx = os.path.join(tempfile.mkdtemp(), "index.html")
open(tmp_idx, "w").write("<html><head><!--aw-seo--><title>AW</title><!--/aw-seo--></head></html>")
design.write_seo(tmp_idx, {**design.default()["seo"], "title": 'AW "Pro" <x>', "og_image": "https://cdn.test/og.png"}, "https://example.test")
html_ = open(tmp_idx).read()
ok("SEO يُكتب في صفحة التطبيق (عنوان/وصف/OG/canonical) مع تهريب آمن", "<title>AW &quot;Pro&quot; &lt;x&gt;</title>" in html_ and 'og:image" content="https://cdn.test/og.png"' in html_ and "canonical" in html_)
bad = json.loads(json.dumps(d_)); bad["seo"]["og_image"] = "javascript:alert(1)"
ok("صورة SEO غير آمنة مرفوضة", c.put("/api/admin/design/draft", json={"design": bad}).status_code == 422)
main._st_nowpayments = lambda: {"status": "up"}
ss = c.get("/api/system/status").json()["services"]
ok("حالة النظام المفصّلة: كل الفروع", all(k in ss for k in ("api", "telegram", "scheduler", "sync", "gateway", "nowpayments", "ai", "storage", "errors", "analytics"))
   and ss["api"]["details"]["uptime_min"] >= 0 and "jobs" in ss["scheduler"])
c.post("/api/admin/logout")

# ═════════ 42) فريق الدعم: توزيع عادل، صلاحيات مفصّلة لكل عضو، أوضاع التحويل، مسودات الذكاء ═════════
reset(); admin_access.invalidate(); support.invalidate(); support._RL.clear()
admin_login(555)
AG = lambda id_, order, **kw: c.put("/api/admin/staff", json={"id": id_, "role": "support", "name": f"A{id_}", "agent": {"enabled": True, "order": order, **kw}})  # noqa: E731
for i_, (id_, o_) in enumerate((("7801", 1), ("7802", 2), ("7803", 3))):
    AG(id_, o_, available=(id_ != "7803"))
ok("عضو بصلاحيات مخصّصة + رؤية مقيّدة", c.put("/api/admin/staff", json={
    "id": "7804", "role": "support", "name": "Dina", "perms": {"support": "rw", "staff": "rw", "bogus": "rw"},
    "scope": {"tickets": "assigned", "hide_money": True, "hide_contacts": True}, "agent": {"enabled": True, "order": 4, "langs": ["ar"]}}).status_code == 200)
st_ = {m["id"]: m for m in c.get("/api/admin/staff").json()["members"]}
ok("صلاحية الفريق لا تُمنح للتعديل أبدًا + الأقسام المجهولة تُحذف", st_["7804"]["perms"] == {"support": "rw", "staff": "r"} and st_["7804"]["custom_perms"])
DB.store["config"]["support"] = {"handoff_mode": "instant", "assign_mode": "round_robin", "assign_by_skill": False, "notify_agent": True}; support.invalidate()
for u_ in (901, 902, 903, 904):
    add_user(u_, status="approved", live={"balance": 5000, "currency": "USD"})
CALLS.clear()
got = []
for u_ in (901, 902, 903, 904):
    SS(u_, "مشكلة في الاشتراك")
    got.append(support.open_ticket_for(DB, u_)["assigned_to"])
ok("وضع التحويل الفوري: كل تذكرة تذهب لموظف دون المساعد", all(support.open_ticket_for(DB, u_)["status"] == "escalated" for u_ in (901, 902, 903, 904)))
ok("توزيع بالترتيب وعادل ويتخطى غير المتاح", got == ["7801", "7802", "7804", "7801"])
ok("تنبيه فوري للموظف المسند إليه في البوت", any(str(p_.get("chat_id")) == "7802" and "أُسندت إليك" in p_.get("text", "") for m_, p_ in CALLS if m_ == "sendMessage"))
DB.store["config"]["support"]["assign_mode"] = "least_load"; support.invalidate()
ok("الأقل ضغطًا يختار من لديه أقل تذاكر مفتوحة", support.pick_agent(DB, support.get_config(DB), {"lang": "ar"})["id"] in ("7802", "7804"))
ok("مطابقة اللغة: موظف العربية فقط لا يستلم تذكرة إنجليزية", support.pick_agent(DB, {**support.get_config(DB), "assign_mode": "round_robin"}, {"lang": "en"})["id"] in ("7801", "7802"))
t903 = support.open_ticket_for(DB, 903)
c.post("/api/admin/logout"); admin_access.invalidate(); admin_login(7804)
me_ = c.get("/api/admin/me").json()
ok("العضو يرى صلاحياته المخصّصة فقط", me_["perms"] == {"support": "rw", "staff": "r"} and me_["scope"]["tickets"] == "assigned")
lst_ = c.get("/api/admin/support/tickets").json()
ok("يرى التذاكر المسندة إليه فقط + إخفاء رقم المستخدم", [r_["id"] for r_ in lst_["rows"]] == [t903["id"]] and lst_["rows"][0]["uid"].startswith("•••"))
ok("لا يفتح تذكرة زميله", c.get(f"/api/admin/support/tickets/{support.open_ticket_for(DB, 901)['id']}").status_code == 403)
det_ = c.get(f"/api/admin/support/tickets/{t903['id']}").json()
ok("إخفاء الأرصدة والمبالغ عنه", det_["context"]["live"]["balance"] == "•••")
ok("قسم غير مسموح مخفي تمامًا (المستخدمون)", c.get("/api/admin/users").status_code == 403)
ok("لا يعدّل الفريق حتى لو رأى صفحته", c.put("/api/admin/staff", json={"id": "7804", "role": "manager", "perms": {"staff": "rw"}}).status_code == 403)
ok("العضو المقيّد لا يعيد توزيع التذاكر", c.post(f"/api/admin/support/tickets/{t903['id']}/assign", json={"agent_id": "7801"}).status_code == 403)
ok("الموظف يبدّل توفّره بنفسه", c.post("/api/admin/support/agents/me", json={"available": False}).json()["agent"]["available"] is False)
ok("الرد من الموظف يصل للمستخدم", c.post(f"/api/admin/support/tickets/{t903['id']}/reply", json={"text": "مرحبًا، أتابع طلبك"}).status_code == 200
   and support.get_ticket(DB, t903["id"])["status"] == "in_progress")
c.post("/api/admin/logout"); admin_access.invalidate(); admin_login(555)
ok("غير المتاح لا يستلم جديدًا", "7804" not in {support.pick_agent(DB, {**support.get_config(DB), "assign_mode": "round_robin"}, {"lang": "ar"}, exclude=(x_,))["id"] for x_ in ("7801", "7802")})
SCRIPT.clear(); SCRIPT_SEEN.clear(); support.llm = fake_llm; support.ai_available = lambda *a: True
SS(903, "هل من جديد؟")
ok("بعد تدخل موظف: المساعد لا يرد، والموظف يُنبَّه فقط", not SCRIPT_SEEN and support.get_ticket(DB, t903["id"])["assigned_to"] == "7804")
ok("إعادة إسناد يدوية لموظف محدد", c.post(f"/api/admin/support/tickets/{t903['id']}/assign", json={"agent_id": "7802"}).json()["ticket"]["assigned_to"] == "7802")
ag_ = {r_["id"]: r_ for r_ in c.get("/api/admin/support/agents").json()["rows"]}
ok("لوحة الفريق: الحِمل وعدد الإسنادات لكل موظف", ag_["7802"]["active"] >= 2 and ag_["7801"]["assigned_total"] == 2)
t901 = support.open_ticket_for(DB, 901)
DB.store["support_tickets"][t901["id"]]["assigned_at"] = time.time() - 3600
DB.store["config"]["support"].update(reassign_after_min=10, assign_mode="round_robin"); support.invalidate()
ok("إعادة التوزيع التلقائية إن لم يرد الموظف خلال المهلة", support.reassign_stale(DB) >= 1 and support.get_ticket(DB, t901["id"])["assigned_to"] != "7801")
support.llm_text = lambda cfg, system, prompt, max_tokens=400: "مرحبًا، راجعت دفعتك وهي مؤكدة.\nملاحظة للموظف: تحقق من الفاتورة قبل الإرسال"
dr_ = c.post(f"/api/admin/support/tickets/{t901['id']}/draft").json()
ok("مسودة رد بالذكاء للموظف + ملاحظة داخلية", dr_["draft"].startswith("مرحبًا") and "الفاتورة" in dr_["note"])
c.delete("/api/admin/staff/7802")
ok("إزالة موظف تعيد تذاكره للتوزيع", all(support.get_ticket(DB, t_["id"])["assigned_to"] != "7802" for t_ in (t903, t901)))

# وضع «لا تحويل أبدًا»: المساعد يستمر، والتحويل بزر المستخدم فقط
DB.store["config"]["support"].update(handoff_mode="never", escalation_threshold=1); support.invalidate(); support._RL.clear()
ok("أداة التحويل لا تُعرض للمساعد في وضع never", "escalate_to_human" not in [t_["name"] for t_ in support.tools_for(support.get_config(DB))])
add_user(905, status="approved")
SCRIPT[:] = [G(txt("جرّب إعادة فتح التطبيق")), G(tool("escalate_to_human", {"summary": "x", "category": "general"})), G(txt("لنجرّب حلًا آخر")), G(txt("حل ثالث"))]
for m_ in ("لا يعمل", "ما زال لا يعمل", "لم ينجح"):
    SS(905, m_)
t905 = support.open_ticket_for(DB, 905)
ok("لا تحويل آلي أبدًا مهما تكررت المحاولات", t905["status"] != "escalated" and int(t905["ai_attempts"]) == 3)
ok("تعليمات الوضع تصل للمساعد", "Automatic transfer to humans is DISABLED" in support.MODE_NOTE["never"])
support.llm = lambda *a: (_ for _ in ()).throw(RuntimeError("provider down"))
SS(905, "مرحبا؟")
ok("تعطّل المساعد في وضع never: لا تحويل، ويُعرض زر الموظف", support.get_ticket(DB, t905["id"])["status"] != "escalated")
ok("زر «موظف» يبقى متاحًا ويُسند التذكرة", ACT(905, "human", t905["id"]).status_code == 200 and support.get_ticket(DB, t905["id"])["status"] == "escalated"
   and support.get_ticket(DB, t905["id"])["assigned_to"])
ok("وضع تحويل غير صالح يُرفض", c.put("/api/admin/support/config", json={"handoff_mode": "sometimes"}).status_code == 422)
cfg_r = c.put("/api/admin/support/config", json={"handoff_mode": "auto", "assign_mode": "least_load", "reassign_after_min": 99999}).json()
ok("حفظ أوضاع التحويل والتوزيع مع حدود آمنة", cfg_r["handoff_mode"] == "auto" and cfg_r["assign_mode"] == "least_load" and cfg_r["reassign_after_min"] == 1440)
ok("تصنيف تلقائي للتذكرة (للتخصص)", support.guess_category("دفعت عبر TON ولم يتفعل") == "payments" and support.guess_category("مشكلة في ربط حساب MT5") == "account")
support.llm = REAL_LLM; support.ai_available = lambda *a: False
c.post("/api/admin/logout")

print("\nALL BACKEND CHECKS PASSED")
