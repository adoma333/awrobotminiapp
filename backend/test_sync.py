"""اختبارات منطق المزامنة (بدون MT5 ولا Firebase): python test_sync.py"""
import copy
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import sync_worker as sw

UTC = ZoneInfo("UTC")
NOW = int(datetime(2026, 9, 19, 12, 30, tzinfo=timezone.utc).timestamp())


def ts(y, m, d, h=0, mi=0):
    return int(datetime(y, m, d, h, mi, tzinfo=timezone.utc).timestamp())


def deal(ticket, t, typ, entry, profit=0.0, commission=0.0, swap=0.0, fee=0.0):
    return dict(ticket=ticket, time=t, type=typ, entry=entry, profit=profit,
                commission=commission, swap=swap, fee=fee)


DEALS = [
    deal(1, ts(2026, 9, 1), 2, 0, profit=10000),              # إيداع
    deal(2, ts(2026, 9, 10), 0, 0, commission=-1),            # دخول
    deal(3, ts(2026, 9, 10, 1), 1, 1, profit=50),             # خروج رابح
    deal(4, ts(2026, 9, 11), 1, 0, commission=-1),
    deal(5, ts(2026, 9, 11, 1), 0, 1, profit=-20),            # خروج خاسر
    deal(6, ts(2026, 9, 19, 9), 0, 0, commission=-1),         # اليوم
    deal(7, ts(2026, 9, 19, 10), 1, 1, profit=30),            # اليوم رابح
    deal(8, ts(2026, 9, 19, 11), 2, 0, profit=-500),          # سحب اليوم
]


def ok(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    assert cond, name


# ───────────── 1) الحسابات ─────────────
s = sw.apply_deals(sw.empty_stats(), DEALS, UTC, NOW)
ok("إيداع/سحب", s["deposits"] == 10000 and s["withdrawals"] == 500)
ok("ربح التداول الكلي = 57", abs(s["trading_pnl"] - 57) < 1e-9)
ok("ربح اليوم = 29 (يشمل عمولة الدخول)", abs(s["day_pnl"] - 29) < 1e-9)
ok("الرابحة 2 والخاسرة 1", s["wins"] == 2 and s["losses"] == 1)

acc = {"balance": 9557.0}
r = sw.build_report(acc, s)
ok("النمو اليومي 0.30%", r["daily_growth_pct"] == 0.3)
ok("النمو الإجمالي 0.60% (بعد استبعاد السحب)", r["total_growth_pct"] == 0.6)
ok("نسبة الربح 66.67%", r["win_rate"] == 66.67)
ok("ربح الأسبوع 29 والشهر 57", r["weekly_pnl"] == 29 and r["monthly_pnl"] == 57)
ok("النمو الأسبوعي والشهري", r["weekly_growth_pct"] == 0.3 and r["monthly_growth_pct"] == 0.6)
ok("متوسط الربح 40 والخسارة 20 والنسبة 2", r["avg_win"] == 40 and r["avg_loss"] == 20 and r["payoff_ratio"] == 2.0)
ok("عامل الربح 4 والتوقّع 20 للصفقة", r["profit_factor"] == 4.0 and r["expectancy"] == 20.0)
ok("أفضل صفقة 50 وأسوأ -20", r["best_trade"] == 50 and r["worst_trade"] == -20)
ok("أقصى تراجع 22 (0.23%)", r["max_drawdown"] == 22 and r["max_drawdown_pct"] == 0.23)

s2 = sw.apply_deals(s, DEALS, UTC, NOW)
ok("التكرار لا يضاعف الأرقام", s2 == s)

extra = DEALS + [deal(9, ts(2026, 9, 19, 11), 1, 1, profit=10),   # نفس ثانية آخر صفقة
                 deal(10, ts(2026, 9, 19, 12), 0, 1, profit=-5)]
s3 = sw.apply_deals(s, extra, UTC, NOW)
ok("صفقة بنفس الثانية تُحتسب مرة واحدة", s3["wins"] == 3 and s3["losses"] == 2)
ok("ربح اليوم بعد الإضافة = 34", abs(s3["day_pnl"] - 34) < 1e-9)

s4 = sw.apply_deals(s3, [], UTC, ts(2026, 9, 20, 0, 5))
ok("عند تغيّر اليوم تُصفَّر عدّادات اليوم فقط", s4["day_pnl"] == 0 and s4["wins"] == 3 and s4["week_pnl"] == s3["week_pnl"])
s5 = sw.apply_deals(s3, [], UTC, ts(2026, 9, 21, 0, 5))
ok("الاثنين: يبدأ أسبوع جديد ويبقى الشهر", s5["week_pnl"] == 0 and s5["month_pnl"] == s3["month_pnl"])

# ───────────── 2) المبدّل الديناميكي ─────────────
class Clock:
    t = 100000.0
    def __call__(self):
        return self.t


class FakeStore:
    ts = "TS"
    def __init__(self):
        self.docs = {}
    def add(self, uid, status="approved", sync=None, login="111111"):
        self.docs[uid] = {"status": status, "language": "ar", "mt5_login": login,
                          "mt5_password": "x", "mt5_server": "S", **({"sync": sync} if sync else {})}
    def approved(self):
        return [(u, d.get("sync") or {}, (d.get("stats") or {}).get("v"))
                for u, d in self.docs.items() if d["status"] == "approved"]
    def new_ids(self):
        return [u for u, d in self.docs.items()
                if d["status"] == "approved" and (d.get("sync") or {}).get("state") == "new"]
    def get(self, uid):
        return copy.deepcopy(self.docs.get(uid))
    def update(self, uid, fields):
        for k, v in fields.items():
            cur = self.docs[uid]
            *path, last = k.split(".")
            for p in path:
                cur = cur.setdefault(p, {})
            cur[last] = v


class FakeClient:
    def __init__(self, clock, work=10.0):
        self.calls, self.clock, self.work, self.script = [], clock, work, {}
    def fetch(self, login, password, server, since, now):
        self.calls.append(login)
        self.clock.t += self.work
        step = self.script.get(login)
        if isinstance(step, Exception):
            raise step
        return {"account": {"login": login, "balance": 9557.0, "equity": 9560.0, "profit": 3.0,
                            "margin": 0, "margin_free": 9560.0, "margin_level": 0,
                            "credit": 0, "leverage": 500, "currency": "USD"},
                "deals": DEALS}


class FakeBridge:
    def __init__(self):
        self.up, self.log, self.fail_start = False, [], False
    def is_up(self): return self.up
    def start(self):
        if self.fail_start:
            raise sw.Mt5Error(-10004, "bridge did not open its port in 60s", "transient")
        if not self.up:
            self.up = True; self.log.append("start")
    def stop(self): self.up = False; self.log.append("stop")
    def restart(self): self.log.append("restart")


class FakeNotifier:
    def __init__(self):
        self.users, self.admins = [], []
    def user(self, uid, text): self.users.append((uid, text))
    def admin(self, text): self.admins.append(text)


def make(uids=("a", "b", "c")):
    cfg = sw.load_config()
    cfg.jitter, cfg.interval, cfg.min_gap, cfg.load_factor = 0.0, 3600, 5.0, 0.5
    clock, store = Clock(), FakeStore()
    for u in uids:
        store.add(u, login=u * 6)
    client, notif = FakeClient(clock), FakeNotifier()
    w = sw.Worker(cfg, store, client, notif, clock=clock, bridge=FakeBridge())
    sw.mem_available_mb = lambda: 4000
    sw.load_per_core = lambda: 0.1
    sw.psi = lambda r: 5.0
    return w, store, client, notif, clock


# التناوب: كل tick يعالج حسابًا واحدًا فقط، والترتيب يدور
w, store, client, notif, clock = make()
for _ in range(3):
    w.tick()
ok("حساب واحد في كل دورة والكل يُخدَّم", client.calls == ["aaaaaa", "bbbbbb", "cccccc"])
ok("تُكتب الأرقام الحية والتقرير", store.docs["a"]["live"]["balance"] == 9557.0
   and store.docs["a"]["report"]["win_rate"] == 66.67 and store.docs["a"]["sync"]["state"] == "ok")
sleep_idle = w.tick()
ok("لا شيء مستحق: ينام دون عمل (≤ فترة الفحص)", len(client.calls) == 3 and sleep_idle <= w.cfg.poll_new)
clock.t += 3700
for _ in range(3):
    w.tick()
ok("الدورة التالية بالترتيب نفسه (الأقدم أولًا)", client.calls[3:] == ["aaaaaa", "bbbbbb", "cccccc"])

# الراحة الديناميكية تتناسب مع زمن العمل
w, store, client, notif, clock = make(("a",))
client.work = 40.0
ok("الراحة = نصف زمن العمل (20ث)", w.tick() == 20.0)
w, store, client, notif, clock = make(("a",))
client.work = 2.0
ok("وحد أدنى للراحة 5ث", w.tick() == 5.0)

# حساب جديد بعد ✅ يقفز أمام الآخرين
w, store, client, notif, clock = make(("a", "b"))
w.tick(); w.tick()
clock.t += 3700  # الحسابان مستحقان
store.add("n", sync={"state": "new"}, login="nnnnnn")
clock.t += 40
client.calls.clear()
w.tick()
ok("الحساب الجديد يُخدَّم أولًا", client.calls == ["nnnnnn"])

# حماية الذاكرة
w, store, client, notif, clock = make(("a",))
sw.mem_available_mb = lambda: 50
d = w.tick()
ok("ذاكرة قليلة: لا يبدأ حسابًا", d == 30.0 and client.calls == [])
sw.mem_available_mb = lambda: 4000

# فشل التوثيق: يوقف ويُعيد الطلب للمستخدم فقط إذا كان الترمنال سليمًا
w, store, client, notif, clock = make(("a", "bad"))
client.script["bad" * 6] = sw.Mt5Error(-6, "Authorization failed", "auth")
w.tick(); w.tick()               # a ينجح، bad يفشل (1)
ok("بعد فشل واحد: تراجع 120ث وبقاء الحساب مقبولًا",
   w.queue["bad"].fails == 1 and abs(w.queue["bad"].next_due - (clock.t + 120)) <= 10
   and store.docs["bad"]["status"] == "approved")
for _ in range(8):
    if "bad" not in w.queue:
        break
    clock.t += 3000
    w.tick()
ok("بعد 3 فشول توثيق: يُرفض ليعدّل بياناته", store.docs["bad"]["status"] == "rejected"
   and "bad" not in w.queue and notif.users and notif.admins)

# لا يُرفض أحد إن لم ينجح أي حساب (الخلل غالبًا في الترمنال)
w, store, client, notif, clock = make(("bad",))
client.script["bad" * 6] = sw.Mt5Error(-6, "Authorization failed", "auth")
for _ in range(5):
    clock.t += 3000
    w.tick()
ok("ترمنال غير سليم: لا رفض للمستخدم", store.docs["bad"]["status"] == "approved"
   and len(notif.admins) == 1 and not notif.users)

# أعطال عابرة: تراجع تدريجي ثم إعادة تشغيل الجسر مرة واحدة
w, store, client, notif, clock = make(("a", "b", "c"))
restarts = []
w.maybe_restart_bridge = lambda now: restarts.append(now) if w.transient_streak >= 3 else None
for u in ("aaaaaa", "bbbbbb", "cccccc"):
    client.script[u] = sw.Mt5Error(-10004, "No IPC connection", "transient")
for _ in range(3):
    w.tick()
ok("3 أعطال متتالية تُطلق إعادة تشغيل الجسر", len(restarts) >= 1)
ok("لا يُرفض أحد بسبب أعطال عابرة", all(d["status"] == "approved" for d in store.docs.values()))

# حساب بإحصاءات بصيغة قديمة يُحدَّث فورًا ولو كان دوره بعيدًا
w, store, client, notif, clock = make(("a",))
store.docs["a"]["sync"] = {"state": "ok", "next_due": clock.t + 99999}
store.docs["a"]["stats"] = {"v": 1, "wins": 999}
w.tick()
ok("صيغة قديمة: تُعاد القراءة فورًا من الصفر",
   client.calls == ["aaaaaa"] and store.docs["a"]["stats"]["v"] == sw.STATS_VERSION
   and store.docs["a"]["stats"]["wins"] == 2)

# حساب لم يعد مقبولًا يخرج من القائمة
w, store, client, notif, clock = make(("a", "b"))
w.tick()
store.docs["b"]["status"] = "rejected"
w.last_refresh = -1e12
w.tick()
ok("الحساب غير المقبول يُزال من الدوران", "b" not in w.queue)

print("\nكل الاختبارات نجحت ✅")

# ───────────── الترمنال عند الطلب + PSI + شرط الرفض الأشدّ ─────────────
w, store, client, notif, clock = make(("a",))
w.tick()
ok("يُشغَّل الجسر قبل أول حساب", w.bridge.log[:1] == ["start"])
ok("يُطفأ بعد الانتهاء لأن الدور القادم بعد ساعة", w.bridge.log[-1] == "stop" and not w.bridge.up)
clock.t += 3500
w.tick()
ok("لا يُشغَّل قبل موعد الحساب", w.bridge.log == ["start", "stop"] and len(client.calls) == 1)
clock.t += 200
w.tick()
ok("يُشغَّل من جديد عند حلول الدور ثم يُطفأ", w.bridge.log == ["start", "stop", "start", "stop"] and len(client.calls) == 2)

w, store, client, notif, clock = make(("a", "b"))
w.cfg.interval = 200                       # حسابان دورهما قريب (أقل من idle_stop)
w.tick()
ok("يبقى شغّالًا إن كان الدور القادم قريبًا", w.bridge.up and w.bridge.log == ["start"])

w, store, client, notif, clock = make(("a",))
w.bridge.fail_start = True
w.tick()
ok("فشل تشغيل الجسر يُعامل كعطل عابر لا كخطأ مستخدم",
   store.docs["a"]["sync"]["state"] == "error" and store.docs["a"]["status"] == "approved" and client.calls == [])

# حماية الضغط تعتمد PSI لا متوسط الحِمل
w, store, client, notif, clock = make(("a",))
sw.psi = lambda r: 95.0
ok("ضغط PSI مرتفع: يؤجّل", w.tick() == 30.0 and client.calls == [])
sw.load_per_core = lambda: 9.0             # الحِمل عالٍ لكن PSI هادئ (حالة سيرفرك)
sw.psi = lambda r: 20.0
w.tick()
ok("حِمل عالٍ بسبب انتظار القرص فقط لا يمنع العمل", client.calls == ["aaaaaa"])
sw.load_per_core = lambda: 0.1
sw.psi = lambda r: 5.0

# لا رفض قبل مرور 90 دقيقة حتى مع 3 فشول
w, store, client, notif, clock = make(("a", "bad"))
client.script["bad" * 6] = sw.Mt5Error(-6, "Authorization failed", "auth")
w.tick(); w.tick()
w.queue["bad"].fails = 2                   # فشلان سابقان قبل دقائق فقط
w.queue["bad"].first_fail = clock.t - 600
w.queue["bad"].next_due = 0
w.tick()
ok("3 فشول خلال 10 دقائق: لا رفض", store.docs["bad"]["status"] == "approved" and "bad" in w.queue)
w.queue["bad"].fails = 2
w.queue["bad"].first_fail = clock.t - 6000
w.queue["bad"].next_due = 0
w.tick()
ok("3 فشول على مدى أكثر من 90 دقيقة: يُرفض", store.docs["bad"]["status"] == "rejected")

# ───────────── 3) عميل MT5: الوسائط يجب أن تكون أرقامًا (لا datetime) ─────────────
class FakeMt5:
    def __init__(self): self.args = None
    def initialize(self, **kw): return True
    def last_error(self): return (1, "Success")
    def account_info(self):
        class A: login, balance, equity, profit, margin, margin_free = 555, 100.0, 101.0, 1.0, 0.0, 101.0
        A.margin_level, A.credit, A.leverage, A.currency, A.name, A.server = 0.0, 0.0, 500, "USD", "n", "s"
        return A()
    def history_deals_get(self, a, b):
        self.args = (a, b)
        if not all(type(x) is int for x in (a, b)):
            raise NameError("name 'datetime' is not defined")   # نفس خطأ Wine الحقيقي
        return ()
    def shutdown(self): pass

fake = FakeMt5()
cl = sw.Mt5Client(sw.load_config())
cl._connect = lambda: fake
res = cl.fetch("555", "pw", "S", 0, 1_800_000_000)
ok("تاريخ الصفقات يُمرَّر أرقامًا", type(fake.args[0]) is int and type(fake.args[1]) is int)
ok("قراءة الحساب من العميل", res["account"]["balance"] == 100.0 and res["deals"] == [])
print("\nكل اختبارات العميل نجحت ✅")

# ───────────── 4) القفل المشترك على ترمنال المراقبة ─────────────
import tempfile
import threading

sw.MT5_LOCK_PATH = os.path.join(tempfile.mkdtemp(), "mt5.lock")


class Slow(FakeMt5):
    active = 0
    peak = 0
    guard = threading.Lock()

    def initialize(self, **kw):
        with Slow.guard:
            Slow.active += 1
            Slow.peak = max(Slow.peak, Slow.active)
        time.sleep(0.25)
        with Slow.guard:
            Slow.active -= 1
        return True

    def history_deals_get(self, a, b):
        return ()


def _client():
    cl = sw.Mt5Client(sw.load_config())
    cl._connect = lambda: Slow()
    return cl


results = []
ts_ = [threading.Thread(target=lambda: results.append(_client().fetch("555", "pw", "S", 0, 1_800_000_000, lock_wait=10)))
       for _ in range(3)]
[t.start() for t in ts_]
[t.join() for t in ts_]
ok("3 طلبات متزامنة تُنفَّذ واحدًا تلو الآخر (لا تداخل)", Slow.peak == 1 and len(results) == 3)

hold, release = threading.Event(), threading.Event()


def _holder():
    with sw.mt5_lock():
        hold.set()
        release.wait(5)


th = threading.Thread(target=_holder)
th.start()
hold.wait(2)
try:
    _client().fetch("555", "pw", "S", 0, 1_800_000_000, lock_wait=0.5)
    raised = None
except sw.Mt5Error as e:
    raised = e
ok("الترمنال مشغول: خطأ عابر لا رفض للمستخدم", raised is not None and raised.kind == "transient")

w, store, client, notif, clock = make(("a",))
w.queue.clear()
w.bridge.up = True
w.maybe_stop_bridge(clock.t)
ok("لا يُطفأ الجسر أثناء تحقق أحدهم", w.bridge.up is True)
release.set()
th.join()
w.maybe_stop_bridge(clock.t)
ok("يُطفأ بعد تحرّر القفل", w.bridge.up is False)
print("\nكل اختبارات القفل نجحت ✅")
