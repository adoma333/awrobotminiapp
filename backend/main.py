"""
AW Mini App — Backend
FastAPI + Firestore + Telegram Bot API

المسارات:
  POST /api/register          استقبال طلب المستخدم من الـ Mini App وإرساله لقناة الأدمن
  POST /api/status            حالة طلب المستخدم (none / pending / approved / rejected)
  POST /api/telegram-webhook  ضغطات الأزرار في القناة + رد الأدمن بسبب الرفض
"""
import asyncio
import hashlib
import hmac
import json
import logging
import math
import os
import re
import socket
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from html import escape
from urllib.parse import parse_qsl, quote

import firebase_admin
import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
import base64
import billing
import payments
import digest
import heartbeat
import reminders
import rewards
import leaderboard
import ton
from retry import RetryableError, raise_for_retryable, with_backoff
from tenacity import retry, stop_after_attempt, wait_exponential
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


def notify_admins(text: str):
    """تنبيه فوري لكل أدمن في الخاص (وللقناة إن لم يُضبط أي أدمن)."""
    for chat in ADMIN_IDS or [CHANNEL_ID]:
        tg("sendMessage", chat_id=chat, text=text)


def record_system_event(kind: str, detail: dict):
    try:
        db.collection("system_events").document().set({"source": "mt5_heartbeat", "type": kind, "at": time.time(), **detail})
    except Exception:  # noqa: BLE001
        log.exception("system event not recorded")


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_watchdog, daemon=True, name="tg-watchdog").start()
    heartbeat.start(notify_admins, record_system_event)
    _scheduler.add_job(lambda: digest.run_digest(db, tg, "weekly"), "cron", day_of_week="mon", hour=9, id="digest_weekly")
    _scheduler.add_job(lambda: digest.run_digest(db, tg, "monthly"), "cron", day=1, hour=9, id="digest_monthly")
    _scheduler.add_job(retry_inbox, "interval", seconds=60, id="webhook_inbox_retry")
    _scheduler.add_job(cleanup_share_media, "cron", hour=4, id="share_media_cleanup")
    _scheduler.add_job(_leaderboard_tick, "interval", seconds=leaderboard.TICK_SEC, id="leaderboard_tick")
    _scheduler.add_job(lambda: reminders.run_renewal_reminders(db, tg, WEBAPP_URL), "cron", hour=10, id="renewal_reminders")
    if ton.configured():
        _scheduler.add_job(scan_ton_payments, "interval", seconds=60, id="ton_scan")
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)
    heartbeat.stop()


app = FastAPI(title="AW Mini App API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if FRONTEND_ORIGIN == "*" else [FRONTEND_ORIGIN],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
http = httpx.Client(timeout=15)


@with_backoff()
def _tg_call(method: str, params: dict) -> dict:
    return raise_for_retryable(http.post(f"{TG_API}/{method}", json=params)).json()


def tg(method: str, **params) -> dict:
    """استدعاء Telegram Bot API مع إعادة محاولة بتراجع أُسّي على أعطال الشبكة و429/5xx.
    لا يرفع استثناء؛ يرجع {'ok': False} عند الفشل النهائي."""
    try:
        return _tg_call(method, params)
    except (httpx.HTTPError, ValueError, RetryableError) as e:
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


TERMS_VERSION = "2026-09"  # نسخة شروط الاستخدام وإخلاء المسؤولية (Terms & Risks)


class Registration(BaseModel):
    init_data: str
    language: str = Field(pattern="^(ar|en)$")
    profile: Profile
    mt5: MT5
    terms_accepted: bool = False  # موافقة صريحة على Terms & Risks قبل الربط


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

    if not body.terms_accepted:
        raise HTTPException(400, "terms_required")
    settings = billing.get_settings(db)
    if settings.get("kill_switch"):
        raise HTTPException(503, "registration_paused")
    # الربط متاح بلا اشتراك: شراء الباقة يأتي بعد ربط الحساب (من لوحة الحساب)

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
            "terms": {"version": TERMS_VERSION, "accepted_at": now_ts},
            "status": "approved",
            "rejection_reason": None,
            "link_fails": [],
            "decided_at": firestore.SERVER_TIMESTAMP,
            "live": live,
            "report": None,
            "stats": None,  # إحصاءات حساب سابق (بعد فكّ ربط) يجب ألا تختلط بالحساب الجديد
            "sync": {"state": "new", "fails": 0, "first_fail": None, "last_error": None, "next_due": 0},
            **billing.trial_fields_on_first_link(settings, previous, live, body.mt5.server, now_ts),
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
    # بطاقات الخدش: الترحيب عند ربط حساب تجريبي، وبطاقة للمُحيل عند نجاح ربط من دعاه (مرة لكل صديق)
    if account_type == "demo":
        rewards.grant_card(db, uid, "welcome")
    referrer = (previous or {}).get("referred_by")
    if referrer and str(referrer) != str(uid):
        rewards.grant_card(db, referrer, f"referral_{uid}")
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
        "package_id": sub.get("package_id"),
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
    return build_status(verify_init_data(body.init_data))


def build_status(user: dict) -> dict:
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
        "scratch_pending": len(d.get("scratch_pending") or []),
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


SSE_POLL_SEC = float(os.getenv("SSE_POLL_SEC", "5"))
SSE_PING_SEC = 15


@app.get("/api/stream")
async def status_stream(init_data: str, request: Request):
    """Server-Sent Events: يبث حالة الحساب والاشتراك (الدفع) والرصيد والمزامنة فور تغيّرها،
    بنفس شكل /api/status، فلا تحتاج الواجهة لسحب الشاشة أو الاستعلام الدوري."""
    user = verify_init_data(init_data)

    async def events():
        yield "retry: 3000\n\n"
        last, last_sent = None, time.time()
        while not await request.is_disconnected():
            try:
                data = await run_in_threadpool(build_status, user)
                payload = json.dumps(data, default=str, sort_keys=True, ensure_ascii=False)
                if payload != last:
                    last, last_sent = payload, time.time()
                    yield f"event: status\ndata: {payload}\n\n"
                elif time.time() - last_sent >= SSE_PING_SEC:
                    last_sent = time.time()
                    yield ": ping\n\n"  # يبقي الاتصال حيًا عبر nginx (proxy_read_timeout)
            except Exception:  # noqa: BLE001
                log.exception("sse status error")
            await asyncio.sleep(SSE_POLL_SEC)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
            elif msg.get("contact"):
                handle_contact(msg)
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
    pkgs = billing.list_packages(db, active_only=True)
    rate = ton.usd_rate() if ton.configured() else None
    for p in pkgs:  # سعر TON متغيّر حسب السوق (يُحسب من السعر بالدولار)
        p["price_ton"] = ton.usd_to_ton(p["price_usd"], rate) if rate else None
    return {"packages": pkgs, "ton_enabled": bool(rate), "ton_rate": rate}


@app.get("/api/admin/settings")
def admin_get_settings(admin_id: int = Depends(get_current_admin)):
    return billing.get_settings(db)


@app.put("/api/admin/settings")
def admin_update_settings(patch: dict, admin_id: int = Depends(get_current_admin)):
    return billing.update_settings(db, patch)


@app.get("/api/admin/packages")
def admin_list_packages(admin_id: int = Depends(get_current_admin)):
    return {"packages": billing.list_packages(db)}


@app.post("/api/admin/packages/seed")
def admin_seed_packages(admin_id: int = Depends(get_current_admin)):
    """يستورد الباقات المقترحة (Starter / Pro / Premium) غير الموجودة."""
    return {"created": billing.seed_packages(db)}


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



# ═══════════════════════════ تفعيل الاشتراك (موحّد لكل وسائل الدفع) ═══════════════════════════
PAID_MSG = "✅ تم تفعيل اشتراكك بنجاح!"
_activation_lock = threading.Lock()  # webhook + فحص دوري + زر التحقق قد تصل معًا لنفس الطلب


def activate_payment(order_id: str, extra: dict | None = None) -> bool:
    """يفعّل الاشتراك لطلب دفع مؤكَّد ويعيد True إن فعّله الآن. آمن عند التكرار (idempotent)."""
    with _activation_lock:
        pay_ref = db.collection("payments").document(order_id)
        snap = pay_ref.get()
        if not snap.exists:
            return False
        pay = snap.to_dict()
        if pay.get("status") == "finished":
            return False
        pkgs = {p["id"]: p for p in billing.list_packages(db)}
        pkg = pkgs.get(pay["package_id"])
        if not pkg:
            return False
        pkg["id"] = pay["package_id"]
        billing.extend_subscription(db, pay["uid"], pkg)
        if pay.get("bonus_days"):  # جائزة خدش "أيام مجانية" طُبّقت على هذا الطلب
            billing._add_days(db, pay["uid"], int(pay["bonus_days"]))
        if pay.get("reward_id"):  # الجائزة تُعلَّم مستخدمة بعد نجاح الدفع فقط
            rewards.mark_used(db, pay["reward_id"], order_id)
        settings = billing.get_settings(db)
        if settings.get("referral_enabled"):
            billing.grant_referral_bonus_if_eligible(db, pay["uid"], settings.get("referral_days", 7))
        pay_ref.set({"status": "finished", "confirmed_at": time.time(), **(extra or {})}, merge=True)
    tg("sendMessage", chat_id=pay["uid"], text=PAID_MSG)
    return True


# ═══════════════════════════ صندوق الـ webhooks الواردة (لا يضيع إشعار دفع) ═══════════════════════════
INBOX = "webhook_inbox"
INBOX_MAX_ATTEMPTS = 10


def inbox_put(source: str, payload: dict) -> str:
    """يحفظ الإشعار الوارد أولًا (قبل الرد 200) ثم يُعالَج في الخلفية."""
    ref = db.collection(INBOX).document()
    ref.set({"source": source, "payload": payload, "received_at": time.time(), "processed": False, "attempts": 0})
    return ref.id


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.5, max=4), reraise=True)
def _handle_inbox(source: str, payload: dict):
    if source == "nowpayments":
        process_nowpayments(payload)
    elif source == "ton":
        scan_ton_payments(raise_errors=True)


def process_inbox_item(item_id: str):
    ref = db.collection(INBOX).document(item_id)
    snap = ref.get()
    if not snap.exists:
        return
    item = snap.to_dict()
    if item.get("processed"):
        return
    try:
        _handle_inbox(item["source"], item.get("payload") or {})
        ref.set({"processed": True, "processed_at": time.time()}, merge=True)
    except Exception as e:  # noqa: BLE001 — يبقى في الصندوق وتعيده المهمة الدورية
        log.exception("inbox item %s failed", item_id)
        ref.set({"attempts": int(item.get("attempts") or 0) + 1, "last_error": str(e)[:300]}, merge=True)


def retry_inbox():
    """مهمة دورية: تعيد معالجة أي إشعار لم يكتمل (هبوط مؤقت لـ Firestore/toncenter...)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time()
    for doc in db.collection(INBOX).where(filter=FieldFilter("processed", "==", False)).stream():
        d = doc.to_dict() or {}
        if int(d.get("attempts") or 0) < INBOX_MAX_ATTEMPTS and now - (d.get("received_at") or 0) > 30:
            process_inbox_item(doc.id)


# ═══════════════════════════ الدفع (NOWPayments) ═══════════════════════════
class PaymentCreate(BaseModel):
    init_data: str
    package_id: str
    reward_id: str | None = None  # جائزة خدش صالحة تُطبَّق تلقائيًا على المبلغ
    pay_currency: str | None = None  # مع قيمة: بوابة مخصّصة (عنوان + مبلغ) بدل صفحة NOWPayments المستضافة


def checkout_reward(uid, reward_id) -> dict | None:
    """يتحقق من جائزة الخدش قبل إنشاء طلب الدفع (منتهية/مستخدمة/ليست له → رفض)."""
    if not reward_id:
        return None
    try:
        return rewards.validate(db, uid, reward_id, rewards.CHECKOUT_TYPES)
    except rewards.RewardError as e:
        raise HTTPException(e.status, e.code)


def reward_fields(card, reward_id, full_price) -> dict:
    if not card:
        return {}
    _, bonus = rewards.apply_to_amount(card, full_price)
    return {"reward_id": reward_id, "bonus_days": bonus, "price_full": full_price}


@app.post("/api/payments/create")
def create_payment(body: PaymentCreate):
    user = verify_init_data(body.init_data)
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True)}
    pkg = pkgs.get(body.package_id)
    if not pkg:
        raise HTTPException(404, "package_not_found")
    card = checkout_reward(user["id"], body.reward_id)
    amount_usd = pkg["price_usd"]
    if card:
        amount_usd = round(rewards.apply_to_amount(card, amount_usd)[0], 2)

    order_id = f"{user['id']}-{body.package_id}-{int(time.time())}"
    base = FRONTEND_ORIGIN if FRONTEND_ORIGIN != "*" else (WEBAPP_URL or "")
    if body.pay_currency:
        return _create_direct_crypto(user, body, pkg, card, amount_usd, order_id, base)
    try:
        inv = payments.create_invoice(
            order_id=order_id,
            amount_usd=amount_usd,
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
        "amount_usd": amount_usd,
        "method": "nowpayments",
        "status": "waiting",
        "created_at": time.time(),
        "invoice_id": inv.get("id"),
        **reward_fields(card, body.reward_id, pkg["price_usd"]),
    })
    return {
        "invoice_url": inv["invoice_url"],
        "order_id": order_id,
        "invoice_id": inv.get("id"),
        # بوابة NOWPayments المضمّنة: تُعرض داخل الـ Mini App في iframe بدل متصفح خارجي
        "widget_url": payments.widget_url(inv.get("id")) if inv.get("id") else None,
    }


def _create_direct_crypto(user, body, pkg, card, amount_usd, order_id, base):
    try:
        pay = payments.create_direct_payment(
            order_id=order_id,
            amount_usd=amount_usd,
            pay_currency=body.pay_currency,
            description=f"AW Robot - {pkg.get('name_en') or pkg.get('name_ar')}",
            ipn_url=f"{base}/api/payments/nowpayments-webhook",
        )
    except payments.PaymentError as e:
        code = str(e)
        raise HTTPException(400 if code in ("unsupported_currency", "amount_too_low") else 502,
                            code if code in ("unsupported_currency", "amount_too_low") else "payment_provider_error")
    info = {
        "payment_id": pay.get("payment_id"),
        "pay_address": pay.get("pay_address"),
        "pay_amount": pay.get("pay_amount"),
        "pay_currency": pay.get("pay_currency") or body.pay_currency,
        "payin_extra_id": pay.get("payin_extra_id"),  # memo/tag مطلوب لبعض الشبكات (مثل TON)
        "network": payments.CURRENCIES.get(body.pay_currency, ("", ""))[1],
        "expires_at": pay.get("expiration_estimate_date"),
    }
    db.collection("payments").document(order_id).set({
        "uid": user["id"],
        "package_id": body.package_id,
        "amount_usd": amount_usd,
        "method": "nowpayments",
        "status": "waiting",
        "created_at": time.time(),
        "np_payment_id": info["payment_id"],
        "np_pay": info,
        **reward_fields(card, body.reward_id, pkg["price_usd"]),
    })
    return {"order_id": order_id, "amount_usd": amount_usd, **info}


@app.get("/api/payments/currencies")
def payment_currencies():
    return {"currencies": payments.currencies()}


class OrderStatus(BaseModel):
    init_data: str
    order_id: str


@app.post("/api/payments/status")
def payment_status(body: OrderStatus):
    """حالة طلب الدفع لشاشة الدفع المخصّصة. يسأل NOWPayments مباشرة (بحد أدنى 10ث بين الطلبات)."""
    user = verify_init_data(body.init_data)
    ref = db.collection("payments").document(body.order_id)
    snap = ref.get()
    pay = snap.to_dict() if snap.exists else None
    if not pay or str(pay.get("uid")) != str(user["id"]):
        raise HTTPException(404, "order_not_found")
    status = pay.get("status")
    if status not in ("finished", "failed", "expired", "refunded") and pay.get("np_payment_id"):
        if time.time() - float(pay.get("np_checked_at") or 0) >= 10:
            ref.set({"np_checked_at": time.time()}, merge=True)
            try:
                remote = payments.get_payment(pay["np_payment_id"]).get("payment_status")
            except payments.PaymentError:
                remote = None
            if remote and remote != status:
                process_nowpayments({"order_id": body.order_id, "payment_status": remote, "payment_id": pay["np_payment_id"]})
                status = ref.get().to_dict().get("status")
    return {"status": status}


def process_nowpayments(data: dict):
    order_id = data.get("order_id")
    pay_status = data.get("payment_status")
    if not order_id:
        return
    pay_ref = db.collection("payments").document(order_id)
    pay_snap = pay_ref.get()
    if not pay_snap.exists or pay_snap.to_dict().get("status") == "finished":
        return  # حماية من التكرار (idempotency)
    if pay_status == "finished":
        activate_payment(order_id, {"np_payment_id": data.get("payment_id")})
    else:
        pay_ref.set({"status": pay_status}, merge=True)


@app.post("/api/payments/nowpayments-webhook")
async def payments_webhook(request: Request, background: BackgroundTasks):
    raw = await request.body()
    sig = request.headers.get("x-nowpayments-sig", "")
    if not payments.verify_ipn_signature(raw, sig):
        raise HTTPException(401, "bad_signature")
    item_id = await run_in_threadpool(inbox_put, "nowpayments", json.loads(raw))
    background.add_task(process_inbox_item, item_id)
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




# ═══════════════════════════ الدفع عبر محفظة TON (TON Connect) ═══════════════════════════
class TonPaymentCreate(BaseModel):
    init_data: str
    package_id: str
    reward_id: str | None = None


@app.get("/api/tonconnect-manifest.json")
def tonconnect_manifest(response: Response):
    response.headers["Access-Control-Allow-Origin"] = "*"  # المحافظ تجلبه من نطاقاتها
    base = WEBAPP_URL or ""
    return {"url": base, "name": "AW Robot", "iconUrl": f"{base}/icon.png"}


@app.post("/api/payments/create-ton")
def create_ton_payment(body: TonPaymentCreate):
    user = verify_init_data(body.init_data)
    if not ton.configured():
        raise HTTPException(503, "ton_not_configured")
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True)}
    pkg = pkgs.get(body.package_id)
    if not pkg:
        raise HTTPException(404, "package_not_found")
    rate = ton.usd_rate()
    if not rate:
        raise HTTPException(503, "ton_rate_unavailable")
    full = ton.usd_to_ton(pkg["price_usd"], rate)  # سعر متغيّر حسب سعر TON الحالي
    card = checkout_reward(user["id"], body.reward_id)
    price = round(rewards.apply_to_amount(card, full)[0], 4) if card else full

    order_id = f"{user['id']}-{body.package_id}-{int(time.time())}"
    nano = ton.to_nano(price)
    db.collection("payments").document(order_id).set({
        "uid": user["id"],
        "package_id": body.package_id,
        "amount_ton": price,
        "amount_nano": nano,
        "ton_rate_usd": rate,
        "method": "ton",
        "status": "waiting",
        "created_at": time.time(),
        **reward_fields(card, body.reward_id, full),
    })
    return {
        "order_id": order_id,
        "address": ton.TON_WALLET,
        "amount_nano": str(nano),
        "payload": ton.comment_payload(order_id),  # التعليق = order_id، به نطابق المعاملة على الشبكة
        "valid_until": int(time.time()) + 600,
    }


def scan_ton_payments(only_order: str | None = None, raise_errors: bool = False) -> int:
    """يطابق طلبات TON المنتظرة مع المعاملات الواردة الفعلية على الشبكة ويفعّل المؤكَّد منها."""
    if not ton.configured():
        return 0
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time()
    q = (
        db.collection("payments")
        .where(filter=FieldFilter("method", "==", "ton"))
        .where(filter=FieldFilter("status", "==", "waiting"))
    )
    pending = []
    for doc in q.stream():
        p = doc.to_dict() or {}
        if only_order and doc.id != only_order:
            continue
        if now - (p.get("created_at") or 0) > ton.TON_PAYMENT_WINDOW:
            db.collection("payments").document(doc.id).set({"status": "expired"}, merge=True)
            continue
        pending.append((doc.id, p))
    if not pending:
        return 0
    try:
        txs = ton.fetch_transactions()
    except ton.TonError as e:
        log.warning("toncenter unavailable: %s", e)
        if raise_errors:
            raise
        return 0

    done = 0
    for order_id, p in pending:
        tx = ton.find_payment(txs, order_id, int(p.get("amount_nano") or 0))
        if not tx:
            continue
        claim = db.collection("ton_txs").document(hashlib.sha256(tx["hash"].encode()).hexdigest())
        if claim.get().exists:
            continue  # معاملة واحدة لا تفعّل طلبين
        claim.set({"order_id": order_id, "hash": tx["hash"], "at": now})
        if activate_payment(order_id, {"ton_tx_hash": tx["hash"], "ton_sender": tx["source"]}):
            done += 1
    return done


class TonCheck(BaseModel):
    init_data: str
    order_id: str


@app.post("/api/payments/ton-check")
def ton_check(body: TonCheck):
    """تستدعيه الواجهة بعد إرسال المعاملة لتسريع التفعيل (المهمة الدورية تغطيه على أي حال)."""
    user = verify_init_data(body.init_data)
    ref = db.collection("payments").document(body.order_id)
    snap = ref.get()
    if not snap.exists or str(snap.to_dict().get("uid")) != str(user["id"]):
        raise HTTPException(404, "order_not_found")
    if snap.to_dict().get("status") != "finished":
        scan_ton_payments(only_order=body.order_id)
    return {"status": ref.get().to_dict().get("status")}


@app.post("/api/payments/ton-webhook")
async def ton_webhook(request: Request, background: BackgroundTasks):
    """إشعار من مزوّد مراقبة شبكة TON (مثل TonAPI webhooks) بوصول معاملة لمحفظة المشروع.
    محتواه لا يُصدَّق: نستخدمه فقط كمنبّه ثم نتحقق من المعاملة على الشبكة نفسها."""
    auth = request.headers.get("authorization", "")
    given = request.headers.get("x-webhook-secret") or request.query_params.get("secret") or (
        auth[7:] if auth.lower().startswith("bearer ") else ""
    )
    if not ton.TON_WEBHOOK_SECRET or not hmac.compare_digest(given, ton.TON_WEBHOOK_SECRET):
        raise HTTPException(401, "bad_secret")
    raw = await request.body()
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        payload = {}
    item_id = await run_in_threadpool(inbox_put, "ton", payload if isinstance(payload, dict) else {})
    background.add_task(process_inbox_item, item_id)
    return {"ok": True}


# ═══════════════════════════ الدفع عبر Telegram Stars ═══════════════════════════
class StarsPaymentCreate(BaseModel):
    init_data: str
    package_id: str
    reward_id: str | None = None


@app.post("/api/payments/create-stars")
def create_stars_payment(body: StarsPaymentCreate):
    user = verify_init_data(body.init_data)
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True)}
    pkg = pkgs.get(body.package_id)
    if not pkg:
        raise HTTPException(404, "package_not_found")
    full = pkg.get("price_stars")
    if not full:
        raise HTTPException(400, "stars_not_configured_for_package")
    card = checkout_reward(user["id"], body.reward_id)
    stars = max(1, int(round(rewards.apply_to_amount(card, full)[0]))) if card else full

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
        **reward_fields(card, body.reward_id, full),
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
    activate_payment(sp.get("invoice_payload", ""), {"telegram_payment_charge_id": sp.get("telegram_payment_charge_id")})



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


# ═══════════════════════════ بطاقات الخدش والمكافآت (Scratch & Win) ═══════════════════════════
REWARD_SECRET = os.getenv("REWARD_SECRET", WEBHOOK_SECRET)
REWARD_LABEL = {
    "slippage_insurance": "رصيد تداول / تأمين انزلاق ${v}",
    "funded_challenge": "دخول تحدي حساب ممول ${v}",
}


def _reward_http(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except rewards.RewardError as e:
        raise HTTPException(e.status, e.code)


class InitOnly(BaseModel):
    init_data: str


class ScratchClaim(BaseModel):
    init_data: str
    card_id: str | None = None


class RewardAction(BaseModel):
    init_data: str
    reward_id: str


@app.post("/api/onboarding/complete")
def onboarding_complete(body: InitOnly):
    """إكمال شاشات التعريف: أول خطوة تمنح بطاقة الترحيب (مرة واحدة، مشتركة مع ربط حساب تجريبي)."""
    user = verify_init_data(body.init_data)
    user_ref(user["id"]).set({"onboarded_at": time.time()}, merge=True)
    card = rewards.grant_card(db, user["id"], "welcome")
    return {"ok": True, "card_id": card}


@app.post("/api/scratch/claim")
def scratch_claim(body: ScratchClaim):
    """يولّد جائزة البطاقة على الخادم فقط ويخزّنها في Firestore ثم يعيدها مختومة للعرض."""
    user = verify_init_data(body.init_data)
    return _reward_http(rewards.claim, db, user, body.card_id, REWARD_SECRET)


@app.post("/api/scratch/reveal")
def scratch_reveal(body: ScratchClaim):
    """الواجهة كشفت أكثر من 50%: تبدأ صلاحية الجائزة (بالساعات)."""
    user = verify_init_data(body.init_data)
    if not body.card_id:
        raise HTTPException(422, "card_id_required")
    was_new = (db.collection(rewards.CARDS).document(body.card_id).get().to_dict() or {}).get("status") != "revealed"
    reward = _reward_http(rewards.reveal, db, user["id"], body.card_id)
    if was_new and reward["type"] in rewards.MANUAL_TYPES:  # جوائز يسلّمها الأدمن يدويًا
        label = REWARD_LABEL[reward["type"]].format(v=reward["value"])
        tg("sendMessage", chat_id=CHANNEL_ID, parse_mode="HTML",
           text=f"🎁 جائزة خدش تحتاج تسليمًا يدويًا: {label}\nللمستخدم <code>{user['id']}</code> (البطاقة {escape(body.card_id)})")
    return reward


@app.get("/api/rewards")
def rewards_hub(init_data: str):
    """محفظة المكافآت: بطاقات لم تُكشف + الجوائز (النوع، القيمة، الانتهاء، حالة الاستخدام)."""
    user = verify_init_data(init_data)
    snap = user_ref(user["id"]).get()
    d = (snap.to_dict() or {}) if snap.exists else {}
    out = rewards.list_rewards(db, user["id"])
    out["phone_verified"] = bool(d.get("phone_verified") or user.get("is_premium"))
    out["ttl_hours"] = rewards.get_config(db)["ttl_hours"]
    return out


# ═══════════════════════════ التحليلات والإحالة ═══════════════════════════
@app.get("/api/analytics")
def analytics(init_data: str):
    """إحصاءات الإحالة للمستخدم: المدعوون، من ربط حسابه (إحالة ناجحة)، من دفع، ومعدل التحويل."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    user = verify_init_data(init_data)
    invited = linked = paid = 0
    for doc in db.collection("users").where(filter=FieldFilter("referred_by", "==", str(user["id"]))).stream():
        d = doc.to_dict() or {}
        invited += 1
        linked += bool(d.get("trial_checked") or d.get("status") == "approved")  # trial_checked = ربط مرة على الأقل
        paid += bool(d.get("referral_reward_granted"))
    return {
        "referrals": {
            "invited": invited,
            "linked": linked,
            "paid": paid,
            "conversion_pct": round(linked / invited * 100, 1) if invited else None,
        }
    }


# ═══════════════════════════ مشاركة القصص والمنشورات ═══════════════════════════
MEDIA_DIR = os.getenv("MEDIA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "share")
SHARE_MAX_BYTES = 1_500_000
SHARE_DAILY_LIMIT = 30
SHARE_KEEP_DAYS = 30
_SHARE_ID = re.compile(r"^[A-Za-z0-9_-]{8,24}$")
SHARE_PLATFORMS = {"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook", "x": "X",
                   "whatsapp": "WhatsApp", "telegram": "Telegram", "snapchat": "Snapchat", "threads": "Threads"}


class ShareCreate(BaseModel):
    init_data: str
    story: str  # JPEG بصيغة base64 (1080×1920)
    post: str   # JPEG بصيغة base64 (1080×1080)
    caption: str = Field(default="", max_length=1500)
    captions: dict[str, str] = {}  # نص مخصّص لكل منصة (instagram, facebook, tiktok, ...)


def _jpeg(b64: str) -> bytes:
    try:
        raw = base64.b64decode(b64.split(",")[-1], validate=True)
    except (ValueError, TypeError):
        raise HTTPException(422, "bad_image")
    if len(raw) > SHARE_MAX_BYTES or not raw.startswith(b"\xff\xd8\xff"):
        raise HTTPException(422, "bad_image")
    return raw


@app.post("/api/share/create")
def share_create(body: ShareCreate):
    """يرفع صورة القصة وصورة المنشور ويعيد روابط عامة: للقصة (Telegram Stories)، وللصورة، ولصفحة مشاركة بمعاينة كاملة."""
    user = verify_init_data(body.init_data)
    uid = str(user["id"])
    story, post = _jpeg(body.story), _jpeg(body.post)
    ref = user_ref(uid)
    d = (ref.get().to_dict() or {})
    day = time.strftime("%Y-%m-%d", time.gmtime())
    count = (d.get("share_quota") or {}).get(day, 0)
    if count >= SHARE_DAILY_LIMIT:
        raise HTTPException(429, "share_limit")
    ref.set({"share_quota": {day: count + 1}}, merge=True)

    sid = secrets.token_urlsafe(9)
    os.makedirs(MEDIA_DIR, exist_ok=True)
    for kind, data in (("story", story), ("post", post)):
        with open(os.path.join(MEDIA_DIR, f"{sid}_{kind}.jpg"), "wb") as f:
            f.write(data)
    code = d.get("referral_code") or billing.ensure_referral_code(db, uid)
    bot = _bot_username()
    captions = {k: str(v)[:2200] for k, v in (body.captions or {}).items() if k in SHARE_PLATFORMS}
    db.collection("shares").document(sid).set({
        "uid": uid, "caption": body.caption.strip(), "captions": captions, "created_at": time.time(),
        "link": f"https://t.me/{bot}?start={code}" if bot else WEBAPP_URL,
    })
    base = f"{WEBAPP_URL}/api/share"
    return {"id": sid, "story_url": f"{base}/img/{sid}_story.jpg", "post_url": f"{base}/img/{sid}_post.jpg",
            "page_url": f"{base}/p/{sid}"}


@app.get("/api/share/img/{name}")
def share_image(name: str):
    sid, _, kind = name.removesuffix(".jpg").rpartition("_")
    if not _SHARE_ID.match(sid) or kind not in ("story", "post"):
        raise HTTPException(404, "not_found")
    path = os.path.join(MEDIA_DIR, f"{sid}_{kind}.jpg")
    if not os.path.exists(path):
        raise HTTPException(404, "not_found")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=604800"})


SHARE_UI = {
    "ar": {"dir": "rtl", "title": "انشر على {p}", "go": "انشر الآن على {p}", "copy": "نسخ النص", "copied": "✓ نُسخ",
           "save": "حفظ الصورة", "s1": "النص يُنسخ تلقائيًا عند الضغط", "s2": "اختر {p} من قائمة المشاركة",
           "s3": "الصق النص (لصق) ثم انشر", "cta": "ابدأ الآن مع AW Robot", "fb_link": "مشاركة كرابط",
           "saved": "حُفظت الصورة — افتح {p} وانشرها والصق النص"},
    "en": {"dir": "ltr", "title": "Post to {p}", "go": "Post to {p} now", "copy": "Copy caption", "copied": "✓ Copied",
           "save": "Save image", "s1": "The caption is copied when you tap", "s2": "Pick {p} in the share sheet",
           "s3": "Paste the caption and publish", "cta": "Start with AW Robot", "fb_link": "Share as link",
           "saved": "Image saved — open {p}, post it and paste the caption"},
}
# بعد التنزيل (أجهزة بلا Web Share): نفتح المنصة مباشرة
SHARE_FALLBACK = {
    "instagram": "https://www.instagram.com/", "tiktok": "https://www.tiktok.com/upload", "snapchat": "https://www.snapchat.com/",
    "threads": "https://www.threads.net/", "facebook": "https://www.facebook.com/sharer/sharer.php?u={page}",
    "x": "https://twitter.com/intent/tweet?text={text}&url={page}", "whatsapp": "https://wa.me/?text={text}",
    "telegram": "https://t.me/share/url?url={page}&text={text}",
}
STORY_PLATFORMS = {"instagram", "tiktok", "snapchat"}


@app.get("/api/share/p/{sid}", response_class=HTMLResponse)
def share_page(sid: str, to: str | None = None, lang: str = "ar"):
    """بلا to: صفحة معاينة بوسوم Open Graph (للروابط في فيسبوك وX وواتساب وتلجرام) ثم تحويل لرابط الدعوة.
    مع to=<منصة>: صفحة "انشر الآن" تُفتح في متصفح الهاتف (خارج تلجرام) حيث تعمل نافذة المشاركة الأصلية
    بالصورة، فيفتح محرر المنصة مباشرة، مع نسخ نص تلك المنصة تلقائيًا."""
    snap = db.collection("shares").document(sid).get() if _SHARE_ID.match(sid) else None
    if not snap or not snap.exists:
        raise HTTPException(404, "not_found")
    d = snap.to_dict() or {}
    page = f"{WEBAPP_URL}/api/share/p/{sid}"
    post_img = f"{WEBAPP_URL}/api/share/img/{sid}_post.jpg"
    link_raw = d.get("link") or WEBAPP_URL
    link = escape(link_raw, quote=True)
    base_caption = d.get("caption") or "AW Robot"
    js = lambda v: json.dumps(v, ensure_ascii=False).replace("</", "<\\/")  # noqa: E731

    if to not in SHARE_PLATFORMS:
        desc = escape(" ".join(base_caption.split())[:280], quote=True)
        body = escape(base_caption).replace("\n", "<br>")
        return f"""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AW Robot</title>
<meta property="og:type" content="website"><meta property="og:site_name" content="AW Robot">
<meta property="og:title" content="AW Robot — التداول الآلي بالذكاء الاصطناعي">
<meta property="og:description" content="{desc}">
<meta property="og:image" content="{post_img}"><meta property="og:image:width" content="1080"><meta property="og:image:height" content="1080">
<meta property="og:url" content="{page}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{post_img}">
<meta name="twitter:title" content="AW Robot"><meta name="twitter:description" content="{desc}">
<style>body{{margin:0;background:#000;color:#f5efe8;font-family:system-ui,sans-serif;display:flex;justify-content:center}}
main{{max-width:480px;padding:20px;text-align:center}}img{{width:100%;border-radius:12px}}p{{line-height:1.7;color:#cfc6bb}}
a{{display:inline-block;margin-top:12px;padding:14px 28px;border-radius:10px;background:linear-gradient(135deg,#ff8a00,#ff5a00);color:#1a0d00;font-weight:800;text-decoration:none}}</style>
</head><body><main><img src="{post_img}" alt="AW Robot"><p>{body}</p><a href="{link}">ابدأ الآن مع AW Robot</a></main>
<script>setTimeout(function(){{location.href={js(link_raw)}}},2500)</script></body></html>"""

    ui = SHARE_UI["en" if lang == "en" else "ar"]
    name = SHARE_PLATFORMS[to]
    kind = "story" if to in STORY_PLATFORMS else "post"
    img = f"{WEBAPP_URL}/api/share/img/{sid}_{kind}.jpg"
    caption = (d.get("captions") or {}).get(to) or base_caption
    fallback = SHARE_FALLBACK[to].format(page=quote(page, safe=""), text=quote(caption, safe=""))
    f = lambda k: escape(ui[k].format(p=name))  # noqa: E731
    return f"""<!doctype html><html lang="{'en' if lang == 'en' else 'ar'}" dir="{ui['dir']}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex"><title>AW Robot · {escape(name)}</title>
<style>
*{{box-sizing:border-box}}body{{margin:0;background:#000;color:#f5efe8;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:460px;margin:0 auto;padding:18px 18px 32px}}
.bar{{display:flex;direction:ltr}}.bar img{{height:30px}}
h1{{margin:18px 0 6px;font-size:24px}}
ol{{margin:0 0 14px;padding:0;list-style:none;display:grid;gap:6px;counter-reset:s}}
li{{counter-increment:s;display:flex;gap:10px;align-items:center;color:#cfc6bb;font-size:14px}}
li::before{{content:counter(s);width:22px;height:22px;flex:none;border-radius:50%;display:grid;place-items:center;
  background:rgba(255,138,0,.15);color:#ff8a00;font-weight:800;font-size:12px}}
.pv{{display:block;margin:0 auto 14px;border:1px solid rgba(255,138,0,.35);border-radius:10px;max-height:52vh;max-width:100%}}
.cap{{white-space:pre-wrap;background:rgba(255,138,0,.06);border:1px solid rgba(255,255,255,.1);border-radius:8px;
  padding:12px 14px;font-size:13.5px;line-height:1.7;margin:0 0 14px;max-height:180px;overflow:auto}}
button,a.btn{{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:15px;border-radius:10px;
  border:1px solid rgba(255,138,0,.35);background:#141110;color:#ff8a00;font-family:inherit;font-weight:700;font-size:15px;text-decoration:none;margin-top:10px;cursor:pointer}}
.go{{background:linear-gradient(135deg,#ff8a00,#ff5a00);color:#1a0d00;border:0;font-size:16px;box-shadow:0 10px 28px rgba(255,106,0,.3)}}
.row{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}.row>*{{margin-top:10px}}
.toast{{position:fixed;inset-inline:16px;bottom:22px;padding:12px 14px;border-radius:10px;background:#1a1512;border:1px solid rgba(255,138,0,.4);
  text-align:center;font-size:14px;opacity:0;transform:translateY(10px);transition:.25s}}.toast.on{{opacity:1;transform:none}}
.cta{{margin-top:22px;text-align:center}}.cta a{{color:#8c8378;font-size:13px}}
</style></head><body><main>
<div class="bar"><img src="{WEBAPP_URL}/logo-wordmark.png" alt="AW Robot"></div>
<h1>{f('title')}</h1>
<ol><li>{f('s1')}</li><li>{f('s2')}</li><li>{f('s3')}</li></ol>
<img class="pv" src="{img}" alt="">
<div class="cap" id="cap"></div>
<button class="go" id="go">{f('go')}</button>
<div class="row"><button id="copy">{f('copy')}</button><a class="btn" id="save" href="{img}" download="aw-robot-{kind}.jpg">{f('save')}</a></div>
{f'<a class="btn" href="https://www.facebook.com/sharer/sharer.php?u={quote(page, safe="")}">{f("fb_link")}</a>' if to == "facebook" else ""}
<div class="cta"><a href="{link}">{f('cta')}</a></div>
</main><div class="toast" id="toast"></div>
<script>
var CAP={js(caption)},IMG={js(img)},FALL={js(fallback)},SAVED={js(ui['saved'].format(p=name))},COPIED={js(ui['copied'])};
document.getElementById('cap').textContent=CAP;
function toast(m){{var t=document.getElementById('toast');t.textContent=m;t.className='toast on';setTimeout(function(){{t.className='toast'}},2600)}}
function copy(){{if(navigator.clipboard&&navigator.clipboard.writeText){{return navigator.clipboard.writeText(CAP).catch(function(){{}})}}
  var e=document.createElement('textarea');e.value=CAP;document.body.appendChild(e);e.select();try{{document.execCommand('copy')}}catch(_){{}}e.remove();return Promise.resolve()}}
var file=null;fetch(IMG).then(function(r){{return r.blob()}}).then(function(b){{file=new File([b],'aw-robot.jpg',{{type:'image/jpeg'}})}}).catch(function(){{}});
document.getElementById('copy').onclick=function(){{copy().then(function(){{toast(COPIED)}})}};
document.getElementById('go').onclick=function(){{
  copy();
  if(file&&navigator.canShare&&navigator.canShare({{files:[file]}})){{
    navigator.share({{files:[file],text:CAP}}).catch(function(e){{if(e&&e.name!=='AbortError')fallback()}});return;
  }}
  fallback();
}};
function fallback(){{document.getElementById('save').click();toast(SAVED);setTimeout(function(){{location.href=FALL}},1400)}}
</script></body></html>"""


def cleanup_share_media():
    """يحذف صور المشاركة الأقدم من SHARE_KEEP_DAYS يومًا."""
    if not os.path.isdir(MEDIA_DIR):
        return
    cutoff = time.time() - SHARE_KEEP_DAYS * 86400
    for name in os.listdir(MEDIA_DIR):
        path = os.path.join(MEDIA_DIR, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


# ═══════════════════════════ ترتيب أرباح هذا الأسبوع ═══════════════════════════
@app.get("/api/leaderboard")
def weekly_leaderboard(init_data: str):
    user = verify_init_data(init_data)
    return leaderboard.build(db, user["id"])


def _leaderboard_tick():
    cfg = leaderboard.get_config(db)
    if cfg["enabled"]:
        leaderboard.tick(db, cfg)


@app.get("/api/admin/leaderboard")
def admin_leaderboard_config(admin_id: int = Depends(get_current_admin)):
    return {**leaderboard.get_config(db), "default_profiles": leaderboard.default_config()["profiles"]}


@app.put("/api/admin/leaderboard")
def admin_leaderboard_update(patch: dict, admin_id: int = Depends(get_current_admin)):
    try:
        clean = leaderboard.clean_config(patch)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    db.collection("config").document("leaderboard").set(clean, merge=True)
    return leaderboard.get_config(db)


# ═══════════════════════════ لوحة الأدمن: المكافآت والكوبونات ═══════════════════════════
@app.get("/api/admin/rewards/config")
def admin_rewards_config(admin_id: int = Depends(get_current_admin)):
    return rewards.get_config(db)


@app.put("/api/admin/rewards/config")
def admin_rewards_update(patch: dict, admin_id: int = Depends(get_current_admin)):
    try:
        clean = rewards.clean_config(patch)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    db.collection("config").document("rewards").set(clean, merge=True)
    return rewards.get_config(db)


@app.get("/api/admin/rewards/cards")
def admin_rewards_cards(uid: str | None = None, admin_id: int = Depends(get_current_admin)):
    return rewards.admin_list_cards(db, uid=uid or None)


class AdminGrant(BaseModel):
    uid: str = Field(pattern=r"^\d{1,15}$")
    type: str | None = None   # فارغ = بطاقة خدش عادية؛ وإلا كوبون جاهز بهذا النوع
    value: float | None = None
    hours: int = 24
    notify: bool = True


@app.post("/api/admin/rewards/grant")
def admin_rewards_grant(body: AdminGrant, admin_id: int = Depends(get_current_admin)):
    if body.type:
        if not body.value or body.value <= 0:
            raise HTTPException(422, "value_required")
        value = int(body.value) if float(body.value).is_integer() else body.value
        card_id = _reward_http(rewards.admin_issue_coupon, db, body.uid, body.type, value, body.hours)
        text = "🎁 وصلتك مكافأة جديدة من AW Robot! افتح التطبيق ← المكافآت."
    else:
        card_id = rewards.grant_card(db, body.uid, f"admin_{int(time.time() * 1000)}", force=True)
        text = "🎟️ وصلتك بطاقة خدش جديدة! افتح التطبيق وامسحها."
    if body.notify:
        tg("sendMessage", chat_id=body.uid, text=text)
    return {"ok": True, "card_id": card_id}


class AdminExtend(BaseModel):
    hours: int = Field(ge=1, le=720)


@app.post("/api/admin/rewards/{card_id}/revoke")
def admin_rewards_revoke(card_id: str, admin_id: int = Depends(get_current_admin)):
    _reward_http(rewards.admin_revoke, db, card_id)
    return {"ok": True}


@app.post("/api/admin/rewards/{card_id}/extend")
def admin_rewards_extend(card_id: str, body: AdminExtend, admin_id: int = Depends(get_current_admin)):
    return {"ok": True, "expires_at": _reward_http(rewards.admin_extend, db, card_id, body.hours)}


@app.post("/api/rewards/redeem")
def rewards_redeem(body: RewardAction):
    """جائزة "شهر مجاني": تُفعَّل مباشرة بلا دفع (مع رفض المنتهية أو المستخدمة)."""
    user = verify_init_data(body.init_data)
    card = _reward_http(rewards.validate, db, user["id"], body.reward_id, rewards.REDEEM_TYPES)
    rewards.mark_used(db, body.reward_id, None)
    new_expiry = billing._add_days(db, user["id"], int(card["prize"]["value"]))
    return {"ok": True, "expires_at": new_expiry}


def handle_contact(msg: dict):
    """رقم الهاتف من requestContact في الـ Mini App: يُقبل فقط إن كان رقم المرسل نفسه."""
    contact, sender = msg["contact"], msg.get("from", {}).get("id")
    if not sender or contact.get("user_id") != sender or not contact.get("phone_number"):
        return
    ok = rewards.verify_phone(db, sender, contact["phone_number"])
    tg("sendMessage", chat_id=sender,
       text="✅ تم توثيق رقمك. عد للتطبيق لكشف بطاقتك." if ok else "⚠️ هذا الرقم مستخدم لحساب آخر.")


SYSTEM_DEGRADED_MS = int(os.getenv("SYSTEM_DEGRADED_MS", "1500"))  # زمن استجابة أعلى من هذا = degraded


def _timed_status(t0) -> dict:
    ms = round((time.time() - t0) * 1000)
    return {"status": "degraded" if ms > SYSTEM_DEGRADED_MS else "up", "latency_ms": ms}


def _unit_state(unit: str) -> str:
    """حالة خدمة systemd (active | inactive | failed | activating | unknown). لا تحتاج sudo."""
    try:
        out = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=5)
        return (out.stdout or "").strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


def _monitor_bridge_when_closed(error: str) -> dict:
    """منفذ جسر المراقبة مغلق: قد يكون خاملًا عمدًا (aw-sync يطفئه حين لا حساب مستحق) أو معطّلًا فعلًا."""
    unit = _unit_state(os.getenv("BRIDGE_SERVICE", "mt5-monitor-bridge"))
    sync = _unit_state("aw-sync")
    if unit == "inactive" and sync == "active":
        return {"status": "idle", "note": "خامل: يشغّله aw-sync تلقائيًا عند حلول دور أي حساب"}
    if unit == "activating":
        return {"status": "degraded", "note": "قيد التشغيل الآن"}
    if unit == "inactive" and sync != "active":
        return {"status": "down", "error": f"aw-sync غير فعّال ({sync}): لن يُشغَّل الجسر ولن تُحدَّث الحسابات"}
    if unit == "active":
        return {"status": "down", "error": f"الخدمة تعمل لكن المنفذ لا يستجيب: {error}"}
    return {"status": "down", "error": f"{error} · حالة الخدمة: {unit}"}


@app.get("/api/system/status")
def system_status(admin_id: int = Depends(get_current_admin)):
    """فحص صحة الخدمات الخلفية: Firestore، جسر MT5 (heartbeat)، وتكامل n8n إن وُجد."""
    services = {}

    # Firestore
    t0 = time.time()
    try:
        db.collection("config").document("settings").get()
        services["firestore"] = _timed_status(t0)
    except Exception as e:  # noqa: BLE001
        services["firestore"] = {"status": "down", "error": str(e)[:200]}

    # جسر MT5 عبر Wine (heartbeat على منفذ aw-sync، نفس BRIDGE_PORT الافتراضي 8002)
    bridge_host = os.environ.get("BRIDGE_HOST", "127.0.0.1")
    bridge_port = int(os.environ.get("BRIDGE_PORT", 8002))
    t0 = time.time()
    try:
        with socket.create_connection((bridge_host, bridge_port), timeout=2) as _s:
            services["mt5_bridge"] = _timed_status(t0)
    except OSError as e:
        services["mt5_bridge"] = _monitor_bridge_when_closed(str(e)[:200])

    # ترمنال الروبوت: آخر نبضة من مراقب الـ heartbeat الدائم
    services["mt5_robot"] = heartbeat.snapshot()

    # تكامل n8n: يُفحص فقط إن ضُبط N8N_HEALTH_URL
    n8n_url = os.getenv("N8N_HEALTH_URL", "").strip()
    if not n8n_url:
        services["n8n"] = {"status": "not_configured"}
    else:
        t0 = time.time()
        try:
            res = http.get(n8n_url, timeout=5)
            services["n8n"] = _timed_status(t0) if res.status_code < 500 else {"status": "down", "error": f"HTTP {res.status_code}"}
        except httpx.HTTPError as e:
            services["n8n"] = {"status": "down", "error": str(e)[:200]}

    order = {"up": 0, "idle": 0, "degraded": 1, "not_configured": 2, "unknown": 2, "down": 3}
    overall = max((s["status"] for s in services.values()), key=lambda s: order.get(s, 1))
    return {"overall": overall, "services": services, "checked_at": time.time()}


@app.get("/api/billing/history")
def billing_history(init_data: str):
    """سجل مدفوعات المستخدم (تاريخ، مبلغ، خطة، حالة، معرّف معاملة)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    user = verify_init_data(init_data)
    pkgs = {p["id"]: p for p in billing.list_packages(db)}
    rows = []
    # بلا order_by: الجمع بين where و order_by يتطلب فهرسًا مركّبًا في Firestore (وبدونه يفشل الطلب)
    docs = list(db.collection("payments").where(filter=FieldFilter("uid", "==", user["id"])).stream())
    docs.sort(key=lambda d: (d.to_dict() or {}).get("created_at") or 0, reverse=True)
    for doc in docs:
        p = doc.to_dict() or {}
        pkg = pkgs.get(p.get("package_id"), {})
        if p.get("method") == "stars" or p.get("amount_stars"):
            amount, currency = p.get("amount_stars"), "XTR"
        elif p.get("method") == "ton":
            amount, currency = p.get("amount_ton"), "TON"
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
            "tx_id": (p.get("telegram_payment_charge_id") or p.get("ton_tx_hash") or p.get("np_payment_id")
                      or p.get("invoice_id") or doc.id),
        })
    return {"payments": rows}
