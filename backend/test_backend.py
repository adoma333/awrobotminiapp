"""اختبارات الباك اند (بلا Firebase ولا تلجرام ولا MT5 حقيقية): python test_backend.py"""
import hashlib
import hmac
import json
import os
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
        return Query(self.store, self.name, self.filters, n, self.order)

    def order_by(self, field):
        return Query(self.store, self.name, self.filters, self.lim, field)

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
                elif name == "IS_NOT_NULL":
                    good &= has and cur is not None
                elif name == "IS_NULL":
                    good &= (not has) or cur is None
                else:
                    raise AssertionError(f"عامل استعلام غير مدعوم في القاعدة الوهمية: {name}")
            if good:
                rows.append(Snap(id_, d))
        if self.order:
            rows.sort(key=lambda r: (r.to_dict().get(self.order) is None, r.to_dict().get(self.order)))
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
main.get_logo_file_id = lambda: None
c = TestClient(main.app, base_url="https://testserver")


def ok(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    assert cond, name


def init_data(uid=42, token="123:TEST", age=0, lang="ar"):
    user = json.dumps({"id": uid, "first_name": "Ali", "username": "ali_x", "language_code": lang})
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
ok("بلا اشتراك → 402 subscription_required", r.status_code == 402 and r.json()["detail"] == "subscription_required")
add_user(42, subscription={"expires_at": time.time() - 5})
ok("اشتراك منتهٍ → 402", c.post("/api/register", json=BODY()).status_code == 402)

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
ok("الجلسة تعمل (JWT بـ sub نصّي)", c.get("/api/admin/me").json() == {"admin_id": 555})
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

print("\nALL BACKEND CHECKS PASSED")
