#!/usr/bin/env python3
"""
AW Sync Worker — تحديث بيانات حسابات MT5 بالتناوب.

كيف يعمل:
  • حساب واحد فقط في كل لحظة على ترمنال مراقبة مستقل (منفذ 8002)،
    ولا يلمس ترمنال الروبوت (منفذ 8001) إطلاقًا.
  • مبدّل ديناميكي: الحساب الأقدم تحديثًا يُخدَّم أولًا (Earliest-Due-First)،
    والحساب الجديد بعد ✅ يُخدَّم فورًا، وكل حساب يعود دوره بعد SYNC_INTERVAL_SEC.
  • يحمي السيرفر: لا يبدأ حسابًا إن كانت الذاكرة قليلة أو الحِمل عاليًا،
    ويرتاح بين حساب وآخر بنسبة زمن عمله (LOAD_FACTOR).
  • يعالج الأعطال: تراجع تدريجي عند الفشل، وإعادة تشغيل الجسر ذاتيًا إن علق.
  • للقراءة فقط: يستخدم initialize / account_info / history_deals_get فقط.

التشغيل:
  python sync_worker.py            # الخدمة الدائمة
  python sync_worker.py --probe    # تجربة حساب واحد وطباعة النتيجة بدون كتابة
"""
import argparse
import contextlib
import fcntl
import json
import logging
import os
import random
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("aw-sync")

# ───────────────────────── الإعدادات ─────────────────────────
def _env(name, default, cast=str):
    raw = os.getenv(name)
    return cast(raw) if raw not in (None, "") else default


def load_config():
    return SimpleNamespace(
        bridge_host=_env("BRIDGE_HOST", "127.0.0.1"),
        bridge_port=_env("BRIDGE_PORT", 8002, int),
        mt5_path=_env("MT5_PATH", r"C:\Program Files\MT5-Monitor\terminal64.exe"),
        interval=_env("SYNC_INTERVAL_SEC", 3600, int),  # دورة كل حساب
        jitter=_env("SYNC_JITTER", 0.05, float),  # تشتيت الأوقات كي لا تتكتل
        min_gap=_env("MIN_GAP_SEC", 5.0, float),  # أقل راحة بين حسابين
        load_factor=_env("LOAD_FACTOR", 0.5, float),  # الراحة = زمن العمل × هذا
        mem_min_mb=_env("MEM_MIN_FREE_MB", 200, int),
        load_max=_env("LOAD_MAX_PER_CORE", 1.2, float),  # يُستخدم فقط إن لم يتوفر PSI
        cpu_psi_max=_env("CPU_PSI_MAX", 70.0, float),  # % وقت انتظار المعالج (آخر 10ث)
        io_psi_max=_env("IO_PSI_MAX", 70.0, float),  # % وقت انتظار القرص (آخر 10ث)
        idle_stop=_env("IDLE_STOP_SEC", 300, int),  # نُطفئ ترمنال المراقبة إن لم يُستحق حساب خلال هذه المدة
        auth_min_span=_env("AUTH_MIN_SPAN_SEC", 5400, int),  # أقل مدة تمتد فيها فشول التوثيق قبل الرفض
        refresh=_env("REFRESH_SEC", 1800, int),  # مزامنة القائمة الكاملة
        poll_new=_env("POLL_NEW_SEC", 30, int),  # التقاط الحسابات المقبولة حديثًا
        init_timeout_ms=_env("INIT_TIMEOUT_MS", 90000, int),
        rpc_timeout=_env("RPC_TIMEOUT_SEC", 120, int),
        auth_max_fails=_env("AUTH_MAX_FAILS", 3, int),
        report_tz=_env("REPORT_TZ", "UTC"),
        bridge_service=_env("BRIDGE_SERVICE", "mt5-monitor-bridge"),
        lock_wait=_env("MT5_LOCK_WAIT_SEC", 120, int),  # أقصى انتظار لدور ترمنال المراقبة
    )


# ───────────────────────── حسابات التقارير (دوال نقية) ─────────────────────────
DEAL_BALANCE = 2  # إيداع / سحب
TRADE_TYPES = (0, 1)  # buy / sell
CLOSING_ENTRIES = (1, 2, 3)  # out / inout / out_by
MIN_SINCE_TS = 946684800  # 2000-01-01

ACCOUNT_KEYS = (
    "login", "balance", "equity", "profit", "margin", "margin_free",
    "margin_level", "credit", "leverage", "currency", "name", "server",
)
DEAL_KEYS = ("ticket", "time", "type", "entry", "profit", "commission", "swap", "fee")


STATS_VERSION = 2  # رفع الرقم يعيد قراءة السجل كاملًا مرة واحدة لكل حساب


def empty_stats():
    return {
        "v": STATS_VERSION,
        "wins": 0, "losses": 0, "flat": 0,
        "gross_profit": 0.0, "gross_loss": 0.0,
        "trading_pnl": 0.0, "deposits": 0.0, "withdrawals": 0.0,
        "cursor": 0, "seen": [],  # مؤشر آخر صفقة معالَجة (تحديث تراكمي بدل إعادة الحساب)
        "day_key": None, "day_pnl": 0.0, "day_wins": 0, "day_losses": 0,
        "week_key": None, "week_pnl": 0.0, "month_key": None, "month_pnl": 0.0,
        "best_trade": 0.0, "worst_trade": 0.0,
        "pnl_cum": 0.0, "pnl_peak": 0.0, "max_dd": 0.0,  # منحنى الأرباح المحققة لحساب أقصى تراجع
    }


def stats_defaults(stats):
    s = empty_stats()
    s.update(stats or {})
    return s


def period_keys(ts, tz):
    """مفاتيح اليوم والأسبوع (ISO، يبدأ الاثنين) والشهر بتوقيت التقارير."""
    d = datetime.fromtimestamp(ts, tz)
    iso = d.isocalendar()
    return d.strftime("%Y-%m-%d"), f"{iso[0]}-W{iso[1]:02d}", d.strftime("%Y-%m")


def day_key(ts, tz):
    return period_keys(ts, tz)[0]


def apply_deals(stats, deals, tz, now_ts):
    """يضيف الصفقات الجديدة فقط إلى الإحصاءات التراكمية. آمن عند التكرار."""
    s = stats_defaults(stats)
    s["seen"] = list(s["seen"])
    today_key, week_key, month_key = period_keys(now_ts, tz)
    if s["day_key"] != today_key:  # يوم جديد: نصفّر عدّادات اليوم
        s.update(day_key=today_key, day_pnl=0.0, day_wins=0, day_losses=0)
    if s["week_key"] != week_key:
        s.update(week_key=week_key, week_pnl=0.0)
    if s["month_key"] != month_key:
        s.update(month_key=month_key, month_pnl=0.0)

    for d in sorted(deals, key=lambda x: (int(x["time"]), int(x["ticket"]))):
        t, ticket = int(d["time"]), int(d["ticket"])
        if t < s["cursor"] or (t == s["cursor"] and ticket in s["seen"]):
            continue  # معالَجة سابقًا

        amount = float(d["profit"]) + float(d["commission"]) + float(d["swap"]) + float(d["fee"])
        if d["type"] == DEAL_BALANCE:
            if d["profit"] > 0:
                s["deposits"] += float(d["profit"])
            else:
                s["withdrawals"] += -float(d["profit"])
        elif d["type"] in TRADE_TYPES:
            dk, wk, mk = period_keys(t, tz)
            is_today = dk == today_key
            s["trading_pnl"] += amount
            if is_today:
                s["day_pnl"] += amount
            if wk == week_key:
                s["week_pnl"] += amount
            if mk == month_key:
                s["month_pnl"] += amount
            s["pnl_cum"] += amount
            s["pnl_peak"] = max(s["pnl_peak"], s["pnl_cum"])
            s["max_dd"] = max(s["max_dd"], s["pnl_peak"] - s["pnl_cum"])
            if d["entry"] in CLOSING_ENTRIES:
                s["best_trade"] = max(s["best_trade"], amount)
                s["worst_trade"] = min(s["worst_trade"], amount)
                if amount > 0:
                    s["wins"] += 1
                    s["gross_profit"] += amount
                    s["day_wins"] += is_today
                elif amount < 0:
                    s["losses"] += 1
                    s["gross_loss"] += -amount
                    s["day_losses"] += is_today
                else:
                    s["flat"] += 1

        if t > s["cursor"]:
            s["cursor"], s["seen"] = t, [ticket]
        else:
            s["seen"].append(ticket)
    return s


def _pct(part, base):
    return round(part / base * 100, 2) if base and base > 0 else None


def build_report(acc, stats):
    balance = float(acc["balance"])
    net_dep = stats["deposits"] - stats["withdrawals"]
    baseline = net_dep if net_dep > 0 else balance - stats["trading_pnl"]
    closed = stats["wins"] + stats["losses"]
    wins, losses = stats["wins"], stats["losses"]
    avg_win = stats["gross_profit"] / wins if wins else None
    avg_loss = stats["gross_loss"] / losses if losses else None
    r2 = lambda x: None if x is None else round(x, 2)
    return {
        "day_key": stats["day_key"],
        "daily_pnl": r2(stats["day_pnl"]),
        "daily_growth_pct": _pct(stats["day_pnl"], balance - stats["day_pnl"]),
        "weekly_pnl": r2(stats["week_pnl"]),
        "weekly_growth_pct": _pct(stats["week_pnl"], balance - stats["week_pnl"]),
        "monthly_pnl": r2(stats["month_pnl"]),
        "monthly_growth_pct": _pct(stats["month_pnl"], balance - stats["month_pnl"]),
        "total_pnl": r2(stats["trading_pnl"]),
        "total_growth_pct": _pct(balance - baseline, baseline),
        "net_deposits": r2(net_dep),
        "trades": closed + stats["flat"],
        "wins": wins,
        "losses": losses,
        "win_rate": _pct(wins, closed),
        "profit_factor": r2(stats["gross_profit"] / stats["gross_loss"]) if stats["gross_loss"] > 0 else None,
        "gross_profit": r2(stats["gross_profit"]),
        "gross_loss": r2(stats["gross_loss"]),
        "avg_win": r2(avg_win),
        "avg_loss": r2(avg_loss),
        "payoff_ratio": r2(avg_win / avg_loss) if avg_win and avg_loss else None,
        "expectancy": r2((stats["gross_profit"] - stats["gross_loss"]) / closed) if closed else None,
        "best_trade": r2(stats["best_trade"]) if wins else None,
        "worst_trade": r2(stats["worst_trade"]) if losses else None,
        # تقريبي: من منحنى الصفقات المغلقة (لا يشمل الأرباح العائمة)
        "max_drawdown": r2(stats["max_dd"]),
        "max_drawdown_pct": _pct(stats["max_dd"], baseline + stats["pnl_peak"]),
    }


def build_live(acc):
    f = lambda k: round(float(acc.get(k) or 0), 2)
    return {
        "balance": f("balance"), "equity": f("equity"), "profit": f("profit"),
        "margin": f("margin"), "margin_free": f("margin_free"), "margin_level": f("margin_level"),
        "credit": f("credit"), "leverage": int(acc.get("leverage") or 0),
        "currency": str(acc.get("currency") or ""),
    }


# ───────────────────────── الاتصال بـ MT5 ─────────────────────────
class Mt5Error(Exception):
    def __init__(self, code, msg, kind):
        super().__init__(f"{code}: {msg}")
        self.code, self.msg, self.kind = code, msg, kind  # kind: auth | transient


AUTH_CODES = {-6, -2}  # فشل التوثيق / معاملات غير صالحة

MT5_LOCK_PATH = os.getenv("MT5_LOCK_PATH", "/tmp/aw-mt5.lock")


@contextlib.contextmanager
def mt5_lock(timeout=None):
    """قفل مشترك بين الـ API والمزامنة (عمليتان منفصلتان): حساب واحد فقط على ترمنال المراقبة في أي لحظة.
    timeout=None ينتظر بلا حد، 0 محاولة واحدة، وإلا ينتظر هذه المدة ثم يرفع TimeoutError."""
    fd = os.open(MT5_LOCK_PATH, os.O_RDWR | os.O_CREAT, 0o666)
    try:
        deadline = None if timeout is None else time.time() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if deadline is not None and time.time() >= deadline:
                    raise TimeoutError("mt5 terminal busy")
                time.sleep(0.25)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def read_rows(objs, keys):
    """يقرأ الحقول المطلوبة فقط. يحاول جلب القائمة دفعة واحدة عبر rpyc لتسريعها."""
    try:
        from rpyc.utils.classic import obtain

        objs = obtain(objs)
    except Exception:
        pass
    return [{k: getattr(o, k, 0) for k in keys} for o in objs]


class Mt5Client:
    def __init__(self, cfg, bridge=None):
        self.cfg = cfg
        self.bridge = bridge  # إن وُجد يُشغَّل الجسر داخل القفل عند الحاجة

    def _connect(self):
        from mt5linux import MetaTrader5

        mt5 = MetaTrader5(host=self.cfg.bridge_host, port=self.cfg.bridge_port)
        try:
            mt5._MetaTrader5__conn._config["sync_request_timeout"] = self.cfg.rpc_timeout
        except Exception:
            pass
        return mt5

    def fetch(self, login, password, server, since_ts, now_ts, lock_wait=None):
        """يجلب بيانات حساب واحد. محمي بقفل مشترك فلا يتداخل حسابان على الترمنال نفسه."""
        wait = self.cfg.lock_wait if lock_wait is None else lock_wait
        try:
            with mt5_lock(timeout=wait):
                if self.bridge is not None:
                    self.bridge.start()
                return self._fetch(login, password, server, since_ts, now_ts)
        except TimeoutError:
            raise Mt5Error(-10004, "monitor terminal busy", "transient")

    def _fetch(self, login, password, server, since_ts, now_ts):
        try:
            mt5 = self._connect()
        except Exception as e:  # الجسر متوقف
            raise Mt5Error(-10004, f"bridge unreachable: {e!r}", "transient")

        try:
            ok = mt5.initialize(
                path=self.cfg.mt5_path, login=int(login), password=password,
                server=server, portable=True, timeout=self.cfg.init_timeout_ms,
            )
            if not ok:
                code, msg = mt5.last_error()
                raise Mt5Error(code, msg, "auth" if code in AUTH_CODES else "transient")

            info = mt5.account_info()
            if info is None:
                code, msg = mt5.last_error()
                raise Mt5Error(code, msg, "transient")
            acc = read_rows([info], ACCOUNT_KEYS)[0]
            if int(acc["login"]) != int(login):  # لا نقبل بيانات حساب آخر أبدًا
                raise Mt5Error(-1, "terminal is on a different account", "transient")

            # أرقام ثوانٍ لا datetime: جسر mt5linux يرسل الوسائط كنص إلى Wine ولا يعرف datetime هناك
            start = int(max(since_ts, MIN_SINCE_TS))
            end = int(now_ts + 86400)
            raw = mt5.history_deals_get(start, end)
            if raw is None:
                code, msg = mt5.last_error()
                if code != 1:
                    raise Mt5Error(code, msg, "transient")
                raw = ()
            return {"account": acc, "deals": read_rows(raw, DEAL_KEYS)}
        except Mt5Error:
            raise
        except Exception as e:
            raise Mt5Error(-10005, repr(e), "transient")
        finally:
            try:
                mt5.shutdown()
            except Exception:
                pass


# ───────────────────────── التخزين والإشعارات ─────────────────────────
class Store:
    def __init__(self):
        import firebase_admin
        from firebase_admin import credentials, firestore

        key_json = os.getenv("FIREBASE_KEY_JSON")
        cred = (
            credentials.Certificate(json.loads(key_json))
            if key_json
            else credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "firebase-adminsdk.json"))
        )
        try:
            firebase_admin.get_app()
        except ValueError:
            firebase_admin.initialize_app(cred)
        self.db = firestore.client()
        self.ts = firestore.SERVER_TIMESTAMP

    def _users(self):
        return self.db.collection("users")

    def approved(self):
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = self._users().where(filter=FieldFilter("status", "==", "approved")).select(["sync", "stats.v"])
        out = []
        for d in q.stream():
            x = d.to_dict() or {}
            out.append((d.id, x.get("sync") or {}, (x.get("stats") or {}).get("v")))
        return out

    def new_ids(self):
        from google.cloud.firestore_v1.base_query import FieldFilter

        q = (
            self._users()
            .where(filter=FieldFilter("status", "==", "approved"))
            .where(filter=FieldFilter("sync.state", "==", "new"))
            .select(["sync.state"])
        )
        return [d.id for d in q.stream()]

    def get(self, uid):
        snap = self._users().document(str(uid)).get()
        return snap.to_dict() if snap.exists else None

    def update(self, uid, fields):
        self._users().document(str(uid)).update(fields)


class Notifier:
    def __init__(self):
        self.token = os.getenv("BOT_TOKEN")
        self.channel = os.getenv("CHANNEL_ID")
        self.http = httpx.Client(timeout=15)

    def _send(self, chat_id, text):
        if not (self.token and chat_id):
            return
        try:
            self.http.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": chat_id, "text": text},
            )
        except httpx.HTTPError as e:
            log.warning("تعذّر إرسال إشعار: %s", e)

    def user(self, uid, text):
        self._send(uid, text)

    def admin(self, text):
        self._send(self.channel, text)


# ───────────────────────── المبدّل الديناميكي ─────────────────────────
AUTH_BACKOFF = (120, 600, 1800, 3600)
TRANSIENT_BACKOFF = (60, 120, 300, 600, 1800)

REASON_AUTH = {
    "ar": "تعذّر الدخول إلى حسابك بالبيانات المُدخلة. تحقق من رقم الحساب وكلمة المرور واسم السيرفر ثم أعد الإرسال.",
    "en": "We couldn't sign in to your account with the details provided. Check your login, password and server, then resubmit.",
}
USER_MSG = {
    "ar": "⚠️ توقف تحديث بيانات حسابك.\n📌 السبب: {r}",
    "en": "⚠️ Updates for your account have stopped.\n📌 Reason: {r}",
}


def mem_available_mb():
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    return None


def psi(resource):
    """نسبة الوقت الذي كانت فيه مهام تنتظر المورد (آخر 10ث). None إن لم يتوفر."""
    try:
        with open(f"/proc/pressure/{resource}") as f:
            return float(f.readline().split("avg10=")[1].split()[0])
    except (OSError, IndexError, ValueError):
        return None


def load_per_core():
    try:
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except OSError:
        return 0.0


def mask(login):
    s = str(login)
    return f"{s[:2]}***{s[-2:]}" if len(s) > 4 else "***"


class BridgeCtl:
    """يشغّل جسر/ترمنال المراقبة عند الحاجة ويطفئه وهو خامل لتخفيف الضغط على السيرفر."""

    def __init__(self, cfg):
        self.cfg = cfg

    def is_up(self):
        try:
            socket.create_connection((self.cfg.bridge_host, self.cfg.bridge_port), timeout=1).close()
            return True
        except OSError:
            return False

    def _ctl(self, action):
        subprocess.run(["sudo", "-n", "systemctl", action, self.cfg.bridge_service],
                       timeout=90, check=True)

    def start(self):
        if self.is_up():
            return
        log.info("تشغيل جسر المراقبة")
        try:
            self._ctl("start")
        except Exception as e:
            raise Mt5Error(-10004, f"bridge start failed: {e}", "transient")
        for _ in range(60):
            if self.is_up():
                return
            time.sleep(1)
        raise Mt5Error(-10004, "bridge did not open its port in 60s", "transient")

    def stop(self):
        log.info("إطفاء جسر المراقبة (لا حسابات مستحقة قريبًا)")
        self._ctl("stop")

    def restart(self):
        self._ctl("restart")


@dataclass
class Job:
    uid: str
    next_due: float = 0.0
    fails: int = 0
    first_fail: float = 0.0


class Worker:
    def __init__(self, cfg, store, client, notifier, clock=time.time, bridge=None):
        self.cfg, self.store, self.client, self.notifier, self.clock = cfg, store, client, notifier, clock
        self.bridge = bridge or BridgeCtl(cfg)
        self.tz = ZoneInfo(cfg.report_tz)
        self.queue = {}
        self.last_refresh = -1e12
        self.last_poll = -1e12
        self.transient_streak = 0
        self.last_restart = -1e12
        self.last_ok_ts = None
        self.load_deferrals = 0
        self.warned_unhealthy = False
        self.stop = False

    # ── القائمة ──
    def reload_all(self):
        seen = set()
        for uid, sync, ver in self.store.approved():
            seen.add(uid)
            if uid not in self.queue:
                state = sync.get("state", "new")
                stale = ver != STATS_VERSION  # صيغة إحصاءات قديمة: نحدّثه فورًا
                self.queue[uid] = Job(
                    uid,
                    next_due=0.0 if (state == "new" or stale) else float(sync.get("next_due") or 0),
                    fails=int(sync.get("fails") or 0),
                    first_fail=float(sync.get("first_fail") or 0),
                )
        for uid in list(self.queue):
            if uid not in seen:
                del self.queue[uid]
        log.info("القائمة: %d حساب نشط", len(self.queue))

    def poll_new(self):
        for uid in self.store.new_ids():
            job = self.queue.setdefault(uid, Job(uid))
            job.next_due = 0.0

    def pick(self, now):
        due = [j for j in self.queue.values() if j.next_due <= now]
        return min(due, key=lambda j: j.next_due) if due else None

    # ── حماية السيرفر ──
    def resources_ok(self):
        mem = mem_available_mb()
        if mem is not None and mem < self.cfg.mem_min_mb:
            return False, f"الذاكرة المتاحة {mem}MB أقل من {self.cfg.mem_min_mb}MB"
        cpu, io = psi("cpu"), psi("io")
        if cpu is None or io is None:  # نواة بلا PSI: نرجع لمتوسط الحِمل
            busy = load_per_core() > self.cfg.load_max
            why = "الحِمل مرتفع"
        else:
            busy = cpu > self.cfg.cpu_psi_max or io > self.cfg.io_psi_max
            why = f"ضغط السيرفر مرتفع (معالج {cpu:.0f}% · قرص {io:.0f}%)"
        if busy:
            self.load_deferrals += 1
            if self.load_deferrals <= 5:  # نؤجل 5 مرات كحد أقصى كي لا نتجمد
                return False, why
        self.load_deferrals = 0
        return True, ""

    # ── دورة واحدة: تُرجع كم ثانية ننام ──
    def tick(self):
        now = self.clock()
        if now - self.last_refresh >= self.cfg.refresh:
            self.reload_all()
            self.last_refresh = self.last_poll = now
        elif now - self.last_poll >= self.cfg.poll_new:
            self.poll_new()
            self.last_poll = now

        job = self.pick(now)
        if job is None:
            nxt = min((j.next_due for j in self.queue.values()), default=now + self.cfg.poll_new)
            self.maybe_stop_bridge(now)
            return max(1.0, min(nxt - now, self.cfg.poll_new))

        ok, why = self.resources_ok()
        if not ok:
            log.warning("تأجيل التحديث: %s", why)
            return 30.0

        t0 = self.clock()
        self.process(job)
        elapsed = self.clock() - t0
        self.maybe_stop_bridge(self.clock())
        return max(self.cfg.min_gap, elapsed * self.cfg.load_factor)  # راحة تتناسب مع الجهد

    def maybe_stop_bridge(self, now):
        """لا حساب مستحق خلال idle_stop ثانية: نُطفئ ترمنال المراقبة حتى يحين الدور."""
        nxt = min((j.next_due for j in self.queue.values()), default=float("inf"))
        if nxt - now <= self.cfg.idle_stop:
            return
        try:
            with mt5_lock(timeout=0):  # لا نُطفئ الجسر إن كان أحدهم (تسجيل مستخدم) يتحقق الآن
                if self.bridge.is_up():
                    self.bridge.stop()
        except TimeoutError:
            pass
        except Exception as e:
            log.warning("تعذّر إطفاء الجسر: %s", e)

    # ── معالجة حساب واحد ──
    def process(self, job):
        doc = self.store.get(job.uid)
        if not doc or doc.get("status") != "approved":
            self.queue.pop(job.uid, None)
            return

        raw = doc.get("stats") or {}
        stats = stats_defaults(raw) if raw.get("v") == STATS_VERSION else empty_stats()
        now = self.clock()
        t0 = now
        try:
            self.bridge.start()
            res = self.client.fetch(
                doc["mt5_login"], doc["mt5_password"], doc["mt5_server"], stats["cursor"], now
            )
        except Mt5Error as e:
            return self.on_failure(job, doc, e)
        except Exception as e:
            return self.on_failure(job, doc, Mt5Error(-1, repr(e), "transient"))

        new_stats = apply_deals(stats, res["deals"], self.tz, now)
        delay = self.cfg.interval * (1 + random.uniform(-self.cfg.jitter, self.cfg.jitter))
        live = build_live(res["account"])
        live["updated_at"] = self.store.ts
        self.store.update(job.uid, {
            "live": live,
            "report": build_report(res["account"], new_stats),
            "stats": new_stats,
            "sync": {
                "state": "ok", "last_ok": self.store.ts, "next_due": now + delay,
                "fails": 0, "first_fail": None, "last_error": None,
                "seconds": round(self.clock() - t0, 1),
            },
        })
        job.next_due, job.fails, job.first_fail = now + delay, 0, 0.0
        self.transient_streak = 0
        self.last_ok_ts = now
        log.info("✔ %s (%s) رصيد=%s", job.uid, mask(doc["mt5_login"]), live["balance"])

    def on_failure(self, job, doc, err):
        now = self.clock()
        job.fails += 1
        if job.fails == 1 or not job.first_fail:
            job.first_fail = now
        log.warning("✖ %s (%s): %s [%s]", job.uid, mask(doc.get("mt5_login")), err, err.kind)

        if err.kind == "auth":
            self.transient_streak = 0
            healthy = self.last_ok_ts is not None and now - self.last_ok_ts < 86400
            if job.fails >= self.cfg.auth_max_fails and now - job.first_fail >= self.cfg.auth_min_span:
                if healthy:
                    return self.suspend(job, doc, err)
                if not self.warned_unhealthy:  # لا حساب نجح مؤخرًا: الخلل غالبًا في الترمنال
                    self.warned_unhealthy = True
                    self.notifier.admin(
                        "⚠️ فشل الدخول لحساب ولم ينجح أي حساب مؤخرًا. "
                        "قد تكون المشكلة في ترمنال المراقبة لا في بيانات المستخدم، لذلك لم أُرجِع الطلب."
                    )
            steps = AUTH_BACKOFF
        else:
            self.transient_streak += 1
            self.maybe_restart_bridge(now)
            steps = TRANSIENT_BACKOFF

        delay = min(steps[min(job.fails, len(steps)) - 1], self.cfg.interval)
        job.next_due = now + delay
        self.store.update(job.uid, {
            "sync.state": "error", "sync.fails": job.fails, "sync.first_fail": job.first_fail,
            "sync.last_error": str(err), "sync.next_due": job.next_due,
        })

    def suspend(self, job, doc, err):
        """بيانات الدخول خاطئة فعلًا: نعيد الطلب للمستخدم ليعدّله عبر مسار الرفض الموجود."""
        lang = doc.get("language", "en")
        reason = REASON_AUTH.get(lang, REASON_AUTH["en"])
        self.store.update(job.uid, {
            "status": "rejected", "rejection_reason": reason,
            "sync.state": "auth_failed", "sync.fails": job.fails, "sync.last_error": str(err),
        })
        self.queue.pop(job.uid, None)
        self.notifier.user(job.uid, USER_MSG.get(lang, USER_MSG["en"]).format(r=reason))
        self.notifier.admin(
            f"⚠️ توقف تحديث حساب {doc.get('mt5_login')} ({doc.get('mt5_server')}) "
            f"للمستخدم {job.uid}: {err}\nأُعيد الطلب للمستخدم لتعديل بياناته."
        )

    def maybe_restart_bridge(self, now):
        if self.transient_streak < 3 or now - self.last_restart < 600:
            return
        self.last_restart, self.transient_streak = now, 0
        log.error("أعطال متتالية: إعادة تشغيل جسر المراقبة")
        try:
            self.bridge.restart()
            self.notifier.admin("🔁 أُعيد تشغيل جسر المراقبة بعد أعطال متتالية.")
        except Exception as e:
            log.error("فشلت إعادة التشغيل: %s", e)
            self.notifier.admin(f"❌ تعذّرت إعادة تشغيل جسر المراقبة: {e}")

    # ── الحلقة الدائمة ──
    def sleep(self, secs):
        end = time.time() + secs
        while not self.stop and time.time() < end:
            time.sleep(min(1.0, max(0.0, end - time.time())))

    def run(self):
        log.info("بدأ العمل: دورة كل %ss لكل حساب", self.cfg.interval)
        while not self.stop:
            try:
                delay = self.tick()
            except Exception:
                log.exception("خطأ غير متوقع في الدورة")
                delay = 15.0
            self.sleep(delay)
        log.info("توقف بأمان")


# ───────────────────────── نقطة الدخول ─────────────────────────
def probe(cfg, store, uid):
    if not uid:
        rows = [(u, sy) for u, sy, _ in store.approved()]
        if not rows:
            sys.exit("لا توجد حسابات مقبولة. اقبل حسابًا تجريبيًا أولًا، أو مرّر UID: --probe 12345")
        uid = rows[0][0]
    doc = store.get(uid)
    if not doc:
        sys.exit(f"لا يوجد مستخدم {uid}")
    print(f"تجربة الحساب {mask(doc['mt5_login'])} على {doc['mt5_server']} ... (قد تأخذ حتى دقيقة في أول مرة)")
    now = time.time()
    tz = ZoneInfo(cfg.report_tz)
    try:
        res = Mt5Client(cfg, bridge=BridgeCtl(cfg)).fetch(doc["mt5_login"], doc["mt5_password"], doc["mt5_server"], 0, now)
    except Mt5Error as e:
        sys.exit(f"فشل: {e}  [{e.kind}]")
    stats = apply_deals(empty_stats(), res["deals"], tz, now)
    print(json.dumps({"live": build_live(res["account"]), "report": build_report(res["account"], stats),
                      "deals_read": len(res["deals"])}, indent=2, ensure_ascii=False))
    print("\n✔ نجحت التجربة (لم يُكتب شيء في قاعدة البيانات)")


def main():
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", nargs="?", const="", metavar="UID")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    cfg = load_config()
    store = Store()
    if args.probe is not None:
        return probe(cfg, store, args.probe)

    lock = open("/tmp/aw-sync.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("نسخة أخرى من السكربت تعمل بالفعل")

    bridge = BridgeCtl(cfg)
    worker = Worker(cfg, store, Mt5Client(cfg, bridge=bridge), Notifier(), bridge=bridge)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: setattr(worker, "stop", True))
    worker.run()


if __name__ == "__main__":
    main()
