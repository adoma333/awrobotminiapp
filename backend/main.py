"""
AW Mini App — Backend
FastAPI + Firestore + Telegram Bot API

المسارات:
  POST /api/register          استقبال طلب المستخدم من الـ Mini App وإرساله لقناة الأدمن
  POST /api/status            حالة طلب المستخدم (none / pending / approved / rejected)
  POST /api/telegram-webhook  ضغطات الأزرار في القناة + رد الأدمن بسبب الرفض
"""
import hashlib
import hmac
import json
import logging
import math
import os
import re
import socket
import threading
import time
from contextlib import asynccontextmanager
from html import escape
from urllib.parse import parse_qsl

import firebase_admin
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Request, Response, Depends
import billing
import payments
import digest
from apscheduler.schedulers.background import BackgroundScheduler
import secrets
try:
    import jwt as pyjwt
except ImportError:
    pyjwt = None
from fastapi.middleware.cors import CORSMiddleware
from firebase_admin import credentials, firestore
from pydantic import BaseModel, Field

load_dotenv()

# ───────────────────────── الإعدادات ─────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
CHANNEL_ID = os.environ["CHANNEL_ID"]  # مثل -1001234567890
WEBHOOK_SECRET = os.environ["WEBHOOK_SECRET"]  # أي نص عشوائي طويل
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "*")

log = logging.getLogger("uvicorn.error")

# عنوان الميني آب (زر الترحيب) وعنوان الـ webhook. يُشتقّان من WEBAPP_URL أو FRONTEND_ORIGIN
WEBAPP_URL = (os.getenv("WEBAPP_URL") or (FRONTEND_ORIGIN if FRONTEND_ORIGIN != "*" else "")).rstrip("/")
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or (f"{WEBAPP_URL}/api/telegram-webhook" if WEBAPP_URL else "")

if not ADMIN_IDS:
    print("⚠️  ADMIN_IDS فارغ: لن يستطيع أحد الموافقة أو الرفض من القناة.")

_key_json = os.getenv("FIREBASE_KEY_JSON")  # محتوى ملف الخدمة كنص (مناسب للاستضافة)
_cred = (
    credentials.Certificate(json.loads(_key_json))
    if _key_json
    else credentials.Certificate(os.getenv("FIREBASE_KEY_PATH", "firebase-adminsdk.json"))
)
firebase_admin.initialize_app(_cred)
db = firestore.client()

WANTED_UPDATES = ["callback_query", "message", "pre_checkout_query"]  # pre_checkout_query لازم لدفع Stars


def ensure_webhook() -> str:
    """يتأكد أن webhook تلجرام مضبوط على عنوانك، ويعيد ضبطه إن تغيّر أو تعثّر مؤخرًا."""
    if not WEBHOOK_URL:
        return "no-url"
    info = tg("getWebhookInfo").get("result") or {}
    err_date = info.get("last_error_date")
    recent_error = bool(err_date) and time.time() - err_date < 900
    have = info.get("allowed_updates")  # غائب = الافتراضي (يشمل كل ما نحتاجه)
    updates_ok = have is None or set(WANTED_UPDATES) <= set(have)
    if info.get("url") == WEBHOOK_URL and not recent_error and updates_ok:
        return "ok"
    res = tg(
        "setWebhook",
        url=WEBHOOK_URL,
        secret_token=WEBHOOK_SECRET,
        allowed_updates=WANTED_UPDATES,
        max_connections=20,
    )
    log.info("webhook reset -> %s (%s)", WEBHOOK_URL, "ok" if res.get("ok") else res.get("description"))
    return "reset" if res.get("ok") else "failed"


def _watchdog():
    """حارس دائم: كل 5 دقائق يتحقق من الـ webhook. لا يموت أبدًا بسبب خطأ عابر."""
    while True:
        try:
            ensure_webhook()
        except Exception:
            log.exception("telegram watchdog error")
        time.sleep(300)


_scheduler = BackgroundScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_watchdog, daemon=True, name="tg-watchdog").start()
    _scheduler.add_job(lambda: digest.run_digest(db, tg, "weekly"), "cron", day_of_week="mon", hour=9, id="digest_weekly")
    _scheduler.add_job(lambda: digest.run_digest(db, tg, "monthly"), "cron", day=1, hour=9, id="digest_monthly")
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title="AW Mini App API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if FRONTEND_ORIGIN == "*" else [FRONTEND_ORIGIN],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
http = httpx.Client(timeout=15)


def tg(method: str, **params) -> dict:
    """استدعاء Telegram Bot API. لا يرفع استثناء؛ يرجع {'ok': False} عند الفشل."""
    try:
        return http.post(f"{TG_API}/{method}", json=params).json()
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "description": str(e)}


# ───────────────────────── التحقق من هوية المستخدم ─────────────────────────
def verify_init_data(init_data: str, max_age: int = 86400) -> dict:
    """يتحقق من توقيع initData القادم من تلجرام ويرجع بيانات المستخدم."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise HTTPException(401, "missing_hash")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise HTTPException(401, "bad_signature")

    if time.time() - int(pairs.get("auth_date", 0)) > max_age:
        raise HTTPException(401, "expired")

    try:
        return json.loads(pairs["user"])
    except (KeyError, ValueError):
        raise HTTPException(401, "no_user")


# ───────────────────────── النماذج ─────────────────────────
class Profile(BaseModel):
    nickname: str = Field(min_length=2, max_length=24)
    avatar: str = Field(pattern="^(boy|girl)$")


class MT5(BaseModel):
    login: str = Field(pattern=r"^\d{4,12}$")
    password: str = Field(min_length=1, max_length=64)
    server: str = Field(min_length=2, max_length=64)


class Registration(BaseModel):
    init_data: str
    language: str = Field(pattern="^(ar|en)$")
    profile: Profile
    mt5: MT5


class StatusRequest(BaseModel):
    init_data: str


# ───────────────────────── نصوص ─────────────────────────
REASONS = {
    "cred": {"ar": "رقم الحساب أو كلمة المرور غير صحيحة", "en": "Wrong login or password"},
    "srv": {"ar": "اسم السيرفر غير صحيح", "en": "Wrong server name"},
    "elig": {"ar": "الحساب غير مؤهل للربط", "en": "This account isn't eligible to be linked"},
}

USER_MSG = {
    "approved": {
        "ar": "🎉 تم قبول طلبك وربط حساب MT5 بنجاح.",
        "en": "🎉 Your request was approved and your MT5 account is linked.",
    },
    "rejected": {
        "ar": "❌ تم رفض طلب ربط حسابك.\n📌 السبب: {reason}",
        "en": "❌ Your account-linking request was rejected.\n📌 Reason: {reason}",
    },
}


def request_text(user: dict, body: Registration) -> str:
    uid = user["id"]
    username = user.get("username")
    who = f"@{escape(username)}" if username else escape(user.get("first_name", "—"))
    avatar = "فتى" if body.profile.avatar == "boy" else "فتاة"
    lang = "العربية" if body.language == "ar" else "English"
    return (
        "🟠 <b>طلب ربط حساب MT5</b>\n\n"
        f'👤 <a href="tg://user?id={uid}">{who}</a>\n'
        f"🆔 <code>{uid}</code>\n"
        f"🏷 الاسم المستعار: {escape(body.profile.nickname)} ({avatar})\n"
        f"🌐 اللغة: {lang}\n\n"
        "<b>بيانات الحساب</b> (اضغط على القيمة لنسخها)\n"
        f"Login: <code>{escape(body.mt5.login)}</code>\n"
        f"Password: <code>{escape(body.mt5.password)}</code>\n"
        f"Server: <code>{escape(body.mt5.server)}</code>"
    )


def decision_keyboard(uid: int) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "✅ موافقة", "callback_data": f"ap:{uid}"},
                {"text": "❌ رفض", "callback_data": f"rj:{uid}"},
            ]
        ]
    }


def reason_keyboard(uid: int) -> dict:
    rows = [[{"text": r["ar"], "callback_data": f"rr:{uid}:{k}"}] for k, r in REASONS.items()]
    rows.append([{"text": "✍️ سبب آخر", "callback_data": f"rr:{uid}:custom"}])
    rows.append([{"text": "↩️ رجوع", "callback_data": f"bk:{uid}"}])
    return {"inline_keyboard": rows}


def done_keyboard(label: str) -> dict:
    return {"inline_keyboard": [[{"text": label, "callback_data": "noop"}]]}


def user_ref(uid):
    return db.collection("users").document(str(uid))


# ───────────────────────── مسارات الـ Mini App ─────────────────────────
@app.get("/")
def health():
    return {"ok": True}


@app.post("/api/register")
def register(body: Registration):
    user = verify_init_data(body.init_data)
    uid = user["id"]
    now_ts = time.time()

    ref = user_ref(uid)
    snap = ref.get()
    previous = snap.to_dict() if snap.exists else None
    if previous and previous.get("status") == "approved":
        raise HTTPException(409, "approved")

    settings = billing.get_settings(db)
    if settings.get("kill_switch"):
        raise HTTPException(503, "registration_paused")
    if not billing.is_subscription_active(previous or {}):
        raise HTTPException(402, "subscription_required")

    fails = [t for t in ((previous or {}).get("link_fails") or []) if now_ts - t < 3600]
    if len(fails) >= 3:
        raise HTTPException(429, "too_many_attempts")

    if db.collection("blacklist").document(body.mt5.login).get().exists:
        raise HTTPException(403, "account_blacklisted")

    from google.cloud.firestore_v1.base_query import FieldFilter
    dup = (
        db.collection("users")
        .where(filter=FieldFilter("mt5_login", "==", body.mt5.login))
        .where(filter=FieldFilter("status", "==", "approved"))
        .limit(1)
        .get()
    )
    if dup and dup[0].id != str(uid):
        raise HTTPException(409, "account_already_linked")

    account_type = _account_type(body.mt5.server)
    if not billing.account_type_allowed(settings, account_type):
        raise HTTPException(403, "account_type_not_allowed")

    from sync_worker import load_config, Mt5Client, BridgeCtl, Mt5Error, build_live

    cfg = load_config()
    try:
        # القفل المشترك + تشغيل الجسر داخله؛ ننتظر دورنا حتى 45ث فقط ثم "حاول مجددًا"
        res = Mt5Client(cfg, bridge=BridgeCtl(cfg)).fetch(
            body.mt5.login, body.mt5.password, body.mt5.server, 0, now_ts, lock_wait=45
        )
    except Mt5Error as e:
        if e.kind == "auth":
            fails.append(now_ts)
            ref.set({"link_fails": fails}, merge=True)
            reason_key = "cred" if e.code == -6 else ("srv" if e.code == -2 else "elig")
            raise HTTPException(422, reason_key)
        raise HTTPException(503, "verification_temporarily_unavailable")

    live = build_live(res["account"])
    live["updated_at"] = firestore.SERVER_TIMESTAMP  # كي لا تظهر لوحة العميل "متأخرة" قبل أول مزامنة
    if not billing.leverage_allowed(settings, live.get("leverage")):
        raise HTTPException(403, "leverage_not_allowed")

    ref.set(
        {
            "telegram_id": uid,
            "username": user.get("username"),
            "language": body.language,
            "nickname": body.profile.nickname,
            "avatar": body.profile.avatar,
            "mt5_login": body.mt5.login,
            "mt5_password": body.mt5.password,
            "mt5_server": body.mt5.server,
            "status": "approved",
            "rejection_reason": None,
            "link_fails": [],
            "decided_at": firestore.SERVER_TIMESTAMP,
            "live": live,
            "report": None,
            "stats": None,  # إحصاءات حساب سابق (بعد فكّ ربط) يجب ألا تختلط بالحساب الجديد
            "sync": {"state": "new", "fails": 0, "first_fail": None, "last_error": None, "next_due": 0},
        },
        merge=True,
    )
    if not (previous or {}).get("created_at"):
        ref.set({"created_at": firestore.SERVER_TIMESTAMP}, merge=True)

    tg(
        "sendMessage", chat_id=CHANNEL_ID,
        text=f"🟢 ربط تلقائي ناجح: <code>{uid}</code> · {body.mt5.login} · {body.mt5.server} · {account_type}",
        parse_mode="HTML",
    )
    return {"status": "approved"}


def _epoch(v):
    """طابع Firestore الزمني → ثوانٍ منذ 1970 (قابل للإرسال كـ JSON)."""
    try:
        return int(v.timestamp())
    except Exception:
        return None


def _subscription_info(d: dict | None):
    sub = (d or {}).get("subscription") or {}
    exp = sub.get("expires_at") or 0
    if not exp:
        return None
    now = time.time()
    return {
        "active": exp > now,
        "expires_at": int(exp),
        "days_left": max(0, math.ceil((exp - now) / 86400)),
        "remaining_days": max(0, math.ceil((exp - now) / 86400)),  # اسم بديل للتوافق
        "package_name_ar": sub.get("package_name_ar"),
        "package_name_en": sub.get("package_name_en"),
    }


_BOT_USERNAME = {"v": os.getenv("BOT_USERNAME") or None}


def _bot_username():
    """اسم البوت لرابط الدعوة t.me/<bot>?start=<code>. يُجلب مرة واحدة ثم يُخزَّن."""
    if not _BOT_USERNAME["v"]:
        _BOT_USERNAME["v"] = (tg("getMe").get("result") or {}).get("username")
    return _BOT_USERNAME["v"]


def _public_settings() -> dict:
    s = billing.get_settings(db)
    return {
        "kill_switch": bool(s.get("kill_switch")),
        "referral_enabled": bool(s.get("referral_enabled")),
        "referral_days": s.get("referral_days", 7),
    }


@app.post("/api/status")
def status(body: StatusRequest):
    user = verify_init_data(body.init_data)
    settings = _public_settings()
    snap = user_ref(user["id"]).get()
    if not snap.exists:
        return {"status": "none", "subscription": None, "referral_code": None, "settings": settings,
                "bot_username": _bot_username()}
    d = snap.to_dict()
    out = {
        "status": d.get("status") or "none",  # مستند بلا status (مثلًا أنشأته الإحالة) = مستخدم جديد
        "reason": d.get("rejection_reason"),
        "language": d.get("language"),
        "nickname": d.get("nickname"),
        "avatar": d.get("avatar"),
        "subscription": _subscription_info(d),
        "referral_code": d.get("referral_code") or billing.ensure_referral_code(db, user["id"]),
        "settings": settings,
        "bot_username": _bot_username(),
    }
    if out["status"] == "approved":
        # لوحة الحساب: أرقام حساب المستخدم نفسه فقط (الهوية مؤكدة من initData)
        live = d.get("live")
        sync = d.get("sync") or {}
        out.update(
            account={"login": d.get("mt5_login"), "server": d.get("mt5_server")},
            live={**live, "updated_at": _epoch(live.get("updated_at"))} if live else None,
            report=d.get("report"),
            sync={"state": sync.get("state", "new"), "last_ok": _epoch(sync.get("last_ok"))},
        )
    return out


# ───────────────────────── Webhook تلجرام ─────────────────────────
def finalize(uid: int, approved: bool, reason=None) -> str:
    """يحسم الطلب ويُبلغ المستخدم. يرجع: ok | missing | handled."""
    ref = user_ref(uid)
    snap = ref.get()
    if not snap.exists:
        return "missing"
    data = snap.to_dict()
    if data.get("status") != "pending":
        return "handled"

    lang = data.get("language", "en")
    if approved:
        ref.update({"status": "approved", "decided_at": firestore.SERVER_TIMESTAMP, "sync": {"state": "new"}})
        text = USER_MSG["approved"][lang]
    else:
        reason_text = reason[lang] if isinstance(reason, dict) else str(reason)
        ref.update(
            {
                "status": "rejected",
                "rejection_reason": reason_text,
                "decided_at": firestore.SERVER_TIMESTAMP,
            }
        )
        text = USER_MSG["rejected"][lang].format(reason=reason_text)

    tg("sendMessage", chat_id=uid, text=text)
    return "ok"


def mark_channel_message(chat_id, message_id, label):
    if chat_id and message_id:
        tg(
            "editMessageReplyMarkup",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=done_keyboard(label),
        )


def handle_callback(cq: dict):
    qid = cq["id"]
    admin = cq["from"]
    msg = cq.get("message") or {}
    chat_id = msg.get("chat", {}).get("id")
    message_id = msg.get("message_id")
    data = cq.get("data", "")

    def answer(text="", alert=False):
        tg("answerCallbackQuery", callback_query_id=qid, text=text, show_alert=alert)

    if data == "noop":
        return answer()
    if admin["id"] not in ADMIN_IDS:
        return answer("غير مصرّح لك بهذا الإجراء", True)

    action, _, rest = data.partition(":")
    uid_str, _, extra = rest.partition(":")
    if not uid_str.isdigit():
        return answer()
    uid = int(uid_str)
    admin_name = admin.get("first_name", "Admin")

    if action == "ap":
        outcome = finalize(uid, True)
        if outcome == "ok":
            mark_channel_message(chat_id, message_id, f"✅ تمت الموافقة · {admin_name}")
            return answer("تمت الموافقة")
        return answer("سبق البتّ في هذا الطلب" if outcome == "handled" else "الطلب غير موجود", True)

    if action == "rj":
        tg("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup=reason_keyboard(uid))
        return answer()

    if action == "bk":
        tg("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup=decision_keyboard(uid))
        return answer()

    if action == "rr":
        if extra == "custom":
            db.collection("admin_state").document(str(admin["id"])).set(
                {"uid": uid, "chat_id": chat_id, "message_id": message_id}
            )
            sent = tg(
                "sendMessage",
                chat_id=admin["id"],
                text=f"✍️ اكتب سبب رفض المستخدم <code>{uid}</code> في رسالة واحدة وسأرسله له.",
                parse_mode="HTML",
            )
            if sent.get("ok"):
                return answer("راسلتك على الخاص، اكتب السبب هناك.", True)
            return answer("افتح البوت في الخاص واضغط Start ثم أعد المحاولة.", True)

        reason = REASONS.get(extra)
        if not reason:
            return answer()
        outcome = finalize(uid, False, reason)
        if outcome == "ok":
            mark_channel_message(chat_id, message_id, f"❌ تم الرفض · {admin_name}")
            return answer("تم الرفض وإبلاغ المستخدم")
        return answer("سبق البتّ في هذا الطلب" if outcome == "handled" else "الطلب غير موجود", True)

    answer()


WELCOME_AR = (
    "✨ <b>أهلاً بك في عائلة AW Robot</b>\n\n"
    "منصتك المتكاملة لربط حساب MetaTrader 5 والانطلاق في عالم التداول الآلي باحترافية.\n\n"
    "🔐 <b>ربط آمن وسريع</b> — بياناتك محمية، والتحقق من حسابك يتم تلقائيًا خلال لحظات.\n"
    "📊 <b>متابعة حية</b> — راقب رصيدك وأرباحك ونمو حسابك لحظة بلحظة.\n"
    "🤖 <b>تداول ذكي وآلي</b> — دع الأنظمة تعمل نيابةً عنك بدقة واحترافية.\n\n"
    "كل ما عليك فعله هو الضغط على الزر أدناه، وابدأ رحلتك معنا الآن 👇"
)
WELCOME_EN = (
    "✨ <b>Welcome to the AW Robot family</b>\n\n"
    "Your complete platform for linking your MetaTrader 5 account and stepping into professional automated trading.\n\n"
    "🔐 <b>Secure &amp; fast linking</b> — your data is protected, and your account is verified automatically within moments.\n"
    "📊 <b>Live tracking</b> — watch your balance, profits and growth in real time.\n"
    "🤖 <b>Smart, automated trading</b> — let the system work for you with precision and professionalism.\n\n"
    "Just tap the button below and start your journey with us now 👇"
)
BUTTON_AR = "🚀 ابدأ الآن"
BUTTON_EN = "🚀 Get Started"

LOGO_PATH = os.path.join(os.path.dirname(__file__), "assets", "welcome_logo.mp4")
LOGO_CACHE_FILE = os.path.join(os.path.dirname(__file__), ".welcome_logo_id")


def _upload_logo_and_cache():
    if not os.path.exists(LOGO_PATH):
        return None
    try:
        with open(LOGO_PATH, "rb") as f:
            res = httpx.post(
                f"{TG_API}/sendAnimation",
                data={"chat_id": CHANNEL_ID, "caption": "⚙️ تم تخزين الشعار الترحيبي مؤقتًا", "disable_notification": True},
                files={"animation": ("welcome_logo.mp4", f, "video/mp4")},
                timeout=30,
            ).json()
    except (httpx.HTTPError, OSError) as e:
        log.warning("logo upload failed: %s", e)
        return None
    if not res.get("ok"):
        log.warning("logo upload rejected by Telegram: %s", res)
        return None
    fid = res["result"]["animation"]["file_id"]
    try:
        with open(LOGO_CACHE_FILE, "w") as f:
            f.write(fid)
    except OSError:
        pass
    return fid


def get_logo_file_id():
    try:
        with open(LOGO_CACHE_FILE) as f:
            fid = f.read().strip()
            if fid:
                return fid
    except FileNotFoundError:
        pass
    return _upload_logo_and_cache()


def send_welcome(msg: dict, raw_text: str = ""):
    chat_id = msg["chat"]["id"]
    parts = raw_text.split(maxsplit=1)
    payload = parts[1].strip() if len(parts) > 1 else ""
    if re.fullmatch(r"[A-Za-z0-9]{4,12}", payload or ""):
        snap = user_ref(chat_id).get()
        data = (snap.to_dict() if snap.exists else None) or {}
        if not data.get("referred_by") and not data.get("status"):  # مستخدم جديد فقط
            referrer_uid = billing.find_by_referral_code(db, payload)
            if referrer_uid and str(referrer_uid) != str(chat_id):
                user_ref(chat_id).set({"referred_by": str(referrer_uid)}, merge=True)
    lang = "ar" if (msg.get("from", {}).get("language_code") or "").lower().startswith("ar") else "en"
    text = WELCOME_AR if lang == "ar" else WELCOME_EN
    btn = BUTTON_AR if lang == "ar" else BUTTON_EN
    reply_markup = (
        {"inline_keyboard": [[{"text": btn, "web_app": {"url": WEBAPP_URL}}]]} if WEBAPP_URL else None
    )

    fid = get_logo_file_id()
    if fid:
        payload = {"chat_id": chat_id, "animation": fid, "caption": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        res = tg("sendAnimation", **payload)
        if res.get("ok"):
            return
        log.warning("sendAnimation failed, falling back to text: %s", res)

    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    tg("sendMessage", **payload)


def handle_private_message(msg: dict):
    """/start لأي مستخدم، ورد الأدمن على الخاص بسبب رفض مخصص."""
    if msg.get("chat", {}).get("type") != "private":
        return
    text = (msg.get("text") or "").strip()
    first = text.split()[0].split("@")[0].lower() if text else ""
    if first == "/start":
        return send_welcome(msg, text)
    if first == "/admin":
        return handle_admin_login(msg)

    sender = msg["from"]["id"]
    if sender not in ADMIN_IDS:
        return
    if not text or text.startswith("/"):
        return

    state_ref = db.collection("admin_state").document(str(sender))
    snap = state_ref.get()
    if not snap.exists:
        return
    state = snap.to_dict()
    state_ref.delete()

    outcome = finalize(state["uid"], False, text[:500])
    if outcome == "ok":
        mark_channel_message(state["chat_id"], state["message_id"], f"❌ تم الرفض · {msg['from'].get('first_name', 'Admin')}")
        tg("sendMessage", chat_id=sender, text="✅ أُرسل السبب للمستخدم.")
    else:
        tg("sendMessage", chat_id=sender, text="سبق البتّ في هذا الطلب أو لم يعد موجودًا.")


@app.post("/api/telegram-webhook")
def telegram_webhook(update: dict, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    if not hmac.compare_digest(x_telegram_bot_api_secret_token or "", WEBHOOK_SECRET):
        raise HTTPException(403, "forbidden")

    try:
        if update.get("pre_checkout_query"):
            handle_pre_checkout(update["pre_checkout_query"])
        elif update.get("callback_query"):
            handle_callback(update["callback_query"])
        elif update.get("message"):
            msg = update["message"]
            if msg.get("successful_payment"):
                handle_successful_payment(msg)
            else:
                handle_private_message(msg)
    except Exception:
        # لا نرجع خطأ لتلجرام أبدًا: يكرر الإرسال ويتراكم الطابور ويتوقف الاستقبال
        log.exception("webhook handler error")

    return {"ok": True}



# ═══════════════════════════ لوحة تحكم الأدمن (Web) ═══════════════════════════
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", WEBHOOK_SECRET)
ADMIN_SESSION_HOURS = 12
_login_tokens: dict = {}  # token -> {admin, code, expires, used}


def _cleanup_login_tokens():
    now = time.time()
    for t in [t for t, v in _login_tokens.items() if v["expires"] < now]:
        _login_tokens.pop(t, None)


def handle_admin_login(msg: dict):
    """أمر /admin: يرسل للأدمن رابط دخول سري + رمز تحقق صالحين 5 دقائق."""
    admin_id = msg["from"]["id"]
    chat_id = msg["chat"]["id"]
    if admin_id not in ADMIN_IDS:
        return
    _cleanup_login_tokens()
    token = secrets.token_urlsafe(24)
    code = f"{secrets.randbelow(900000) + 100000}"
    _login_tokens[token] = {"admin": admin_id, "code": code, "expires": time.time() + 300, "used": False}
    base = WEBAPP_URL or FRONTEND_ORIGIN
    link = f"{base}/admin/login?token={token}" if base and base != "*" else "(الرجاء ضبط WEBAPP_URL في .env)"
    tg(
        "sendMessage",
        chat_id=chat_id,
        text=(
            "🔐 <b>دخول لوحة التحكم</b>\n\n"
            f"الرابط (صالح 5 دقائق):\n{link}\n\n"
            f"رمز التحقق: <code>{code}</code>"
        ),
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


def create_admin_session(admin_id: int) -> str:
    payload = {"sub": str(admin_id), "exp": int(time.time()) + ADMIN_SESSION_HOURS * 3600}
    return pyjwt.encode(payload, ADMIN_SESSION_SECRET, algorithm="HS256")


def get_current_admin(request: Request) -> int:
    token = request.cookies.get("aw_admin")
    if not token:
        raise HTTPException(401, "not_authenticated")
    try:
        payload = pyjwt.decode(token, ADMIN_SESSION_SECRET, algorithms=["HS256"])
    except Exception:
        raise HTTPException(401, "invalid_session")
    try:
        admin_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(401, "invalid_session")
    if admin_id not in ADMIN_IDS:
        raise HTTPException(403, "not_admin")
    return admin_id


class AdminVerify(BaseModel):
    token: str
    code: str


@app.post("/api/admin/verify")
def admin_verify(body: AdminVerify, response: Response):
    _cleanup_login_tokens()
    entry = _login_tokens.get(body.token)
    if not entry or entry["used"] or entry["expires"] < time.time():
        raise HTTPException(401, "invalid_or_expired")
    if entry["code"] != body.code.strip():
        raise HTTPException(401, "wrong_code")
    entry["used"] = True
    session = create_admin_session(entry["admin"])
    response.set_cookie(
        "aw_admin", session, max_age=ADMIN_SESSION_HOURS * 3600,
        httponly=True, secure=True, samesite="strict", path="/",
    )
    return {"ok": True}


@app.post("/api/admin/logout")
def admin_logout(response: Response):
    response.delete_cookie("aw_admin", path="/")
    return {"ok": True}


@app.get("/api/admin/me")
def admin_me(admin_id: int = Depends(get_current_admin)):
    return {"admin_id": admin_id}


def _account_type(server) -> str:
    s = (server or "").lower()
    if "demo" in s or "trial" in s:
        return "demo"
    if "real" in s:
        return "real"
    return "unknown"


def _summarize(uid: str, d: dict) -> dict:
    live = d.get("live") or {}
    return {
        "id": uid,
        "username": d.get("username"),
        "nickname": d.get("nickname"),
        "avatar": d.get("avatar"),
        "language": d.get("language"),
        "status": d.get("status"),
        "mt5_login": d.get("mt5_login"),
        "mt5_server": d.get("mt5_server"),
        "account_type": _account_type(d.get("mt5_server")),
        "leverage": live.get("leverage"),
        "balance": live.get("balance"),
        "currency": live.get("currency"),
        "created_at": _epoch(d.get("created_at")),
        "decided_at": _epoch(d.get("decided_at")),
        "rejection_reason": d.get("rejection_reason"),
        "sync_state": (d.get("sync") or {}).get("state"),
    }


@app.get("/api/admin/users")
def admin_users(
    status: str | None = None,
    account_type: str | None = None,
    leverage_min: int | None = None,
    leverage_max: int | None = None,
    search: str | None = None,
    limit: int = 50,
    admin_id: int = Depends(get_current_admin),
):
    from google.cloud.firestore_v1.base_query import FieldFilter

    q = db.collection("users")
    if status:
        q = q.where(filter=FieldFilter("status", "==", status))
    rows = []
    for doc in q.limit(1000).stream():
        d = doc.to_dict() or {}
        row = _summarize(doc.id, d)
        if account_type and row["account_type"] != account_type:
            continue
        if leverage_min is not None and (row["leverage"] or 0) < leverage_min:
            continue
        if leverage_max is not None and (row["leverage"] or 0) > leverage_max:
            continue
        if search:
            hay = f"{row['nickname'] or ''} {row['username'] or ''} {row['mt5_login'] or ''} {row['id']}".lower()
            if search.lower() not in hay:
                continue
        rows.append(row)
    rows.sort(key=lambda r: r["created_at"] or 0, reverse=True)
    return {"total": len(rows), "users": rows[:limit]}


@app.get("/api/admin/users/{uid}")
def admin_user_detail(uid: str, admin_id: int = Depends(get_current_admin)):
    snap = user_ref(uid).get()
    if not snap.exists:
        raise HTTPException(404, "not_found")
    d = snap.to_dict() or {}
    d["id"] = uid
    d["created_at"] = _epoch(d.get("created_at"))
    d["decided_at"] = _epoch(d.get("decided_at"))
    if d.get("live"):
        d["live"] = {**d["live"], "updated_at": _epoch(d["live"].get("updated_at"))}
    return d


class AdminDecision(BaseModel):
    action: str
    reason: str | None = None


@app.post("/api/admin/users/{uid}/decision")
def admin_decision(uid: str, body: AdminDecision, admin_id: int = Depends(get_current_admin)):
    uid_int = int(uid)
    if body.action == "approve":
        outcome = finalize(uid_int, True)
    elif body.action == "reject":
        reason_text = body.reason or REASONS["elig"]["ar"]
        outcome = finalize(uid_int, False, reason_text)
    else:
        raise HTTPException(400, "bad_action")
    if outcome == "missing":
        raise HTTPException(404, "not_found")
    if outcome == "handled":
        raise HTTPException(409, "already_decided")
    tg(
        "sendMessage", chat_id=CHANNEL_ID,
        text=f"🖥️ بُتّ في طلب <code>{uid}</code> من لوحة التحكم ({'موافقة ✅' if body.action == 'approve' else 'رفض ❌'})",
        parse_mode="HTML",
    )
    return {"ok": True}


@app.get("/api/admin/stats")
def admin_stats(admin_id: int = Depends(get_current_admin)):
    from google.cloud.firestore_v1.base_query import FieldFilter

    counts = {}
    for s in ("pending", "approved", "rejected"):
        counts[s] = sum(1 for _ in db.collection("users").where(filter=FieldFilter("status", "==", s)).select([]).stream())
    return counts



# ═══════════════════════════ الإعدادات والباقات (Admin) ═══════════════════════════
@app.get("/api/packages")
def public_packages():
    return {"packages": billing.list_packages(db, active_only=True)}


@app.get("/api/admin/settings")
def admin_get_settings(admin_id: int = Depends(get_current_admin)):
    return billing.get_settings(db)


@app.put("/api/admin/settings")
def admin_update_settings(patch: dict, admin_id: int = Depends(get_current_admin)):
    return billing.update_settings(db, patch)


@app.get("/api/admin/packages")
def admin_list_packages(admin_id: int = Depends(get_current_admin)):
    return {"packages": billing.list_packages(db)}


@app.post("/api/admin/packages")
def admin_create_package(data: dict, admin_id: int = Depends(get_current_admin)):
    try:
        pkg_id = billing.create_package(db, data)
    except (KeyError, ValueError, TypeError):
        raise HTTPException(422, "invalid_package_data")
    return {"id": pkg_id}


@app.put("/api/admin/packages/{pkg_id}")
def admin_update_package(pkg_id: str, patch: dict, admin_id: int = Depends(get_current_admin)):
    billing.update_package(db, pkg_id, patch)
    return {"ok": True}


@app.delete("/api/admin/packages/{pkg_id}")
def admin_delete_package(pkg_id: str, admin_id: int = Depends(get_current_admin)):
    billing.delete_package(db, pkg_id)
    return {"ok": True}



# ═══════════════════════════ الدفع (NOWPayments) والاشتراك ═══════════════════════════
class PaymentCreate(BaseModel):
    init_data: str
    package_id: str


@app.post("/api/payments/create")
def create_payment(body: PaymentCreate):
    user = verify_init_data(body.init_data)
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True)}
    pkg = pkgs.get(body.package_id)
    if not pkg:
        raise HTTPException(404, "package_not_found")

    order_id = f"{user['id']}-{body.package_id}-{int(time.time())}"
    base = FRONTEND_ORIGIN if FRONTEND_ORIGIN != "*" else (WEBAPP_URL or "")
    try:
        inv = payments.create_invoice(
            order_id=order_id,
            amount_usd=pkg["price_usd"],
            description=f"AW Robot - {pkg.get('name_en') or pkg.get('name_ar')}",
            ipn_url=f"{base}/api/payments/nowpayments-webhook",
            success_url=f"{base}/?paid=1",
            cancel_url=f"{base}/?paid=0",
        )
    except payments.PaymentError as e:
        raise HTTPException(502, "payment_provider_error")

    db.collection("payments").document(order_id).set({
        "uid": user["id"],
        "package_id": body.package_id,
        "amount_usd": pkg["price_usd"],
        "status": "waiting",
        "created_at": time.time(),
        "invoice_id": inv.get("id"),
    })
    return {"invoice_url": inv["invoice_url"], "order_id": order_id}


@app.post("/api/payments/nowpayments-webhook")
async def payments_webhook(request: Request):
    raw = await request.body()
    sig = request.headers.get("x-nowpayments-sig", "")
    if not payments.verify_ipn_signature(raw, sig):
        raise HTTPException(401, "bad_signature")

    data = json.loads(raw)
    order_id = data.get("order_id")
    pay_status = data.get("payment_status")
    if not order_id:
        return {"ok": True}

    pay_ref = db.collection("payments").document(order_id)
    pay_snap = pay_ref.get()
    if not pay_snap.exists:
        return {"ok": True}
    pay = pay_snap.to_dict()

    if pay.get("status") == "finished":
        return {"ok": True}  # حماية من التكرار (idempotency)

    pay_ref.set({"status": pay_status}, merge=True)

    if pay_status == "finished":
        pkgs = {p["id"]: p for p in billing.list_packages(db)}
        pkg = pkgs.get(pay["package_id"])
        if pkg:
            pkg["id"] = pay["package_id"]
            new_expiry = billing.extend_subscription(db, pay["uid"], pkg)
            settings = billing.get_settings(db)
            if settings.get("referral_enabled"):
                billing.grant_referral_bonus_if_eligible(db, pay["uid"], settings.get("referral_days", 7))
            pay_ref.set({"status": "finished", "confirmed_at": time.time()}, merge=True)
            tg("sendMessage", chat_id=pay["uid"],
               text="✅ تم تفعيل اشتراكك بنجاح! افتح التطبيق الآن لربط حساب MT5.")
    return {"ok": True}


@app.get("/api/admin/referrals")
def admin_referrals(admin_id: int = Depends(get_current_admin)):
    from google.cloud.firestore_v1.base_query import FieldFilter
    rows = []
    for doc in db.collection("users").where(filter=FieldFilter("referred_by", "!=", None)).stream():
        d = doc.to_dict() or {}
        rows.append({
            "uid": doc.id,
            "nickname": d.get("nickname"),
            "referred_by": d.get("referred_by"),
            "reward_granted": bool(d.get("referral_reward_granted")),
        })
    return {"referrals": rows}



# ═══════════════════════════ الدفع عبر Telegram Stars ═══════════════════════════
class StarsPaymentCreate(BaseModel):
    init_data: str
    package_id: str


@app.post("/api/payments/create-stars")
def create_stars_payment(body: StarsPaymentCreate):
    user = verify_init_data(body.init_data)
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True)}
    pkg = pkgs.get(body.package_id)
    if not pkg:
        raise HTTPException(404, "package_not_found")
    stars = pkg.get("price_stars")
    if not stars:
        raise HTTPException(400, "stars_not_configured_for_package")

    order_id = f"{user['id']}-{body.package_id}-{int(time.time())}"
    res = tg(
        "createInvoiceLink",
        title=f"AW Robot — {pkg.get('name_ar')}",
        description=pkg.get("name_ar") or pkg.get("name_en"),
        payload=order_id,
        provider_token="",
        currency="XTR",
        prices=[{"label": pkg.get("name_ar") or "اشتراك", "amount": int(stars)}],
    )
    if not res.get("ok"):
        raise HTTPException(502, "telegram_invoice_failed")

    db.collection("payments").document(order_id).set({
        "uid": user["id"],
        "package_id": body.package_id,
        "amount_stars": stars,
        "method": "stars",
        "status": "waiting",
        "created_at": time.time(),
    })
    return {"invoice_link": res["result"]}


def handle_pre_checkout(query: dict):
    order_id = query.get("invoice_payload", "")
    ok = bool(order_id) and db.collection("payments").document(order_id).get().exists
    if ok:
        tg("answerPreCheckoutQuery", pre_checkout_query_id=query["id"], ok=True)
    else:
        tg(
            "answerPreCheckoutQuery", pre_checkout_query_id=query["id"], ok=False,
            error_message="انتهت صلاحية طلب الدفع هذا. أعد المحاولة من التطبيق.",
        )


def handle_successful_payment(msg: dict):
    sp = msg["successful_payment"]
    order_id = sp.get("invoice_payload", "")
    pay_ref = db.collection("payments").document(order_id)
    pay_snap = pay_ref.get()
    if not pay_snap.exists:
        return
    pay = pay_snap.to_dict()
    if pay.get("status") == "finished":
        return

    pkgs = {p["id"]: p for p in billing.list_packages(db)}
    pkg = pkgs.get(pay["package_id"])
    if not pkg:
        return
    pkg["id"] = pay["package_id"]
    billing.extend_subscription(db, pay["uid"], pkg)
    settings = billing.get_settings(db)
    if settings.get("referral_enabled"):
        billing.grant_referral_bonus_if_eligible(db, pay["uid"], settings.get("referral_days", 7))
    pay_ref.set(
        {
            "status": "finished",
            "confirmed_at": time.time(),
            "telegram_payment_charge_id": sp.get("telegram_payment_charge_id"),
        },
        merge=True,
    )
    tg("sendMessage", chat_id=pay["uid"], text="✅ تم تفعيل اشتراكك بنجاح! افتح التطبيق الآن لربط حساب MT5.")



# ═══════════════════════════ إعدادات المستخدم: فكّ الربط والملف الشخصي ═══════════════════════════
UNLINK_COOLDOWN_SEC = 24 * 3600


class UnlinkRequest(BaseModel):
    init_data: str


@app.post("/api/unlink")
def unlink_account(body: UnlinkRequest):
    user = verify_init_data(body.init_data)
    ref = user_ref(user["id"])
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(404, "not_found")
    d = snap.to_dict()
    if d.get("status") != "approved":
        raise HTTPException(400, "not_linked")

    last = d.get("last_unlink_at") or 0
    now_ts = time.time()
    if now_ts - last < UNLINK_COOLDOWN_SEC:
        remaining_h = int((UNLINK_COOLDOWN_SEC - (now_ts - last)) / 3600) + 1
        raise HTTPException(429, f"cooldown_{remaining_h}h")

    old_login, old_server = d.get("mt5_login"), d.get("mt5_server")
    ref.set(
        {
            "status": "unlinked",
            "mt5_login": None,
            "mt5_password": None,
            "mt5_server": None,
            "live": None,
            "report": None,
            "stats": None,  # الإحصاءات تخص الحساب الذي فُكّ ربطه
            "sync": None,
            "last_unlink_at": now_ts,
        },
        merge=True,
    )
    tg("sendMessage", chat_id=CHANNEL_ID, parse_mode="HTML",
       text=f"🔓 فكّ ربط: <code>{user['id']}</code> · {escape(str(old_login))} · {escape(str(old_server))}")
    return {"ok": True}


class ProfileUpdate(BaseModel):
    init_data: str
    language: str | None = Field(default=None, pattern="^(ar|en)$")
    nickname: str | None = Field(default=None, min_length=2, max_length=24)
    avatar: str | None = Field(default=None, pattern="^(boy|girl)$")


@app.post("/api/profile")
def update_profile(body: ProfileUpdate):
    user = verify_init_data(body.init_data)
    ref = user_ref(user["id"])
    if not ref.get().exists:
        raise HTTPException(404, "not_found")
    patch = {k: v for k, v in (("language", body.language), ("nickname", body.nickname), ("avatar", body.avatar)) if v}
    if patch:
        ref.set(patch, merge=True)
    return {"ok": True}


class FeedbackRequest(BaseModel):
    init_data: str
    rating: int = Field(ge=1, le=5)
    message: str = Field(default="", max_length=1000)


@app.post("/api/feedback")
def submit_feedback(body: FeedbackRequest):
    """يستقبل تقييم/ملاحظة من المستخدم ويرسلها لقناة الأدمن."""
    user = verify_init_data(body.init_data)
    ref = user_ref(user["id"])
    snap = ref.get()
    nickname = (snap.to_dict() or {}).get("nickname") if snap.exists else None
    stars = "⭐" * body.rating + "☆" * (5 - body.rating)
    text = f"📝 <b>تقييم جديد</b>\n{stars}\nمن: {escape(nickname or user.get('first_name', ''))} (<code>{user['id']}</code>)"
    if body.message.strip():
        text += f"\n\n{escape(body.message.strip())}"
    tg("sendMessage", chat_id=CHANNEL_ID, parse_mode="HTML", text=text, disable_notification=True)
    return {"ok": True}


@app.get("/api/system/status")
def system_status(admin_id: int = Depends(get_current_admin)):
    """فحص صحة الخدمات الخلفية: Firestore، جسر MT5 (heartbeat)، وتكامل n8n إن وُجد."""
    services = {}

    # Firestore
    t0 = time.time()
    try:
        db.collection("config").document("settings").get()
        services["firestore"] = {"status": "up", "latency_ms": round((time.time() - t0) * 1000)}
    except Exception as e:  # noqa: BLE001
        services["firestore"] = {"status": "down", "error": str(e)[:200]}

    # جسر MT5 عبر Wine (heartbeat على منفذ aw-sync، نفس BRIDGE_PORT الافتراضي 8002)
    bridge_host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    bridge_port = int(os.environ.get("BRIDGE_PORT", 8002))
    t0 = time.time()
    try:
        with socket.create_connection((bridge_host, bridge_port), timeout=2) as _s:
            services["mt5_bridge"] = {"status": "up", "latency_ms": round((time.time() - t0) * 1000)}
    except OSError as e:
        services["mt5_bridge"] = {"status": "down", "error": str(e)[:200]}

    # تكامل n8n: غير موجود حاليًا في المشروع
    services["n8n"] = {"status": "not_configured"}

    order = {"up": 0, "degraded": 1, "not_configured": 2, "down": 3}
    overall = max((s["status"] for s in services.values()), key=lambda s: order.get(s, 1))
    return {"overall": overall, "services": services, "checked_at": time.time()}


@app.get("/api/billing/history")
def billing_history(init_data: str):
    """سجل مدفوعات المستخدم (تاريخ، مبلغ، خطة، حالة، معرّف معاملة)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    user = verify_init_data(init_data)
    pkgs = {p["id"]: p for p in billing.list_packages(db)}
    rows = []
    query = db.collection("payments").where(filter=FieldFilter("uid", "==", user["id"])).order_by(
        "created_at", direction="DESCENDING"
    )
    for doc in query.stream():
        p = doc.to_dict() or {}
        pkg = pkgs.get(p.get("package_id"), {})
        if p.get("method") == "stars" or p.get("amount_stars"):
            amount, currency = p.get("amount_stars"), "XTR"
        else:
            amount, currency = p.get("amount_usd"), "USD"
        rows.append({
            "order_id": doc.id,
            "date": p.get("created_at"),
            "amount": amount,
            "currency": currency,
            "plan_name_ar": pkg.get("name_ar"),
            "plan_name_en": pkg.get("name_en"),
            "status": p.get("status"),
            "tx_id": p.get("telegram_payment_charge_id") or p.get("invoice_id") or doc.id,
        })
    return {"payments": rows}
