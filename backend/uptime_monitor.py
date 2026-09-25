"""
AW Uptime Monitor — مراقبة خارجية مستقلة عن الـ API (تعمل حتى لو توقف الـ API نفسه).

يشغّله مؤقّت systemd كل دقيقة (aw-uptime.timer). يفحص:
  • الـ API محليًا (127.0.0.1:8000) وعبر الرابط العام (nginx + TLS) إن ضُبط WEBAPP_URL.
  • خدمة المزامنة aw-sync وجسر MT5 للروبوت (mt5-bridge، المنفذ 8001).
يرسل تنبيهًا فوريًا لكل أدمن (ADMIN_IDS) عبر البوت عند التعطل، ورسالة «عاد للعمل» عند التعافي، وتذكيرًا
كل 30 دقيقة ما دام العطل قائمًا. لا يعتمد إلا على مكتبة بايثون القياسية.
"""
import json
import os
import socket
import subprocess
import time
import urllib.parse
import urllib.request

STATE = os.getenv("AW_UPTIME_STATE", "/var/lib/aw-uptime/state.json")
REMIND_SEC = 30 * 60
FAILS_TO_ALERT = 2  # فحصان متتاليان فاشلان (دقيقتان) قبل التنبيه: لا إنذارات كاذبة أثناء إعادة التشغيل


def _http_ok(url: str, timeout: float = 8) -> tuple[bool, str]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "aw-uptime"}), timeout=timeout) as r:
            return r.status < 500, f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return e.code < 500, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


def _tcp_ok(host: str, port: int) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=5):
            return True, "open"
    except OSError as e:
        return False, type(e).__name__


def _unit_ok(unit: str) -> tuple[bool, str]:
    try:
        out = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception as e:  # noqa: BLE001
        return True, f"unknown ({type(e).__name__})"  # لا نملك systemctl: لا نبلّغ خطأً كاذبًا
    if out in ("inactive", "unknown") and subprocess.run(["systemctl", "is-enabled", unit], capture_output=True, text=True).stdout.strip() != "enabled":
        return True, "not installed"
    return out == "active", out


def checks() -> dict:
    res = {"api": _http_ok("http://127.0.0.1:8000/"), "sync": _unit_ok("aw-sync")}
    web = (os.getenv("WEBAPP_URL") or "").rstrip("/")
    if web.startswith("https://"):
        res["public"] = _http_ok(f"{web}/api/")
    if os.getenv("UPTIME_CHECK_BRIDGE", "1") == "1" and _unit_ok("mt5-bridge")[1] != "not installed":
        res["mt5_bridge"] = _tcp_ok("127.0.0.1", int(os.getenv("BRIDGE_PORT", "8001")))
    return res


LABEL = {"api": "الـ API (الخادم)", "public": "الرابط العام (nginx/SSL)", "sync": "عامل المزامنة aw-sync", "mt5_bridge": "جسر MT5 للروبوت"}


def send(text: str):
    token = os.getenv("BOT_TOKEN", "")
    for chat in [x for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]:
        try:
            data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
            urllib.request.urlopen(f"https://api.telegram.org/bot{token}/sendMessage", data=data, timeout=10).read()
        except Exception:  # noqa: BLE001
            pass


def run(now: float | None = None, results: dict | None = None, notify=send) -> dict:
    now = time.time() if now is None else now
    try:
        with open(STATE) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    results = results if results is not None else checks()
    for name, (up, detail) in results.items():
        st = state.get(name) or {"fails": 0, "down_since": None, "alerted": 0}
        if up:
            if st.get("alerted"):
                mins = round((now - (st.get("down_since") or now)) / 60)
                notify(f"✅ عاد للعمل: {LABEL.get(name, name)} (توقف ~{mins} دقيقة)")
            st = {"fails": 0, "down_since": None, "alerted": 0}
        else:
            st["fails"] = int(st.get("fails") or 0) + 1
            st["down_since"] = st.get("down_since") or now
            if st["fails"] >= FAILS_TO_ALERT and (not st.get("alerted") or now - st["alerted"] >= REMIND_SEC):
                again = " (ما زال متوقفًا)" if st.get("alerted") else ""
                notify(f"🔴 تعطّل{again}: {LABEL.get(name, name)} — {detail}\nمنذ {time.strftime('%H:%M UTC', time.gmtime(st['down_since']))}. "
                       f"للفحص: aw-doctor")
                st["alerted"] = now
        state[name] = st
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(state, f)
    return state


if __name__ == "__main__":
    run()
