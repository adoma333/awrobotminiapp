"""اختبارات القاعدة المحلية (SQLite) ونقل البيانات من Firebase: python test_localdb.py"""
import os
import random
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import localdb  # noqa: E402
from google.cloud.firestore_v1.base_query import FieldFilter  # noqa: E402

N = {"pass": 0}


def ok(name, cond):
    assert cond, name
    N["pass"] += 1
    print("PASS", name)


# القاعدة الوهمية نفسها التي تُختبر عليها كل منطق المشروع (من test_backend.py) — مرجع المقارنة
src = open(os.path.join(HERE, "test_backend.py"), encoding="utf-8").read()
fake_ns = {}
exec(src[: src.index("DB = FakeDB()")], fake_ns)  # noqa: S102
fake_ns["SERVER_TS"] = localdb.SERVER_TIMESTAMP


tmp = tempfile.mkdtemp()
L = localdb.Client(os.path.join(tmp, "t.db"))

# ───────── أساسيات ─────────
u = L.collection("users").document("42")
u.set({"name": "A", "sub": {"exp": 5, "pkg": "p1"}, "tags": [1, 2]})
u.set({"sub": {"exp": 9}, "x": None}, merge=True)
d = u.get().to_dict()
ok("set + merge متداخل", d == {"name": "A", "sub": {"exp": 9, "pkg": "p1"}, "tags": [1, 2], "x": None})
u.update({"sub.pkg": "p2", "live.balance": 10.5})
d = u.get().to_dict()
ok("update بمسارات النقاط", d["sub"] == {"exp": 9, "pkg": "p2"} and d["live"] == {"balance": 10.5})
u.set({"at": localdb.SERVER_TIMESTAMP}, merge=True)
at = u.get().to_dict()["at"]
ok("SERVER_TIMESTAMP → datetime UTC", isinstance(at, datetime) and at.tzinfo is not None and abs(at.timestamp() - datetime.now(timezone.utc).timestamp()) < 5)
ok("مستند غير موجود", not L.collection("users").document("nope").get().exists)
L.collection("c").document("k").create({"v": 1})
try:
    L.collection("c").document("k").create({"v": 2})
    ok("create مكرر يُرفض", False)
except localdb.AlreadyExists:
    ok("create مكرر يُرفض (AlreadyExists)", L.collection("c").document("k").get().to_dict() == {"v": 1})
L.collection("c").document("k").delete()
ok("delete", not L.collection("c").document("k").get().exists)
a = L.collection("auto").document()
ok("معرّف تلقائي", len(a.id) == 20)

# ───────── مقارنة تفاضلية مع القاعدة الوهمية ─────────
F = fake_ns["FakeDB"]()
rnd = random.Random(7)
statuses = ["approved", "pending", None, "rejected"]
for i in range(300):
    col = rnd.choice(["d_users", "d_payments"])
    id_ = str(rnd.randint(1, 40))
    op = rnd.random()
    data = {"status": rnd.choice(statuses), "n": rnd.randint(0, 9), "m": {"a": rnd.randint(0, 3)}}
    if rnd.random() < 0.3:
        data.pop("status")
    if op < 0.5:
        merge = rnd.random() < 0.5
        F.collection(col).document(id_).set(data, merge=merge)
        L.collection(col).document(id_).set(data, merge=merge)
    elif op < 0.65:
        F.collection(col).document(id_).delete()
        L.collection(col).document(id_).delete()
    elif op < 0.8 and L.collection(col).document(id_).get().exists:
        F.collection(col).document(id_).update({"m.b": i})
        L.collection(col).document(id_).update({"m.b": i})


def snap_rows(q):
    return sorted((s.id, repr(sorted((s.to_dict() or {}).items()))) for s in q.stream())


same = True
for col in ("d_users", "d_payments"):
    for s in [x for x in statuses if x is not None]:  # "== None" غير مستخدم في المشروع (والقاعدة الوهمية تخالف Firestore فيه)
        same &= snap_rows(F.collection(col).where(filter=FieldFilter("status", "==", s))) == snap_rows(L.collection(col).where(filter=FieldFilter("status", "==", s)))
    same &= snap_rows(F.collection(col).where(filter=FieldFilter("status", "!=", None))) == snap_rows(L.collection(col).where(filter=FieldFilter("status", "!=", None)))
    same &= snap_rows(F.collection(col)) == snap_rows(L.collection(col))
    fo = [s.id for s in F.collection(col).order_by("n", direction="DESCENDING").limit(5).stream()]
    lo = [s.id for s in L.collection(col).order_by("n", direction="DESCENDING").limit(5).stream()]
    same &= [F.collection(col).document(i).get().to_dict()["n"] for i in fo] == [L.collection(col).document(i).get().to_dict()["n"] for i in lo]
ok("300 عملية عشوائية: نتائج مطابقة للقاعدة التي اختُبر عليها المشروع", same)
ok("where بسلسلة أمثلة + select", len(list(L.collection("users").where("status", "==", "approved").select(["n"]).stream())) == len(
    list(F.collection("users").where("status", "==", "approved").stream())))

# ───────── التزامن (الخادم + المزامنة معًا) ─────────
C = L.collection("cnt").document("x")
C.set({"v": 0})


def bump(k):
    for j in range(50):
        C.set({f"t{k}": {str(j): True}}, merge=True)


ths = [threading.Thread(target=bump, args=(k,)) for k in range(4)]
[t.start() for t in ths]
[t.join() for t in ths]
ok("كتابات متزامنة من 4 خيوط بلا فقدان", all(len(C.get().to_dict()[f"t{k}"]) == 50 for k in range(4)))
code = "import sys;sys.path.insert(0,%r);import localdb;c=localdb.Client(%r)\nfor j in range(100): c.collection('mp').document(sys.argv[1]+str(j)).set({'j':j})" % (HERE, L.path)
procs = [subprocess.Popen([sys.executable, "-c", code, str(k)]) for k in range(3)]
ok("3 عمليات منفصلة تكتب نفس الملف معًا", all(p.wait() == 0 for p in procs) and len(list(L.collection("mp").stream())) == 300)
L.backup(os.path.join(tmp, "bk.db"))
ok("نسخة احتياطية متسقة أثناء العمل", len(list(localdb.Client(os.path.join(tmp, "bk.db")).collection("mp").stream())) == 300)

# ───────── النقل من Firebase ─────────
import migrate_sqlite  # noqa: E402


class FSnap:
    def __init__(self, id_, d):
        self.id, self._d = id_, d

    def to_dict(self):
        return self._d


class FCol:
    def __init__(self, fdb, name):
        self.fdb, self.id = fdb, name

    def stream(self):
        self.fdb.reads[self.id] = self.fdb.reads.get(self.id, 0) + 1
        if self.id in self.fdb.fail:
            raise Exception("429 Quota exceeded.")
        return iter(FSnap(k, v) for k, v in self.fdb.data[self.id].items())


class FDB:
    def __init__(self, data):
        self.data, self.fail, self.reads = data, set(), {}

    def collections(self):
        return [FCol(self, n) for n in self.data]

    def collection(self, n):
        return FCol(self, n)


ts = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
src_data = {
    "users": {str(i): {"nickname": f"u{i}", "status": "approved", "subscription": {"expires_at": 1.8e9, "package_id": "p1"},
                       "decided_at": ts, "tags": ["a", {"b": 1}]} for i in range(250)},
    "payments": {f"o{i}": {"uid": i, "status": "finished", "amount_usd": 12.0} for i in range(120)},
    "config": {"settings": {"maintenance": False, "referral_tiers": [{"min": 0, "days": 7}]}},
    "audit_log": {f"a{i}": {"at": 1.7e9 + i} for i in range(500)},
}
fdb = FDB(src_data)
fdb.fail = {"audit_log"}
final = os.path.join(tmp, "prod", "aw.db")
try:
    migrate_sqlite.migrate(fdb, final, log=lambda *_: None)
    ok("توقف عند نفاد حد Firebase", False)
except Exception as e:  # noqa: BLE001
    ok("توقف عند نفاد حد Firebase (دون اعتماد نسخة ناقصة)", migrate_sqlite.is_quota(e) and not os.path.exists(final))
fdb.fail = set()
res = migrate_sqlite.migrate(fdb, final, log=lambda *_: None)
ok("الاستئناف يكمل دون إعادة قراءة ما نُقل", fdb.reads == {"users": 1, "payments": 1, "config": 1, "audit_log": 2})
ok("عدد المستندات مطابق لكل مجموعة", res == {"users": 250, "payments": 120, "config": 1, "audit_log": 500})
M = localdb.Client(final)
u7 = M.collection("users").document("7").get().to_dict()
ok("البيانات كما هي (تواريخ + قوائم + خرائط متداخلة)", u7 == src_data["users"]["7"])
ok("الاستعلامات تعمل على البيانات المنقولة", len(list(M.collection("users").where(filter=FieldFilter("status", "==", "approved")).stream())) == 250)
ok("ملف واحد مكتمل بلا بقايا مؤقتة", not any(f.endswith((".migrating", ".migrating-wal")) for f in os.listdir(os.path.dirname(final))))

# ───────── وحدات المشروع الحقيقية على SQLite ─────────
import billing  # noqa: E402

R = localdb.Client(os.path.join(tmp, "app.db"))
billing.update_settings(R, {"maintenance": True, "referral_days": 9})
ok("billing: الإعدادات", billing.get_settings(R)["maintenance"] is True and billing.get_settings(R)["referral_days"] == 9)
R.collection("packages").document("b").set({"name_ar": "ب", "price_usd": 20, "duration_days": 30, "active": True, "sort_order": 2})
R.collection("packages").document("a").set({"name_ar": "أ", "price_usd": 10, "duration_days": 30, "active": True, "sort_order": 1})
ok("billing: الباقات مرتبة", [p["id"] for p in billing.list_packages(R, active_only=True)] == ["a", "b"])
billing.extend_subscription(R, 42, {"id": "a", "name_ar": "أ", "name_en": "A", "duration_days": 30})
sub = R.collection("users").document("42").get().to_dict()["subscription"]
ok("billing: تفعيل الاشتراك", sub["package_id"] == "a" and sub["expires_at"] > datetime.now().timestamp() + 29 * 86400)

# ───────── الخادم الكامل (main.py) يعمل على SQLite ─────────
import hashlib, hmac, json, time  # noqa: E401,E402
from urllib.parse import urlencode  # noqa: E402

APP_DB = os.path.join(tmp, "server", "aw.db")
os.environ.update(DB_BACKEND="sqlite", DB_PATH=APP_DB, BOT_TOKEN="123:TEST", CHANNEL_ID="-100", WEBHOOK_SECRET="s", ADMIN_IDS="555",
                  WEBAPP_URL="https://example.test", ADMIN_SESSION_SECRET="j", MT5_LOCK_PATH=os.path.join(tmp, "l.lock"))
S = localdb.Client(APP_DB)  # بيانات كما بعد النقل
S.collection("users").document("42").set({"status": "approved", "nickname": "Ali", "language": "ar", "mt5_login": 5123, "mt5_server": "X",
                                          "subscription": {"expires_at": time.time() + 10 * 86400, "package_id": "a", "package_name_ar": "أ"},
                                          "decided_at": datetime(2026, 9, 1, tzinfo=timezone.utc), "referral_code": "AB12CD"})
S.collection("packages").document("a").set({"name_ar": "أ", "name_en": "A", "price_usd": 12, "duration_days": 30, "active": True, "sort_order": 1})
import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

main.tg = lambda method, **p: {"ok": True, "result": {"username": "awbot"}}


def init_data(uid=42):
    p = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "Ali", "language_code": "ar"})}
    chk = "\n".join(f"{k}={v}" for k, v in sorted(p.items()))
    sec = hmac.new(b"WebAppData", b"123:TEST", hashlib.sha256).digest()
    p["hash"] = hmac.new(sec, chk.encode(), hashlib.sha256).hexdigest()
    return urlencode(p)


cl = TestClient(main.app, base_url="https://testserver")
ok("الخادم يستخدم SQLite فعلًا", isinstance(main.db, localdb.Client) and main.db.path == APP_DB)
st = cl.post("/api/status", json={"init_data": init_data(42)}).json()
ok("/api/status: المستخدم المنقول يظهر مربوطًا باشتراكه (لا شاشة لغة)", st["status"] == "approved" and st["subscription"]["active"] and st["account"]["login"] == 5123)
st2 = cl.post("/api/status", json={"init_data": init_data(99)}).json()
ok("/api/status: مستخدم جديد", st2["status"] == "none")
ok("/api/packages", [p["id"] for p in cl.get("/api/packages").json()["packages"]] == ["a"])
ok("آخر ظهور يُكتب في SQLite", S.collection("users").document("42").get().to_dict().get("last_seen", 0) > 0)

print(f"\nALL LOCALDB CHECKS PASSED ({N['pass']})")
