"""
AW Heartbeat — نبضة دائمة بين الباك اند وترمنال MT5 الخاص بالروبوت (جسر mt5linux عبر Wine، منفذ 8001).

  • نبضة كل HEARTBEAT_INTERVAL_SEC ثوانٍ (اتصال TCP بالجسر؛ لا يلمس الترمنال نفسه ولا صفقاته).
  • انقطاع أطول من HEARTBEAT_ALERT_SEC → تنبيه فوري للأدمن عبر تلجرام + تسجيل الحدث في Firestore (system_events).
  • ثم محاولة إعادة تشغيل الجسر تلقائيًا (sudo -n systemctl restart <HEARTBEAT_SERVICE>) بفاصل تهدئة بين المحاولات.
  • عند العودة: إشعار بالتعافي ومدة الانقطاع.
يعمل في خيط داخل الباك اند (lifespan في main.py). ملاحظة: الخدمة تُشغَّل بعامل uvicorn واحد، فالنبضة واحدة.
"""
import logging
import os
import socket
import subprocess
import threading
import time

log = logging.getLogger("aw-heartbeat")


def _env(name, default, cast=str):
    raw = os.getenv(name)
    return cast(raw) if raw not in (None, "") else default


ENABLED = _env("HEARTBEAT_ENABLED", "1") not in ("0", "false", "no")
HOST = _env("HEARTBEAT_HOST", "127.0.0.1")
PORT = _env("HEARTBEAT_PORT", 8001, int)
INTERVAL = _env("HEARTBEAT_INTERVAL_SEC", 5.0, float)
ALERT_AFTER = _env("HEARTBEAT_ALERT_SEC", 15.0, float)
RESTART_COOLDOWN = _env("HEARTBEAT_RESTART_COOLDOWN_SEC", 120.0, float)
SERVICE = _env("HEARTBEAT_SERVICE", "mt5-bridge")


def tcp_probe(host=HOST, port=PORT, timeout=2.0) -> bool:
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def systemctl_restart(service=SERVICE) -> bool:
    try:
        subprocess.run(["sudo", "-n", "systemctl", "restart", service], timeout=90, check=True)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("restart %s failed: %s", service, e)
        return False


class Heartbeat:
    def __init__(self, notify, record, probe=tcp_probe, restart=systemctl_restart, clock=time.time,
                 alert_after=ALERT_AFTER, restart_cooldown=RESTART_COOLDOWN):
        self.notify, self.record = notify, record  # notify(text) للأدمن، record(type, detail) في Firestore
        self.probe, self.restart, self.clock = probe, restart, clock
        self.alert_after, self.restart_cooldown = alert_after, restart_cooldown
        self.last_ok = None
        self.last_beat = None
        self.down_since = None
        self.alerted = False
        self.last_restart = -1e12
        self.restarts = 0

    def beat(self):
        now = self.clock()
        self.last_beat = now
        if self.probe():
            if self.down_since is not None:
                down_for = now - self.down_since
                self.record("recovered", {"down_for_sec": round(down_for, 1)})
                if self.alerted:
                    self.notify(f"✅ عاد الاتصال بترمنال MT5 للروبوت بعد انقطاع {down_for:.0f} ثانية.")
                log.info("MT5 heartbeat recovered after %.0fs", down_for)
            self.last_ok, self.down_since, self.alerted = now, None, False
            return True

        if self.down_since is None:
            self.down_since = now
            self.record("lost", {"host": HOST, "port": PORT})
            log.warning("MT5 heartbeat lost (%s:%s)", HOST, PORT)
        down_for = now - self.down_since
        if down_for >= self.alert_after:
            if not self.alerted:
                self.alerted = True
                self.record("alert", {"down_for_sec": round(down_for, 1)})
                self.notify(
                    f"🚨 انقطع الاتصال بترمنال MT5 للروبوت ({HOST}:{PORT}) منذ {down_for:.0f} ثانية.\n"
                    f"جارٍ محاولة إعادة تشغيل {SERVICE} تلقائيًا..."
                )
            if now - self.last_restart >= self.restart_cooldown:
                self.last_restart = now
                self.restarts += 1
                ok = self.restart()
                self.record("restart", {"ok": ok, "attempt": self.restarts})
                if not ok:
                    self.notify(f"❌ تعذّرت إعادة تشغيل {SERVICE} تلقائيًا. يلزم تدخل يدوي.")
        return False

    def snapshot(self) -> dict:
        now = self.clock()
        if self.last_beat is None:
            return {"status": "unknown"}
        if self.down_since is not None:
            return {"status": "down", "down_for_sec": round(now - self.down_since, 1), "restarts": self.restarts}
        return {"status": "up", "last_ok": self.last_ok, "restarts": self.restarts}

    def run(self, stop: threading.Event, interval=INTERVAL):
        while not stop.is_set():
            try:
                self.beat()
            except Exception:  # noqa: BLE001 — الحارس لا يموت أبدًا
                log.exception("heartbeat error")
            stop.wait(interval)


_instance: Heartbeat | None = None
_stop = threading.Event()


def start(notify, record):
    global _instance
    if not ENABLED or _instance is not None:
        return
    _instance = Heartbeat(notify, record)
    threading.Thread(target=_instance.run, args=(_stop,), daemon=True, name="mt5-heartbeat").start()


def stop():
    _stop.set()


def snapshot() -> dict:
    if not ENABLED:
        return {"status": "not_configured"}
    return _instance.snapshot() if _instance else {"status": "unknown"}
