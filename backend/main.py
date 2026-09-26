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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
import base64
import billing
import payments
import digest
import heartbeat
import reminders
import rewards
import leaderboard
import servers
import admin_access
import announcements
import notifications
import support
import analytics as tracking
import cards
import design
import ton
import tonadmin
import growth
import gateway
import secretbox
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

if os.getenv("DB_BACKEND", "").strip().lower() == "sqlite":
    # قاعدة البيانات المحلية (SQLite): بلا حدود يومية. نفس واجهة Firestore فلا يتغير أي منطق.
    import localdb

    firestore = localdb  # noqa: F811 — يوفّر SERVER_TIMESTAMP
    db = localdb.client()
else:
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


_BG = {"err": None, "err_at": 0.0, "count": 0}  # آخر خطأ في المهام الخلفية (لحالة النظام)
_JOBS: dict = {}  # job_id → {"last": ts, "ok": bool}
_APP_STARTED = time.time()


def _safe(fn):
    try:
        fn()
    except Exception as e:  # noqa: BLE001
        log.exception("background task %s", getattr(fn, "__name__", fn))
        _BG.update(err=f"{type(e).__name__}: {str(e)[:160]}", err_at=time.time(), count=_BG["count"] + 1)


def record_system_event(kind: str, detail: dict):
    try:
        db.collection("system_events").document().set({"source": "mt5_heartbeat", "type": kind, "at": time.time(), **detail})
    except Exception:  # noqa: BLE001
        log.exception("system event not recorded")


@asynccontextmanager
async def lifespan(_app):
    threading.Thread(target=_watchdog, daemon=True, name="tg-watchdog").start()
    heartbeat.start(notify_admins, record_system_event)
    threading.Thread(target=lambda: _safe(backfill_servers), daemon=True, name="servers-backfill").start()
    _safe(lambda: tonadmin.load_override(db))
    _safe(lambda: announcements.seed_default(db))
    _safe(lambda: design.write_seo(FRONTEND_INDEX, design.published(db)["seo"], WEBAPP_URL))  # SEO المنشور بعد كل بناء للتطبيق
    from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED

    def _job_event(ev):
        _JOBS[ev.job_id] = {"last": time.time(), "ok": ev.code == EVENT_JOB_EXECUTED, "missed": ev.code == EVENT_JOB_MISSED}
    _scheduler.add_listener(_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
    _scheduler.add_job(lambda: digest.run_digest(db, tg, "weekly"), "cron", day_of_week="mon", hour=9, id="digest_weekly")
    _scheduler.add_job(lambda: digest.run_digest(db, tg, "monthly"), "cron", day=1, hour=9, id="digest_monthly")
    _scheduler.add_job(retry_inbox, "interval", seconds=60, id="webhook_inbox_retry")
    _scheduler.add_job(cleanup_share_media, "cron", hour=4, id="share_media_cleanup")
    _scheduler.add_job(lambda: _safe(lambda: tracking.cleanup(db)), "cron", hour=4, minute=20, id="analytics_cleanup")
    _scheduler.add_job(_leaderboard_tick, "interval", seconds=leaderboard.TICK_SEC, id="leaderboard_tick")
    _scheduler.add_job(lambda: reminders.run_renewal_reminders(db, tg, WEBAPP_URL), "cron", hour=10, id="renewal_reminders")
    _scheduler.add_job(scan_ton_payments, "interval", seconds=60, id="ton_scan")  # يتجاهل الدورة إن لم تُضبط محفظة
    _scheduler.add_job(lambda: _safe(run_growth_automations), "interval", minutes=60, id="growth_automations")
    _scheduler.add_job(lambda: _safe(reconcile_nowpayments), "interval", minutes=5, id="np_reconcile")
    if os.getenv("DB_BACKEND", "").strip().lower() == "sqlite":
        _scheduler.add_job(lambda: _safe(backup_local_db), "cron", hour=3, minute=30, id="db_backup")
    _scheduler.add_job(lambda: _safe(run_gateway_tick), "interval", seconds=30, id="gw_tick", max_instances=1, coalesce=True)
    _scheduler.add_job(lambda: _safe(run_gateway_sweeps), "interval", minutes=3, id="gw_sweeps", max_instances=1, coalesce=True)
    _scheduler.add_job(lambda: _safe(run_gateway_gas_check), "interval", minutes=30, id="gw_gas")
    _scheduler.add_job(lambda: _safe(lambda: support.reassign_stale(db)), "interval", minutes=2, id="support_reassign")
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
    لا يرفع استثناء؛ يرجع {'ok': False} عند الفشل النهائي.
    رسائل المستخدمين (sendMessage) تُرسل مع بطاقة GIF متحركة بتصميم AW إن كانت مفعّلة (انظر cards_send)."""
    if method == "sendMessage":
        res = cards_send(params)
        if res is not None:
            return res
        params.pop("_card", None)
    try:
        return _tg_call(method, params)
    except (httpx.HTTPError, ValueError, RetryableError) as e:
        return {"ok": False, "description": str(e)}


# ───────────────────────── بطاقات GIF لرسائل البوت ─────────────────────────
CARDS_DOC = ("config", "cards")
CARD_FILES = "card_files"  # مفتاح البطاقة → file_id في تلجرام (رفع مرة واحدة لكل تصميم)
_CARDS_CFG = {"v": None, "at": 0.0}
_ANIM_DROP = ("disable_web_page_preview", "link_preview_options", "entities")


def cards_config() -> dict:
    if _CARDS_CFG["v"] is None or time.time() - _CARDS_CFG["at"] > 30:
        snap = db.collection(CARDS_DOC[0]).document(CARDS_DOC[1]).get()
        cfg = {"enabled": True, "kinds": {k: True for k in cards.KINDS}}
        if snap.exists:
            d = snap.to_dict() or {}
            cfg["enabled"] = bool(d.get("enabled", True))
            cfg["kinds"].update({k: bool(v) for k, v in (d.get("kinds") or {}).items() if k in cards.KINDS})
        _CARDS_CFG.update(v=cfg, at=time.time())
    return _CARDS_CFG["v"]


def _card_target(chat_id) -> bool:
    """البطاقات للمستخدمين فقط: لا للأدمن ولا الفريق ولا القنوات/المجموعات ولا حساب تنبيهات الدعم."""
    try:
        cid = int(chat_id)
    except (TypeError, ValueError):
        return False
    if cid <= 0 or cid in ADMIN_IDS or str(cid) in admin_access.staff_members(db):
        return False
    return str(cid) != str(support.get_config(db).get("support_chat_id") or "")


def _tg_upload(method: str, params: dict, field: str, path: str, mime: str) -> dict:
    data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v).lower() if isinstance(v, bool) else str(v)) for k, v in params.items()}
    try:
        with open(path, "rb") as f:
            return raise_for_retryable(http.post(f"{TG_API}/{method}", data=data, files={field: (os.path.basename(path), f, mime)}, timeout=60)).json()
    except (httpx.HTTPError, OSError, ValueError, RetryableError) as e:
        return {"ok": False, "description": str(e)}


def cards_send(params: dict) -> dict | None:
    """يرسل الرسالة كبطاقة متحركة + النص تعليقًا. يرجع None إن لم تنطبق (فتُرسل نصًا عاديًا كما هي)."""
    opt = params.get("_card", None)
    text = str(params.get("text") or "")
    if opt is False or not text or len(text) > 1000 or "token=" in text:
        return None
    try:
        cfg = cards_config()
        if not cfg["enabled"] or not _card_target(params.get("chat_id")):
            return None
        opt = opt if isinstance(opt, dict) else {}
        lang = opt.get("lang") or ("ar" if re.search(r"[\u0600-\u06FF]", text) else "en")
        spec = cards.spec_for(text, lang, opt.get("kind"), opt.get("title"), opt.get("hl"))
        if not cfg["kinds"].get(spec["kind"], True):
            return None
        key = cards.cache_key(spec)
        payload = {k: v for k, v in params.items() if k not in ("text", "_card") + _ANIM_DROP}
        payload["caption"] = text
        if params.get("entities"):
            payload["caption_entities"] = params["entities"]
        ref = db.collection(CARD_FILES).document(key)
        snap = ref.get()
        fid = (snap.to_dict() or {}).get("file_id") if snap.exists else None
        if fid:
            res = _tg_call("sendAnimation", {**payload, "animation": fid})
        else:
            res = _tg_upload("sendAnimation", payload, "animation", cards.get_file(spec), "image/gif")
            anim = ((res.get("result") or {}).get("animation") or (res.get("result") or {}).get("document") or {}) if res.get("ok") else {}
            if anim.get("file_id"):
                ref.set({"file_id": anim["file_id"], "kind": spec["kind"], "lang": spec["lang"], "title": spec["title"], "hl": spec["hl"], "at": time.time()})
        if res.get("ok"):
            return res
        log.warning("card send failed, falling back to text: %s", str(res.get("description"))[:200])
    except Exception:  # noqa: BLE001 — البطاقة إضافة؛ الرسالة النصية تُرسل دائمًا
        log.exception("card send")
    return None


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
    if billing.get_settings(db).get("maintenance"):
        raise HTTPException(503, "maintenance")

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
    notifications.push(db, uid, "account", "تم ربط حسابك بنجاح", "Account linked successfully",
                       f"حساب MT5 {str(body.mt5.login)[-3:].rjust(len(str(body.mt5.login)), '•')} على {body.mt5.server}.",
                       f"MT5 account {str(body.mt5.login)[-3:].rjust(len(str(body.mt5.login)), '•')} on {body.mt5.server}.")
    support.on_account_linked(db, uid, mask_login(body.mt5.login), body.mt5.server)
    try:
        servers.record_success(db, body.mt5.server)  # اسم خادم صحيح 100% لاقتراحات البحث
    except Exception:  # noqa: BLE001
        log.exception("server registry")
    # بطاقات الخدش: الترحيب عند ربط حساب تجريبي، وبطاقة للمُحيل عند نجاح ربط من دعاه (مرة لكل صديق)
    if account_type == "demo":
        rewards.grant_card(db, uid, "welcome")
    else:
        rewards.grant_card(db, uid, "link_real")
    referrer = (previous or {}).get("referred_by")
    if referrer and str(referrer) != str(uid):
        rewards.grant_card(db, referrer, f"referral_{uid}")
        s_ = billing.get_settings(db)
        pct = int(s_.get("referral_friend_discount") or 0)
        if s_.get("referral_enabled") and pct > 0 and not (previous or {}).get("referral_welcome_given"):
            try:  # هدية الصديق المدعو: خصم فوري في محفظة مكافآته
                rewards.admin_issue_coupon(db, uid, "discount", pct, int(s_.get("referral_friend_discount_hours") or 72))
                user_ref(uid).set({"referral_welcome_given": True}, merge=True)
            except rewards.RewardError:
                log.exception("referral friend discount")
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


def _support_public() -> dict:
    """الدعم داخل التطبيق حصريًا (مركز الدعم): لا بوت دعم ولا حسابات تلجرام."""
    cfg = support.get_config(db)
    return {"support_url": "", "support_bot": "", "support_mode": "app", "support_phone": cfg.get("support_phone") or ""}


def _public_settings() -> dict:
    s = billing.get_settings(db)
    return {
        "kill_switch": bool(s.get("kill_switch")),
        "maintenance": bool(s.get("maintenance")),
        "maintenance_ar": s.get("maintenance_ar") or "",
        "maintenance_en": s.get("maintenance_en") or "",
        "referral_enabled": bool(s.get("referral_enabled")),
        "referral_days": s.get("referral_days", 7),
        "referral_mode": s.get("referral_mode", "first"),
        "referral_friend_discount": s.get("referral_friend_discount", 0),
        "referral_share_ar": s.get("referral_share_ar") or "",
        "referral_share_en": s.get("referral_share_en") or "",
        **_support_public(),
        "pay_ton": bool(s.get("pay_ton_enabled", True)),
        "pay_crypto": bool(s.get("pay_crypto_enabled", True)),
        "pay_stars": bool(s.get("pay_stars_enabled", True)),
        "announcement_ar": s.get("announcement_ar") or "",
        "announcement_en": s.get("announcement_en") or "",
        "analytics": bool(tracking.get_config(db).get("enabled")),
        "pixels": tracking.public_pixels(tracking.get_config(db)),
    }


@app.post("/api/status")
def status(body: StatusRequest):
    user = verify_init_data(body.init_data)
    _touch_seen(user["id"])
    return build_status(user)


def _touch_seen(uid):
    """أول/آخر فتح للتطبيق (قمع التحويل + أتمتة الخاملين). كتابة واحدة كل ساعة كحد أقصى."""
    try:
        now = time.time()
        snap = user_ref(uid).get()
        d = (snap.to_dict() or {}) if snap.exists else {}
        if now - float(d.get("last_seen") or 0) >= 3600:
            user_ref(uid).set({"last_seen": now, **({} if d.get("first_seen") else {"first_seen": now})}, merge=True)
    except Exception:  # noqa: BLE001
        log.exception("touch seen")


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
        "photo_url": d.get("photo_url"),
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
    if re.match(r"(csat|human|act|sup):", data):  # أزرار دعم قديمة في البوت: الدعم أصبح داخل التطبيق
        return answer("🎧 الدعم أصبح داخل التطبيق — افتح مركز الدعم من التطبيق.", True)
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
    gift = None
    m = re.fullmatch(r"c_([a-z0-9-]{2,30})", payload or "", re.I)
    if m:  # رابط حملة إعلانية: نقرة + نسب المستخدم للحملة، وهدية الحملة إن وُجدت
        camp = growth.track_start(db, chat_id, m.group(1))
        if camp and camp.get("gift_code"):
            gift = camp["gift_code"]
    m = re.fullmatch(r"gift_([A-Za-z0-9]{6,12})", payload or "")
    if m:
        gift = m.group(1)
    if gift:
        tg("sendMessage", chat_id=chat_id, text=gift_message(chat_id, gift, lang))
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
        payload = text.split(maxsplit=1)[1].strip() if len(text.split()) > 1 else ""
        if payload.lower().startswith("err_") or payload.lower() == "support":  # زر "تواصل مع الدعم" / سماعة الرأس
            return route_to_support(msg)
        return send_welcome(msg, text)
    if first == "/admin":
        return handle_admin_login(msg)
    if first == "/gateway" and msg["from"]["id"] in ADMIN_IDS:
        return tg("sendMessage", chat_id=msg["chat"]["id"], text=gateway_summary())

    sender = msg["from"]["id"]
    state_ref = db.collection("admin_state").document(str(sender))
    snap = state_ref.get() if sender in ADMIN_IDS and text and not text.startswith("/") else None
    if not (snap and snap.exists):
        return route_to_support(msg)
    state = snap.to_dict()
    state_ref.delete()

    outcome = finalize(state["uid"], False, text[:500])
    if outcome == "ok":
        mark_channel_message(state["chat_id"], state["message_id"], f"❌ تم الرفض · {msg['from'].get('first_name', 'Admin')}")
        tg("sendMessage", chat_id=sender, text="✅ أُرسل السبب للمستخدم.")
    else:
        tg("sendMessage", chat_id=sender, text="سبق البتّ في هذا الطلب أو لم يعد موجودًا.")


def route_to_support(msg: dict):
    """أي رسالة نصية للبوت من مستخدم: الدعم أصبح داخل التطبيق — نرسل له زر فتح مركز الدعم مباشرة."""
    lang = "ar" if (msg["from"].get("language_code") or "ar").startswith("ar") else "en"
    text = (msg.get("text") or "").strip()
    m = re.search(r"ERR-[A-Z0-9]{6}", text.upper())
    url = f"{WEBAPP_URL}?view=support" + (f"&err={m.group(0)}" if m else "")
    tg("sendMessage", chat_id=msg["chat"]["id"],
       text="🎧 الدعم الفني أصبح داخل التطبيق: محادثة فورية مع المساعد الذكي وفريق الدعم، مع إرفاق الصور ومتابعة تذكرتك."
       if lang == "ar" else "🎧 Support now lives inside the app: instant chat with our smart assistant and team, screenshots and ticket tracking.",
       reply_markup={"inline_keyboard": [[{"text": "🎧 فتح مركز الدعم" if lang == "ar" else "🎧 Open Support Center", "web_app": {"url": url}}]]}
       if WEBAPP_URL.startswith("https://") else None)
    return None


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
    if not admin_access.role_of(db, ADMIN_IDS, admin_id):  # المالك أو عضو فريق
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
    if not admin_access.role_of(db, ADMIN_IDS, admin_id):
        raise HTTPException(403, "not_admin")
    return admin_id


class AdminVerify(BaseModel):
    token: str
    code: str


@app.post("/api/admin/verify")
def admin_verify(body: AdminVerify, response: Response, request: Request):
    _cleanup_login_tokens()
    entry = _login_tokens.get(body.token)
    if not entry or entry["used"] or entry["expires"] < time.time():
        raise HTTPException(401, "invalid_or_expired")
    if entry["code"] != body.code.strip():
        raise HTTPException(401, "wrong_code")
    entry["used"] = True
    write_audit(entry["admin"], "LOGIN", "LOGIN", 200, dict(request.headers), request.client.host if request.client else None, "")
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
    role = admin_access.role_of(db, ADMIN_IDS, admin_id)
    member = admin_access.staff_members(db).get(str(admin_id)) or {}
    return {"admin_id": admin_id, "role": role, "role_label": admin_access.ROLE_LABEL.get(role),
            "name": member.get("name"), "perms": admin_access.perms_of(db, ADMIN_IDS, admin_id),
            "scope": admin_access.scope_of(db, ADMIN_IDS, admin_id), "agent": admin_access.clean_agent(member.get("agent"))}


# ═══════════════════════════ سجل العمليات + الصلاحيات (كل طلب لمسارات الأدمن) ═══════════════════════════
def write_audit(admin_id, method: str, path: str, status: int, headers: dict, peer: str | None, body_summary: str):
    try:
        ua = headers.get("user-agent", "")
        db.collection("audit_log").document().set({
            "at": time.time(), "admin_id": admin_id, "role": admin_access.role_of(db, ADMIN_IDS, admin_id),
            "method": method, "path": path, "action": admin_access.action_label(method, path), "status": status,
            "ip": admin_access.client_ip(headers, peer), "user_agent": ua[:300], "device": admin_access.parse_device(ua),
            "body": body_summary,
        })
    except Exception:  # noqa: BLE001 — السجل لا يعطّل العملية نفسها
        log.exception("audit log")


def _session_admin(cookie_header: str):
    from http.cookies import SimpleCookie

    try:
        c = SimpleCookie(cookie_header or "")
        token = c["aw_admin"].value if "aw_admin" in c else None
        return int(pyjwt.decode(token, ADMIN_SESSION_SECRET, algorithms=["HS256"]).get("sub")) if token else None
    except Exception:  # noqa: BLE001
        return None


class AdminGuard:
    """ASGI: يمنع أي دور من الوصول لقسم ليس من صلاحياته، ويسجّل كل عملية تعديل (IP + الجهاز + المحتوى)."""

    def __init__(self, app_):
        self.app = app_

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path.startswith("/api/admin") or path == "/api/system/status"):
            return await self.app(scope, receive, send)
        method = scope["method"]
        headers = {k.decode().lower(): v.decode(errors="replace") for k, v in scope.get("headers", [])}
        admin_id = _session_admin(headers.get("cookie", ""))
        if admin_id and path not in admin_access.OPEN_PATHS:
            role = await run_in_threadpool(admin_access.role_of, db, ADMIN_IDS, admin_id)
            perms = await run_in_threadpool(admin_access.perms_of, db, ADMIN_IDS, admin_id) if role else {}
            if role and not admin_access.allowed(perms, admin_access.area_for(path), method):
                body = json.dumps({"detail": "forbidden_role"}).encode()
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
                return await send({"type": "http.response.body", "body": body})
        chunks, status = [], {"code": 0}

        async def recv():
            msg = await receive()
            if msg["type"] == "http.request":
                chunks.append(msg.get("body", b""))
            return msg

        async def snd(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        await self.app(scope, recv, snd)
        if method not in ("GET", "HEAD", "OPTIONS") and path != "/api/admin/verify" and admin_id:
            peer = (scope.get("client") or [None])[0]
            await run_in_threadpool(write_audit, admin_id, method, path, status["code"], headers, peer,
                                    admin_access.summarize_body(b"".join(chunks)))


app.add_middleware(AdminGuard)
app.add_middleware(tracking.ApiTimer)  # زمن استجابة كل مسار API ونسبة أخطائه (لوحة التحليلات ← الأداء)


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
def public_packages(init_data: str = ""):
    uid = None
    if init_data:  # مع الهوية: تظهر أيضًا الباقات الخاصة بهذا المستخدم فقط
        try:
            uid = verify_init_data(init_data)["id"]
        except HTTPException:
            uid = None
    pkgs = billing.list_packages(db, active_only=True, for_uid=uid)
    rate = ton.usd_rate() if ton.configured() else None
    for p in pkgs:  # سعر TON متغيّر حسب السوق (يُحسب من السعر بالدولار)
        p["price_ton"] = ton.usd_to_ton(p["price_usd"], rate) if rate else None
    return {"packages": pkgs, "ton_enabled": bool(rate), "ton_rate": rate}


@app.get("/api/admin/settings")
def admin_get_settings(admin_id: int = Depends(get_current_admin)):
    return billing.get_settings(db)


@app.put("/api/admin/settings")
def admin_update_settings(patch: dict, admin_id: int = Depends(get_current_admin)):
    # تشغيل/إيقاف TON عملية حساسة: تمر فقط عبر /api/admin/ton (رمز OTP)، لا من الإعدادات العامة
    patch = {k: v for k, v in patch.items() if k != "pay_ton_enabled"}
    try:
        if "referral_tiers" in patch:
            patch["referral_tiers"] = growth.clean_tiers(patch["referral_tiers"])
        patch.update(billing.clean_referral(patch))
        if "np_tolerance_pct" in patch:
            patch["np_tolerance_pct"] = max(0.0, min(5.0, float(patch["np_tolerance_pct"])))
        if patch.get("np_payout_address") and not re.fullmatch(r"[A-Za-z0-9:_-]{20,120}", str(patch["np_payout_address"])):
            raise ValueError("invalid payout address")
    except (growth.GrowthError, ValueError, TypeError) as e:
        raise HTTPException(422, getattr(e, "code", str(e)))
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
        if pkg.get("private_uid") and pkg.get("one_time", True):  # باقة خاصة لمرة واحدة: تختفي بعد استخدامها
            db.collection("packages").document(pkg["id"]).set({"used": True, "used_at": time.time(), "used_order": order_id}, merge=True)
        if pay.get("bonus_days"):  # جائزة خدش "أيام مجانية" طُبّقت على هذا الطلب
            billing._add_days(db, pay["uid"], int(pay["bonus_days"]))
        if pay.get("reward_id"):  # الجائزة تُعلَّم مستخدمة بعد نجاح الدفع فقط
            rewards.mark_used(db, pay["reward_id"], order_id)
        settings = billing.get_settings(db)
        if settings.get("referral_enabled"):
            _referral_reward(pay, pkg, settings)
        _payment_cards(pay, order_id)
        pay_ref.set({"status": "finished", "confirmed_at": time.time(), **(extra or {})}, merge=True)
    tg("sendMessage", chat_id=pay["uid"], text=PAID_MSG)
    notifications.push(db, pay["uid"], "payment", "تم تفعيل اشتراكك ✅", "Your subscription is active ✅",
                       f"تم تأكيد الدفع وتفعيل باقة {pkg.get('name_ar') or ''}.", f"Payment confirmed — {pkg.get('name_en') or ''} plan activated.", order_id)
    return True


def _referral_reward(pay: dict, pkg: dict, settings: dict):
    """مكافأة الإحالة (الوضع، أقل مبلغ، الحد الشهري، المستويات) + جائزة الإنجاز للمُحيل وإشعاره. لا تعطّل الدفع أبدًا."""
    try:
        usd = _pay_usd(pay) or float(pkg.get("price_usd") or 0)
        res = billing.referral_on_payment(db, pay["uid"], settings, usd)
        if not res:
            return
        rid = res["referrer"]
        if res["days"]:
            notifications.push(db, rid, "referral", f"🎉 +{res['days']} يوم من إحالة صديق", f"🎉 +{res['days']} days from a referral",
                               "صديقك دفع اشتراكه وأُضيفت أيامك تلقائيًا.", "Your friend subscribed and your days were added automatically.")
        m = res.get("milestone")
        if m:
            rewards.admin_issue_coupon(db, rid, m["type"], m["value"], m["hours"])
            notifications.push(db, rid, "referral", f"🏆 وصلت {m['count']} إحالة ناجحة!", f"🏆 {m['count']} successful referrals!",
                               "جائزة الإنجاز أُضيفت لمحفظة المكافآت.", "Your milestone prize is in your rewards wallet.")
            tg("sendMessage", chat_id=rid, text=f"🏆 مبروك! وصلت {m['count']} إحالة ناجحة — جائزتك في محفظة المكافآت داخل التطبيق.")
    except Exception:  # noqa: BLE001
        log.exception("referral reward")


def _payment_cards(pay: dict, order_id: str):
    """بطاقات خدش: أول دفعة ناجحة، ثم بطاقة لكل تجديد (كل منها قابل للإيقاف من اللوحة)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    try:
        prev = [d for d in db.collection("payments").where(filter=FieldFilter("uid", "==", pay["uid"])).stream()
                if d.id != order_id and (d.to_dict() or {}).get("status") == "finished"]
        rewards.grant_card(db, pay["uid"], "first_payment" if not prev else f"renewal_{order_id}")
    except Exception:  # noqa: BLE001
        log.exception("payment card")


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


def require_method(key: str):
    """طرق الدفع قابلة للإيقاف من مركز التحكم في لوحة الأدمن، وكلها تتوقف في وضع الصيانة."""
    s_ = billing.get_settings(db)
    if s_.get("maintenance"):
        raise HTTPException(503, "maintenance")
    if not s_.get(key, True):
        raise HTTPException(403, "payment_method_disabled")


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
    require_method("pay_crypto_enabled")
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True, for_uid=user["id"])}
    pkg = pkgs.get(body.package_id)
    if not pkg:
        raise HTTPException(404, "package_not_found")
    card = checkout_reward(user["id"], body.reward_id)
    amount_usd = pkg["price_usd"]
    if card:
        amount_usd = rewards.apply_to_amount(card, amount_usd)[0]
    amount_usd = max(1, int(round(amount_usd)))  # قيمة ثابتة بالدولار بلا كسور (12$ لا 12.000850$)

    order_id = f"{user['id']}-{body.package_id}-{int(time.time())}"
    gw_cfg = gateway.get_config(db)
    if gateway.active(gw_cfg):
        order_id += f"-{secrets.token_hex(3)}"  # فريد حتى لو أنشأ المستخدم فاتورتين في الثانية نفسها
        if not body.pay_currency:
            raise HTTPException(400, "pay_currency_required")
        try:
            return gateway.create_invoice(db, user["id"], body.pay_currency, amount_usd, order_id,
                                          {"package_id": body.package_id, **reward_fields(card, body.reward_id, pkg["price_usd"])})
        except gateway.GatewayError as e:
            raise HTTPException(e.status, e.code)
        except gateway.ch.ChainError:
            raise HTTPException(502, "payment_provider_error")
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
    s_ = billing.get_settings(db)
    try:
        pay = payments.create_direct_payment(
            order_id=order_id,
            amount_usd=amount_usd,
            pay_currency=body.pay_currency,
            description=f"AW Robot - {pkg.get('name_en') or pkg.get('name_ar')}",
            ipn_url=f"{base}/api/payments/nowpayments-webhook",
            payout_address=(s_.get("np_payout_address") or "").strip(),
            payout_currency=(s_.get("np_payout_currency") or "").strip().lower(),
        )
    except payments.PaymentError as e:
        code = str(e)
        raise HTTPException(400 if code in ("unsupported_currency", "amount_too_low") else 502,
                            code if code in ("unsupported_currency", "amount_too_low") else "payment_provider_error")
    info = {
        "payment_id": pay.get("payment_id"),
        "pay_address": pay.get("pay_address"),
        "pay_amount": pay.get("pay_amount"),
        "display_amount": payments.display_amount(pay.get("pay_currency") or body.pay_currency, pay.get("pay_amount"),
                                                  float(s_.get("np_tolerance_pct") or 1.0)),
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
    cfg = gateway.get_config(db)
    if gateway.active(cfg):  # بوابتنا الخاصة (AW Pay) بدل NOWPayments
        return {"currencies": gateway.currencies(cfg), "provider": "aw"}
    return {"currencies": payments.currencies(), "provider": "nowpayments"}


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
    if pay.get("method") == "gateway":  # تحقق مباشر من الشبكة (بحد أدنى 8ث بين الطلبات)
        if status in gateway.OPEN and time.time() - float(pay.get("checked_at") or 0) >= 8:
            try:
                return gateway.check_invoice(db, body.order_id, gw_hooks())
            except Exception:  # noqa: BLE001 — الشبكة بطيئة: نعيد آخر حالة معروفة
                log.exception("gateway check")
        return gateway.public_invoice(body.order_id, pay)
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
    if pay_status == "partially_paid" and _within_tolerance(data, pay_snap.to_dict()):
        pay_status = "finished"  # الفرق ضمن هامش القبول (تقريب المبلغ المعروض/فروقات الشبكة)
        data = {**data, "accepted_partial": True}
    if pay_status == "finished":
        activate_payment(order_id, {"np_payment_id": data.get("payment_id"), "actually_paid": data.get("actually_paid"),
                                    **({"accepted_partial": True} if data.get("accepted_partial") else {})})
    else:
        pay_ref.set({"status": pay_status}, merge=True)


def _within_tolerance(data: dict, pay: dict) -> bool:
    try:
        need = float(data.get("pay_amount") or (pay.get("np_pay") or {}).get("pay_amount") or 0)
        got = float(data.get("actually_paid") or 0)
    except (TypeError, ValueError):
        return False
    tol = float(billing.get_settings(db).get("np_tolerance_pct") or 1.0)
    return need > 0 and got >= need * (1 - tol / 100)


def reconcile_nowpayments():
    """مهمة دورية (كل 5 دقائق): يسأل NOWPayments مباشرة عن كل دفعة منتظرة خلال 48 ساعة — لا تضيع دفعة
    حتى لو فُقد إشعار الـ webhook."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time()
    for d in db.collection("payments").where(filter=FieldFilter("method", "==", "nowpayments")).stream():
        p = d.to_dict() or {}
        if p.get("status") in ("finished", "failed", "expired", "refunded") or not p.get("np_payment_id"):
            continue
        if now - float(p.get("created_at") or 0) > 48 * 3600:
            continue
        try:
            remote = payments.get_payment(p["np_payment_id"])
        except payments.PaymentError:
            continue
        st = remote.get("payment_status")
        if st and (st != p.get("status") or st == "partially_paid"):
            process_nowpayments({"order_id": d.id, "payment_status": st, "payment_id": p["np_payment_id"],
                                 "actually_paid": remote.get("actually_paid"), "pay_amount": remote.get("pay_amount")})


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
    require_method("pay_ton_enabled")
    if not ton.configured():
        raise HTTPException(503, "ton_not_configured")
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True, for_uid=user["id"])}
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
    require_method("pay_stars_enabled")
    pkgs = {p["id"]: p for p in billing.list_packages(db, active_only=True, for_uid=user["id"])}
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
    res = do_unlink(user["id"])
    if not res["ok"]:
        raise HTTPException(res["status"], res["reason"])
    return {"ok": True}


def mask_login(login) -> str:
    s_ = str(login or "")
    return ("•" * max(0, len(s_) - 3)) + s_[-3:]


def do_unlink(uid) -> dict:
    """فكّ ربط حساب MT5 (من التطبيق أو من شات الدعم بعد تأكيد المستخدم). نفس القواعد في الحالتين."""
    ref = user_ref(uid)
    snap = ref.get()
    if not snap.exists:
        return {"ok": False, "status": 404, "reason": "not_found"}
    d = snap.to_dict()
    if d.get("status") != "approved":
        return {"ok": False, "status": 400, "reason": "not_linked"}

    last = d.get("last_unlink_at") or 0
    now_ts = time.time()
    if now_ts - last < UNLINK_COOLDOWN_SEC:
        remaining_h = int((UNLINK_COOLDOWN_SEC - (now_ts - last)) / 3600) + 1
        return {"ok": False, "status": 429, "reason": f"cooldown_{remaining_h}h"}

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
       text=f"🔓 فكّ ربط: <code>{uid}</code> · {escape(str(old_login))} · {escape(str(old_server))}")
    notifications.push(db, uid, "security", "تنبيه أمني: فُكّ ربط حسابك", "Security alert: account unlinked",
                       "تم فكّ ربط حساب MT5 من التطبيق. إن لم تكن أنت، تواصل مع الدعم فورًا.",
                       "Your MT5 account was unlinked in the app. If this wasn't you, contact support immediately.")
    return {"ok": True, "login_masked": mask_login(old_login), "server": old_server}


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


# ═══════════════════════════ الصورة الشخصية ═══════════════════════════
AVATAR_DIR = os.getenv("AVATAR_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "avatars")
AVATAR_MAX_BYTES = 400_000
_AVATAR_NAME = re.compile(r"^[A-Za-z0-9_-]{4,64}\.(jpg|png|webp)$")
_MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


def _image_ext(raw: bytes) -> str | None:
    if raw.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def save_avatar(prefix: str, b64: str, max_bytes: int = AVATAR_MAX_BYTES) -> str:
    """يحفظ صورة JPEG/PNG/WebP (base64) ويعيد رابطها العام. النوع يُتحقق منه من محتوى الملف لا من اسمه."""
    try:
        raw = base64.b64decode(b64.split(",")[-1], validate=True)
    except (ValueError, TypeError):
        raise HTTPException(422, "bad_image")
    ext = _image_ext(raw)
    if len(raw) > max_bytes or not ext:
        raise HTTPException(422, "bad_image")
    os.makedirs(AVATAR_DIR, exist_ok=True)
    name = f"{prefix}_{secrets.token_urlsafe(6)}.{ext}"
    with open(os.path.join(AVATAR_DIR, name), "wb") as f:
        f.write(raw)
    return f"{WEBAPP_URL}/api/media/avatars/{name}"


def delete_avatar(url: str | None):
    name = (url or "").rsplit("/", 1)[-1]
    if _AVATAR_NAME.match(name):
        try:
            os.remove(os.path.join(AVATAR_DIR, name))
        except OSError:
            pass


class PhotoUpdate(BaseModel):
    init_data: str
    photo: str = ""  # JPEG base64؛ فارغ = حذف الصورة والعودة للصورة الافتراضية


@app.post("/api/profile/photo")
def update_photo(body: PhotoUpdate):
    user = verify_init_data(body.init_data)
    ref = user_ref(user["id"])
    snap = ref.get()
    if not snap.exists:
        raise HTTPException(404, "not_found")
    old = (snap.to_dict() or {}).get("photo_url")
    url = save_avatar(f"u{user['id']}", body.photo) if body.photo else None
    ref.set({"photo_url": url}, merge=True)
    delete_avatar(old)
    return {"ok": True, "photo_url": url}


@app.get("/api/media/avatars/{name}")
def avatar_file(name: str):
    path = os.path.join(AVATAR_DIR, name)
    if not _AVATAR_NAME.match(name) or not os.path.exists(path):
        raise HTTPException(404, "not_found")
    return FileResponse(path, media_type=_MEDIA_TYPES[name.rsplit(".", 1)[-1]], headers={"Cache-Control": "public, max-age=2592000"})


class FeedbackRequest(BaseModel):
    init_data: str
    rating: int = Field(ge=1, le=5)
    message: str = Field(default="", max_length=1000)
    lang: str = Field(default="", pattern="^(ar|en|)$")


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
    data = (snap.to_dict() or {}) if snap.exists else {}
    lang = body.lang or data.get("language") or ("ar" if (user.get("language_code") or "").startswith("ar") else "en")
    now = time.time()
    if now - float(data.get("feedback_at") or 0) < 20:  # منع الإغراق: تقييم واحد كل 20 ثانية
        raise HTTPException(429, "too_many")
    res = support.feedback_reply(support.get_config(db), lang, body.rating, body.message.strip(), nickname or user.get("first_name", ""))
    db.collection("feedback").document().set({"uid": str(user["id"]), "rating": body.rating, "message": body.message.strip(), "lang": lang,
                                               "reply": res["reply"], "ai": res["ai"], "suggest_support": res["suggest_support"], "at": now})
    ref.set({"feedback_at": now, "feedback_rating": body.rating}, merge=True)
    tg("sendMessage", chat_id=CHANNEL_ID, parse_mode="HTML", text=text + f"\n\n🤖 الرد: {escape(res['reply'][:600])}", disable_notification=True, _card=False)
    return {"ok": True, "reply": res["reply"], "suggest_support": res["suggest_support"]}


@app.get("/api/admin/support/feedback")
def admin_feedback(admin_id: int = Depends(get_current_admin)):
    rows = [{"id": d.id, **(d.to_dict() or {})} for d in db.collection("feedback").stream()]
    rows.sort(key=lambda r: -(r.get("at") or 0))
    n = len(rows)
    dist = {str(i): sum(1 for r in rows if r.get("rating") == i) for i in range(1, 6)}
    return {"rows": rows[:300], "stats": {"count": n, "avg": round(sum(r.get("rating") or 0 for r in rows) / n, 2) if n else None, "dist": dist}}


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


# ═══════════════════════════ فريق العمل وسجل العمليات ═══════════════════════════
@app.get("/api/admin/staff")
def admin_staff(admin_id: int = Depends(get_current_admin)):
    members = admin_access.staff_members(db)
    owners = [{"id": str(i), "role": "owner", "name": None, "fixed": True, "perms": admin_access.PERMS["owner"]} for i in sorted(ADMIN_IDS)]
    rows = [{"id": k, **v, "fixed": False, "custom_perms": isinstance(v.get("perms"), dict),
             "perms": admin_access.perms_of(db, ADMIN_IDS, k), "scope": admin_access.clean_scope(v.get("scope")),
             "agent": admin_access.clean_agent(v.get("agent"))} for k, v in members.items()]
    rows.sort(key=lambda r: (r["agent"]["order"], r.get("added_at") or 0))
    return {"members": owners + rows, "roles": {r: admin_access.ROLE_LABEL[r] for r in admin_access.ROLES[1:]},
            "perms": admin_access.PERMS, "areas": admin_access.AREA_LABEL, "skills": admin_access.SKILLS,
            "can_edit": admin_access.role_of(db, ADMIN_IDS, admin_id) == "owner"}


class StaffMember(BaseModel):
    id: str = Field(pattern=r"^\d{3,15}$")
    role: str = Field(pattern="^(manager|support|viewer)$")
    name: str = Field(default="", max_length=40)
    perms: dict | None = None     # None = صلاحيات الدور الافتراضية
    scope: dict | None = None
    agent: dict | None = None


def _owner_only(admin_id: int):
    # حتى لو مُنح عضو صلاحية «الفريق» فهي عرض فقط: الإضافة والتعديل والحذف للمالك وحده (لا تصعيد ذاتي للصلاحيات)
    if admin_access.role_of(db, ADMIN_IDS, admin_id) != "owner":
        raise HTTPException(403, "owner_only")


@app.put("/api/admin/staff")
def admin_staff_put(body: StaffMember, admin_id: int = Depends(get_current_admin)):
    _owner_only(admin_id)
    if int(body.id) in ADMIN_IDS:
        raise HTTPException(400, "owner_is_fixed")
    prev = admin_access.staff_members(db).get(body.id) or {}
    fields = body.model_fields_set
    row = {"role": body.role, "name": body.name.strip(), "added_at": prev.get("added_at") or time.time(),
           "added_by": prev.get("added_by") or admin_id, "updated_at": time.time(),
           "perms": admin_access.clean_perms(body.perms) if "perms" in fields else prev.get("perms"),
           "scope": admin_access.clean_scope(body.scope if "scope" in fields else prev.get("scope")),
           "agent": admin_access.clean_agent(body.agent if "agent" in fields else prev.get("agent"))}
    ref = db.collection("config").document("staff")
    snap = ref.get()
    members = dict(((snap.to_dict() or {}).get("members") or {}) if snap.exists else {})
    members[body.id] = row
    ref.set({"members": members})
    admin_access.invalidate()
    return {"ok": True}


@app.delete("/api/admin/staff/{member_id}")
def admin_staff_delete(member_id: str, admin_id: int = Depends(get_current_admin)):
    _owner_only(admin_id)
    ref = db.collection("config").document("staff")
    snap = ref.get()
    members = dict(((snap.to_dict() or {}).get("members") or {}) if snap.exists else {})
    members.pop(member_id, None)
    ref.set({"members": members})
    admin_access.invalidate()
    support.unassign_agent(db, member_id)  # تذاكره المفتوحة تعود للتوزيع على بقية الفريق
    return {"ok": True}


@app.get("/api/admin/audit")
def admin_audit(limit: int = 200, admin: str | None = None, admin_id: int = Depends(get_current_admin)):
    q = db.collection("audit_log").order_by("at", direction="DESCENDING").limit(max(1, min(limit, 1000)))
    rows = []
    for d in q.stream():
        x = d.to_dict() or {}
        if admin and str(x.get("admin_id")) != admin:
            continue
        rows.append({"id": d.id, **x})
    return {"rows": rows}


# ═══════════════════════════ لوحة الرئيس التنفيذي (CEO) ═══════════════════════════
def _pay_usd(p: dict) -> float:
    if p.get("amount_usd") is not None and p.get("method") != "stars":
        return float(p["amount_usd"])
    if p.get("method") == "ton" and p.get("amount_ton") and p.get("ton_rate_usd"):
        return float(p["amount_ton"]) * float(p["ton_rate_usd"])
    return 0.0


@app.get("/api/admin/ceo")
def admin_ceo(admin_id: int = Depends(get_current_admin)):
    """أرقام الأعمال بلغة بسيطة: المستخدمون، الاشتراكات، الإيرادات، التحويل، الإحالة، ومنحنى 30 يومًا."""
    now = time.time()
    day = lambda ts: time.strftime("%Y-%m-%d", time.gmtime(ts))  # noqa: E731
    days = [day(now - i * 86400) for i in range(29, -1, -1)]
    signups = {d: 0 for d in days}
    revenue = {d: 0.0 for d in days}

    users = total = linked = active = expired = trial = referred = new7 = new30 = 0
    for d in db.collection("users").stream():
        u = d.to_dict() or {}
        total += 1
        created = _epoch(u.get("created_at")) or 0
        if created:
            new7 += created > now - 7 * 86400
            new30 += created > now - 30 * 86400
            if day(created) in signups:
                signups[day(created)] += 1
        linked += u.get("status") == "approved"
        exp = float((u.get("subscription") or {}).get("expires_at") or 0)
        active += exp > now
        expired += 0 < exp <= now
        trial += float(u.get("trial_expires_at") or 0) > now
        referred += bool(u.get("referred_by"))

    paid_users, by_method, by_package = set(), {}, {}
    rev_total = rev30 = rev7 = 0.0
    stars_total = orders = 0
    pkgs = {p["id"]: p for p in billing.list_packages(db)}
    for d in db.collection("payments").stream():
        p = d.to_dict() or {}
        if p.get("status") != "finished":
            continue
        orders += 1
        paid_users.add(str(p.get("uid")))
        at = float(p.get("confirmed_at") or p.get("created_at") or 0)
        usd_v = _pay_usd(p)
        method = p.get("method") or "nowpayments"
        by_method[method] = by_method.get(method, 0) + 1
        name = (pkgs.get(p.get("package_id")) or {}).get("name_en") or p.get("package_id")
        by_package[name] = by_package.get(name, 0) + 1
        stars_total += int(p.get("amount_stars") or 0)
        rev_total += usd_v
        rev30 += usd_v if at > now - 30 * 86400 else 0
        rev7 += usd_v if at > now - 7 * 86400 else 0
        if day(at) in revenue:
            revenue[day(at)] += usd_v

    r2 = lambda v: round(v, 2)  # noqa: E731
    return {
        "users": {"total": total, "linked": linked, "new_7d": new7, "new_30d": new30, "referred": referred},
        "subscriptions": {"active": active, "expired": expired, "trial": trial,
                          "paying_users": len(paid_users),
                          "conversion_pct": r2(len(paid_users) / linked * 100) if linked else None},
        "revenue": {"total_usd": r2(rev_total), "last_30d_usd": r2(rev30), "last_7d_usd": r2(rev7), "orders": orders,
                    "stars_total": stars_total, "arpu_usd": r2(rev_total / len(paid_users)) if paid_users else None},
        "by_method": by_method,
        "by_package": dict(sorted(by_package.items(), key=lambda x: -x[1])),
        "series": [{"d": d, "signups": signups[d], "revenue": r2(revenue[d])} for d in days],
        "support": support_stats(),
        "funnel": growth.funnel(db),
        "generated_at": now,
    }


# ═══════════════════════════ اقتراح خوادم MT5 ═══════════════════════════
@app.get("/api/servers")
def server_suggestions(q: str = ""):
    return {"servers": servers.search(db, q[:64])}


def backfill_servers() -> int:
    """يسجّل خوادم الحسابات المربوطة حاليًا (أسماء قبلها MT5 فعلًا)."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    n = 0
    for d in db.collection("users").where(filter=FieldFilter("status", "==", "approved")).stream():
        name = (d.to_dict() or {}).get("mt5_server")
        if name and servers.upsert(db, name, verified=True, source="linked"):
            n += 1
    return n


@app.get("/api/admin/servers")
def admin_servers(admin_id: int = Depends(get_current_admin)):
    rows = sorted(servers.all_rows(db), key=lambda r: (not r["verified"], (r["name"] or "").lower()))
    return {"servers": rows, "total": len(rows)}


class ServerImport(BaseModel):
    text: str = Field(max_length=500_000)


@app.post("/api/admin/servers/import")
def admin_servers_import(body: ServerImport, admin_id: int = Depends(get_current_admin)):
    try:
        rows = servers.parse_import(body.text)
    except ValueError:
        raise HTTPException(422, "bad_file")
    added = sum(1 for name, typ in rows if servers.upsert(db, name, stype=typ, source="import"))
    return {"imported": added}


@app.post("/api/admin/servers/backfill")
def admin_servers_backfill(admin_id: int = Depends(get_current_admin)):
    return {"imported": backfill_servers()}


@app.delete("/api/admin/servers/{sid}")
def admin_servers_delete(sid: str, admin_id: int = Depends(get_current_admin)):
    db.collection(servers.COLLECTION).document(sid).delete()
    servers._CACHE["rows"] = None
    return {"ok": True}


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
    import lbscript

    sim = db.collection(leaderboard.SIM_DOC[0]).document(leaderboard.SIM_DOC[1]).get()
    return {**leaderboard.get_config(db), "default_profiles": leaderboard.default_config()["profiles"],
            "script_error": ((sim.to_dict() or {}).get("script_error") if sim.exists else None),
            "script_presets": lbscript.PRESETS, "script_vars": lbscript.VAR_HELP, "script_funcs": lbscript.FUNC_HELP}


class ScriptPreview(BaseModel):
    script: str = Field(min_length=1, max_length=1500)
    interval_sec: int = Field(default=1200, ge=60, le=86400)


@app.post("/api/admin/leaderboard/script/preview")
def admin_leaderboard_script_preview(body: ScriptPreview, admin_id: int = Depends(get_current_admin)):
    """معاينة المعادلة على أسبوع كامل قبل حفظها (أول 8 أسماء)."""
    import lbscript

    cfg = leaderboard.get_config(db)
    try:
        tree = lbscript.compile_script(body.script)
        bases = leaderboard.bases(cfg)[:8]
        bots = [{"name": p["name"], "base": b, "elite": i < cfg["elite_count"]} for i, (p, b) in enumerate(zip(cfg["profiles"], bases))]
        series = lbscript.simulate(tree, bots, body.interval_sec)
    except lbscript.ScriptError as e:
        raise HTTPException(422, str(e))
    return {"names": [b["name"] for b in bots], "series": series}


class AdminPhoto(BaseModel):
    photo: str


@app.post("/api/admin/leaderboard/photo")
def admin_leaderboard_photo(body: AdminPhoto, admin_id: int = Depends(get_current_admin)):
    """رفع صورة بروفايل لمنافس في الترتيب؛ يعيد رابطها لاستخدامه في القائمة."""
    return {"url": save_avatar("lb", body.photo, 1_500_000)}


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
    user_ref(sender).set({"phone_prefix": re.sub(r"\D", "", contact["phone_number"])[:4]}, merge=True)  # فلتر الدولة في الإشعارات
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
        if hasattr(db, "health"):  # SQLite: الحجم ووضع WAL وحجم ملفه
            services["firestore"]["db"] = db.health()
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

    services.update(_extended_status())
    order = {"up": 0, "idle": 0, "degraded": 1, "not_configured": 2, "unknown": 2, "down": 3}
    overall = max((s["status"] for s in services.values()), key=lambda s: order.get(s, 1))
    return {"overall": overall, "services": services, "checked_at": time.time()}


_STATUS_CACHE: dict = {}


def _cached(key: str, ttl: float, fn):
    hit = _STATUS_CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception as e:  # noqa: BLE001 — فحص واحد لا يعطّل صفحة الحالة
        val = {"status": "down", "error": f"{type(e).__name__}: {str(e)[:160]}"}
    _STATUS_CACHE[key] = (time.time(), val)
    return val


def _st_api():
    import resource
    import sys as _sys

    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return {"status": "up", "details": {"uptime_min": round((time.time() - _APP_STARTED) / 60), "python": _sys.version.split()[0],
                                        "memory_mb": round(rss), "threads": threading.active_count(), "pid": os.getpid()},
            "note": f"آخر خطأ في مهمة خلفية: {_BG['err']}" if _BG["err"] and time.time() - _BG["err_at"] < 3600 else ""}


def _st_telegram():
    t0 = time.time()
    info = (tg("getWebhookInfo") or {}).get("result") or {}
    lat = round((time.time() - t0) * 1000)
    pending = int(info.get("pending_update_count") or 0)
    err_at = int(info.get("last_error_date") or 0)
    recent_err = err_at and time.time() - err_at < 900
    status = "down" if not info else "degraded" if (recent_err or pending > 50) else "up"
    return {"status": status, "latency_ms": lat, "details": {"webhook": bool(info.get("url")), "pending_updates": pending,
            "max_connections": info.get("max_connections"), "ip": info.get("ip_address")},
            "error": (info.get("last_error_message") or "")[:160] if recent_err else ""}


def _st_scheduler():
    jobs = []
    now = time.time()
    for j in _scheduler.get_jobs():
        st = _JOBS.get(j.id) or {}
        jobs.append({"id": j.id, "next": j.next_run_time.timestamp() if j.next_run_time else None, "last": st.get("last"),
                     "ok": st.get("ok", True), "missed": st.get("missed", False)})
    bad = [j for j in jobs if not j["ok"] or j["missed"]]
    return {"status": "down" if not _scheduler.running else "degraded" if bad else "up",
            "details": {"running": _scheduler.running, "jobs": len(jobs), "failing": len(bad)}, "jobs": jobs[:40],
            "note": ", ".join(j["id"] for j in bad)[:200]}


def _st_sync():
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time()
    total = err = stale = 0
    newest = 0.0
    for d in db.collection("users").where(filter=FieldFilter("status", "==", "approved")).stream():
        u = d.to_dict() or {}
        total += 1
        sy = u.get("sync") or {}
        if sy.get("state") == "error":
            err += 1
        last = float(sy.get("last_ok") or 0)
        newest = max(newest, last)
        if last and now - last > 3 * 3600:
            stale += 1
    status = "idle" if not total else "down" if newest and now - newest > 6 * 3600 else "degraded" if total and (err + stale) / total > 0.2 else "up"
    return {"status": status, "details": {"linked_accounts": total, "sync_errors": err, "stale_3h": stale,
                                          "last_sync_min": round((now - newest) / 60) if newest else None}, "unit": _unit_state("aw-sync")}


def _st_gateway():
    cfg = gateway.get_config(db)
    if not gateway.active(cfg):
        return {"status": "not_configured", "note": "بوابة AW Pay غير مفعّلة"}
    last = (_JOBS.get("gw_tick_run") or {}).get("last") or (_JOBS.get("gw_tick") or {}).get("last")
    from google.cloud.firestore_v1.base_query import FieldFilter

    waiting = sum(1 for d in db.collection("payments").where(filter=FieldFilter("status", "==", "waiting")).stream()
                  if (d.to_dict() or {}).get("method") == "gateway")
    nets = [n for n in gateway.NETWORKS if gateway.network_ready(cfg, n)]
    status = "degraded" if last and time.time() - last > 180 else "up"
    return {"status": status, "details": {"networks": nets, "waiting_invoices": waiting, "last_scan_sec": round(time.time() - last) if last else None}}


def _st_nowpayments():
    if not payments.NP_API_KEY:
        return {"status": "not_configured"}
    t0 = time.time()
    r = http.get("https://api.nowpayments.io/v1/status", timeout=6)
    lat = round((time.time() - t0) * 1000)
    ok = r.status_code == 200 and (r.json() or {}).get("message") == "OK"
    last = (_JOBS.get("np_reconcile") or {})
    return {"status": "up" if ok else "down", "latency_ms": lat, "details": {"reconcile_ok": last.get("ok", True),
            "last_reconcile_min": round((time.time() - last["last"]) / 60) if last.get("last") else None}}


def _st_ai():
    cfg = support.get_config(db)
    if not support.ai_available(cfg):
        return {"status": "not_configured", "note": "أضف مفتاح Gemini من الدعم الفني ← الإعدادات"}
    stt = support.AI_STATE
    recent_err = stt.get("err_at", 0) > stt.get("ok_at", 0) and time.time() - stt.get("err_at", 0) < 1800
    return {"status": "degraded" if recent_err else "up",
            "details": {"model": cfg.get("model"), "fallbacks": cfg.get("fallback_models"), "last_ok_min": round((time.time() - stt["ok_at"]) / 60) if stt.get("ok_at") else None,
                        "calls": stt.get("calls", 0), "failures": stt.get("fails", 0)},
            "error": stt.get("err", "")[:160] if recent_err else ""}


def _st_storage():
    import shutil

    base = os.path.dirname(getattr(db, "path", "") or os.path.abspath(__file__))
    du = shutil.disk_usage(base)
    free_pct = du.free / du.total * 100
    bdir = os.path.join(base, "backups")
    newest = max((os.path.getmtime(os.path.join(bdir, f)) for f in os.listdir(bdir) if f.endswith(".db")), default=0) if os.path.isdir(bdir) else 0
    backup_h = round((time.time() - newest) / 3600, 1) if newest else None
    status = "down" if free_pct < 5 else "degraded" if free_pct < 15 or (hasattr(db, "health") and (backup_h is None or backup_h > 30)) else "up"
    return {"status": status, "details": {"disk_free_gb": round(du.free / 1e9, 1), "disk_free_pct": round(free_pct, 1), "last_backup_h": backup_h}}


def _st_errors():
    from google.cloud.firestore_v1.base_query import FieldFilter

    since = time.time() - 3600
    rows = [d.to_dict() or {} for d in db.collection("client_errors").where(filter=FieldFilter("at", ">=", since)).stream()]
    crit = sum(1 for r in rows if r.get("priority") == "critical")
    return {"status": "down" if crit >= 10 else "degraded" if crit or len(rows) > 50 else "up",
            "details": {"errors_1h": len(rows), "critical_1h": crit, "network_1h": sum(1 for r in rows if r.get("kind") == "network")}}


def _st_analytics():
    s = tracking.summary(db, 1)
    return {"status": "up", "details": {"live_users": s["live"]["users"], "dau": s["active"]["dau"], "sessions_today": s["totals"]["sessions"]}}


def _extended_status() -> dict:
    return {
        "api": _st_api(),
        "telegram": _cached("telegram", 30, _st_telegram),
        "scheduler": _st_scheduler(),
        "sync": _cached("sync", 60, _st_sync),
        "gateway": _cached("gateway", 30, _st_gateway),
        "nowpayments": _cached("nowpayments", 120, _st_nowpayments),
        "ai": _st_ai(),
        "storage": _cached("storage", 120, _st_storage),
        "errors": _cached("errors", 30, _st_errors),
        "analytics": _cached("analytics", 60, _st_analytics),
    }


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


# ═══════════════════════════ الإشعارات (🔔) ═══════════════════════════
@app.get("/api/notifications")
def my_notifications(init_data: str):
    user = verify_init_data(init_data)
    snap = user_ref(user["id"]).get()
    return notifications.list_for(db, user["id"], snap.to_dict() if snap.exists else {})


@app.post("/api/notifications/read")
def my_notifications_read(body: InitOnly):
    user = verify_init_data(body.init_data)
    notifications.mark_read(db, user["id"])
    return {"ok": True}


class BroadcastTarget(BaseModel):
    target: str = Field(pattern="^(user|filter|all)$")
    uid: str | None = Field(default=None, pattern=r"^\d{1,15}$")
    filter: dict = Field(default_factory=dict)


class BroadcastBody(BroadcastTarget):
    title_ar: str = Field(default="", max_length=120)
    title_en: str = Field(default="", max_length=120)
    body_ar: str = Field(default="", max_length=1000)
    body_en: str = Field(default="", max_length=1000)
    via_bot: bool = False


def _clean_filter(f: dict) -> dict:
    return {k: v for k, v in (f or {}).items() if k in notifications.FILTERS and v not in (None, "", False)}


@app.post("/api/admin/notifications/preview")
def admin_notifications_preview(body: BroadcastTarget, admin_id: int = Depends(get_current_admin)):
    uids = notifications.resolve(db, body.target, body.uid, _clean_filter(body.filter))
    total = sum(1 for _ in db.collection("users").stream()) if uids is None else len(uids)
    return {"count": total}


def _bot_broadcast(uids: list, text_ar: str, text_en: str):
    for i, uid in enumerate(uids):
        snap = user_ref(uid).get()
        lang = ((snap.to_dict() or {}).get("language") if snap.exists else None) or "ar"
        tg("sendMessage", chat_id=uid, text=text_ar if lang == "ar" else text_en)
        if i % 25 == 24:
            time.sleep(1.1)  # حد تلجرام ~30 رسالة/ث


@app.post("/api/admin/notifications/broadcast")
def admin_notifications_broadcast(body: BroadcastBody, admin_id: int = Depends(get_current_admin)):
    if not (body.title_ar or body.title_en):
        raise HTTPException(422, "title_required")
    if body.target == "user" and not body.uid:
        raise HTTPException(422, "uid_required")
    row = notifications.broadcast(db, admin_id, body.target, body.title_ar or body.title_en, body.title_en or body.title_ar,
                                  body.body_ar, body.body_en or body.body_ar, body.uid, _clean_filter(body.filter))
    if body.via_bot:
        uids = row["uids"] if not row["all"] else [d.id for d in db.collection("users").stream()]
        ar = f"🔔 {row['title_ar']}\n\n{row['body_ar']}".strip()
        en = f"🔔 {row['title_en']}\n\n{row['body_en']}".strip()
        threading.Thread(target=lambda: _safe(lambda: _bot_broadcast(uids, ar, en)), daemon=True).start()
    return {k: v for k, v in row.items() if k != "uids"}


@app.get("/api/admin/notifications/broadcasts")
def admin_notifications_history(admin_id: int = Depends(get_current_admin)):
    rows = [{"id": d.id, **{k: v for k, v in (d.to_dict() or {}).items() if k != "uids"}}
            for d in db.collection(notifications.BROADCASTS).order_by("at", direction="DESCENDING").limit(200).stream()]
    return {"rows": rows}


# ═══════════════════════════ نافذة "ما الجديد" (Announcements) ═══════════════════════════
@app.get("/api/announcements")
def my_announcement(init_data: str):
    user = verify_init_data(init_data)
    snap = user_ref(user["id"]).get()
    return {"announcement": announcements.pick(db, snap.to_dict() if snap.exists else {})}


class AnnounceSeen(BaseModel):
    init_data: str
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{2,40}$")
    dismiss: bool = False


@app.post("/api/announcements/seen")
def my_announcement_seen(body: AnnounceSeen):
    user = verify_init_data(body.init_data)
    announcements.mark_seen(db, user["id"], body.id, body.dismiss)
    ref = db.collection(announcements.COL).document(body.id)
    snap = ref.get()
    if snap.exists:
        d = snap.to_dict() or {}
        ref.set({"views": int(d.get("views") or 0) + 1, "dismissals": int(d.get("dismissals") or 0) + int(body.dismiss)}, merge=True)
    return {"ok": True}


@app.get("/api/admin/announcements")
def admin_announcements(admin_id: int = Depends(get_current_admin)):
    return {"items": announcements.list_all(db), "defaults": announcements.DEFAULT, "icons": announcements.ICONS}


def _save_announcement(aid: str | None, patch: dict, admin_id: int) -> dict:
    ref = db.collection(announcements.COL).document(aid) if aid else db.collection(announcements.COL).document()
    snap = ref.get()
    if aid and not snap.exists:
        raise HTTPException(404, "not_found")
    try:
        clean = announcements.clean(patch, snap.to_dict() if snap.exists else None)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    base = {} if snap.exists else {k: v for k, v in announcements.DEFAULT.items() if k != "id"} | {"enabled": False, "features": []}
    ref.set({**base, **clean, "updated_at": time.time(), "updated_by": admin_id}, merge=True)
    return {**announcements.DEFAULT, **(ref.get().to_dict() or {}), "id": ref.id}


@app.post("/api/admin/announcements")
def admin_announcement_create(patch: dict, admin_id: int = Depends(get_current_admin)):
    return _save_announcement(None, patch, admin_id)


@app.put("/api/admin/announcements/{aid}")
def admin_announcement_update(aid: str, patch: dict, admin_id: int = Depends(get_current_admin)):
    return _save_announcement(aid, patch, admin_id)


@app.delete("/api/admin/announcements/{aid}")
def admin_announcement_delete(aid: str, admin_id: int = Depends(get_current_admin)):
    db.collection(announcements.COL).document(aid).delete()
    return {"ok": True}


@app.post("/api/admin/announcements/seed")
def admin_announcement_seed(admin_id: int = Depends(get_current_admin)):
    return announcements.seed_default(db)


@app.post("/api/admin/media/image")
def admin_media_image(body: AdminPhoto, admin_id: int = Depends(get_current_admin)):
    """صورة لنافذة التحديثات (JPEG/PNG/WebP حتى 1.5MB)."""
    return {"url": save_avatar("ann", body.photo, 1_500_000)}


# ═══════════════════════════ سجل الأخطاء + زر "تواصل مع الدعم" ═══════════════════════════
class ClientError(BaseModel):
    init_data: str = ""
    kind: str = Field(default="ui", pattern="^(network|server|operation|ui)$")
    code: str = Field(default="", max_length=80)
    message: str = Field(default="", max_length=500)
    page: str = Field(default="", max_length=60)
    online: bool | None = None
    ua: str = Field(default="", max_length=300)
    context: dict = Field(default_factory=dict)
    ref: str = Field(default="", max_length=12)


def _support_start_link(ref: str) -> str:
    return ""  # زر «تواصل مع الدعم» يفتح مركز الدعم داخل التطبيق مع رقم الخطأ


_ERR_RL: dict = {}
ERR_RL_MAX = 20  # تقرير خطأ لكل IP في الدقيقة (يمنع إغراق السجل؛ المسار متاح بلا هوية لأخطاء ما قبل الدخول والانقطاع)


@app.post("/api/errors")
def report_client_error(body: ClientError, request: Request):
    ip = admin_access.client_ip({k.lower(): v for k, v in request.headers.items()}, request.client.host if request.client else "")
    now = time.time()
    hits = [t for t in _ERR_RL.get(ip, []) if now - t < 60]
    if len(hits) >= ERR_RL_MAX:
        raise HTTPException(429, "too_many_reports")
    _ERR_RL[ip] = hits + [now]
    if len(_ERR_RL) > 5000:
        _ERR_RL.clear()
    uid = None
    if body.init_data:
        try:
            uid = verify_init_data(body.init_data)["id"]
        except HTTPException:
            uid = None
    ctx = {k: str(v)[:200] for k, v in list((body.context or {}).items())[:12]}
    row = support.log_error(db, uid, body.kind, body.code, body.message, body.page, body.online,
                            body.ua or request.headers.get("user-agent", ""), ctx, "client", body.ref or None)
    return {"ref": row["ref"], "priority": row["priority"], "support_url": _support_start_link(row["ref"])}


@app.exception_handler(Exception)
async def server_error_handler(request: Request, exc: Exception):
    """أي خطأ غير متوقع في الخادم: يُسجَّل برقم مرجعي يظهر للمستخدم مع زر الدعم."""
    from fastapi.responses import JSONResponse

    log.exception("unhandled error on %s", request.url.path, exc_info=exc)
    row = await run_in_threadpool(support.log_error, db, None, "server", "500", f"{type(exc).__name__}: {exc}"[:400],
                                  request.url.path[:60], True, request.headers.get("user-agent", ""), {}, "server")
    return JSONResponse({"detail": "server_error", "ref": row["ref"]}, status_code=500)


@app.get("/api/admin/errors")
def admin_errors(kind: str | None = None, q: str | None = None, limit: int = 200, admin_id: int = Depends(get_current_admin)):
    rows = [d.to_dict() or {} for d in db.collection(support.ERRORS).order_by("at", direction="DESCENDING").limit(max(1, min(limit, 1000))).stream()]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in json.dumps(r, ensure_ascii=False, default=str).lower()]
    return {"rows": rows}


# ═══════════════════════════ الدعم الفني الذكي (لوحة التحكم) ═══════════════════════════
support.NOTIFY["fn"] = lambda uid, kind, tar, ten, bar, ben: notifications.push(db, uid, kind, tar, ten, bar, ben)


def _recheck_payment_for(uid) -> dict | None:
    """أداة الإصلاح الذاتي recheck_payment: تسأل المزوّد نفسه؛ لا تفعيل بدون تأكيده."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    pays = [{"id": d.id, **(d.to_dict() or {})} for d in db.collection("payments").where(filter=FieldFilter("uid", "==", int(uid))).stream()]
    pays = [p for p in pays if p.get("status") not in ("finished", "failed", "expired", "refunded")
            and time.time() - float(p.get("created_at") or 0) < 48 * 3600]
    if not pays:
        return None
    p = max(pays, key=lambda x: x.get("created_at") or 0)
    if p.get("method") == "ton":
        try:
            scan_ton_payments(only_order=p["id"], raise_errors=True)
        except Exception as e:  # noqa: BLE001
            return {"order_id": p["id"], "method": "ton", "status": p.get("status"), "activated": False, "error": str(e)[:120]}
    elif p.get("np_payment_id"):
        try:
            remote = payments.get_payment(p["np_payment_id"]).get("payment_status")
            if remote and remote != p.get("status"):
                process_nowpayments({"order_id": p["id"], "payment_status": remote, "payment_id": p["np_payment_id"]})
        except payments.PaymentError as e:
            return {"order_id": p["id"], "method": p.get("method"), "status": p.get("status"), "activated": False, "error": str(e)[:120]}
    now = (db.collection("payments").document(p["id"]).get().to_dict() or {}).get("status")
    return {"order_id": p["id"], "method": p.get("method"), "status": now, "activated": now == "finished"}


support.PAYMENT_CHECKER["fn"] = _recheck_payment_for


@app.get("/api/admin/support/config")
def admin_support_config(admin_id: int = Depends(get_current_admin)):
    cfg = support.get_config(db)
    return {**support.public_config(cfg), "default_prompt": support.DEFAULT_PROMPT, "ai_available": support.ai_available(cfg), "model_default": support.MODEL_DEFAULT,
            "main_bot_username": _bot_username(), "fix_actions": list(support.FIX_ACTIONS)}


@app.put("/api/admin/support/config")
def admin_support_config_update(patch: dict, admin_id: int = Depends(get_current_admin)):
    try:
        clean = support.clean_config(patch)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    cfg = support.save_config(db, clean)
    return support.public_config(cfg)


def _mask_id(v) -> str:
    v = str(v or "")
    return ("•••" + v[-3:]) if len(v) > 3 else "•••"


def _scoped_ticket(t: dict, scope: dict) -> dict:
    """ما يراه العضو من التذكرة حسب خيارات الرؤية الخاصة به."""
    if scope.get("hide_contacts"):
        t = {**t, "uid": _mask_id(t.get("uid"))}
    return t


def _ticket_guard(tid: str, admin_id: int) -> dict:
    t = support.get_ticket(db, tid)
    if not t:
        raise HTTPException(404, "not_found")
    scope = admin_access.scope_of(db, ADMIN_IDS, admin_id)
    if scope["tickets"] == "assigned" and str(t.get("assigned_to") or "") != str(admin_id):
        raise HTTPException(403, "not_your_ticket")  # العضو المقيّد يرى تذاكره المسندة فقط
    return t


def _support_agents() -> list:
    return [{"id": k, "name": v.get("name") or k, **admin_access.clean_agent(v.get("agent"))}
            for k, v in admin_access.staff_members(db).items() if (v.get("agent") or {}).get("enabled")]


def _support_service_status() -> dict:
    s_ = billing.get_settings(db)
    hb = heartbeat.snapshot() or {}
    return {"maintenance": bool(s_.get("maintenance")), "trading_paused": bool(s_.get("kill_switch")),
            "mt5_robot": hb.get("status"), "payments": {"ton": s_.get("pay_ton_enabled", True), "crypto": s_.get("pay_crypto_enabled", True),
                                                         "stars": s_.get("pay_stars_enabled", True)}}


support.AGENTS["fn"] = _support_agents
support.SERVICE["fn"] = _support_service_status


@app.get("/api/admin/support/tickets")
def admin_support_tickets(status: str | None = None, priority: str | None = None, q: str | None = None, mine: bool = False,
                          assigned: str | None = None, admin_id: int = Depends(get_current_admin)):
    scope = admin_access.scope_of(db, ADMIN_IDS, admin_id)
    rows = [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(support.TICKETS).order_by("updated_at", direction="DESCENDING").limit(500).stream()]
    if mine or scope["tickets"] == "assigned":
        rows = [r for r in rows if str(r.get("assigned_to") or "") == str(admin_id)]
    elif assigned == "none":
        rows = [r for r in rows if not r.get("assigned_to")]
    elif assigned:
        rows = [r for r in rows if str(r.get("assigned_to") or "") == assigned]
    if status == "active":
        rows = [r for r in rows if r.get("status") in ("open", "in_progress", "escalated")]
    elif status:
        rows = [r for r in rows if r.get("status") == status]
    if priority:
        rows = [r for r in rows if r.get("priority") == priority]
    if q:
        ql = q.lower().lstrip("#")
        rows = [r for r in rows if ql in f"{r['id']} {r.get('uid')} {r.get('subject')}".lower()]
    for r in rows:
        r.pop("history", None)
        r.pop("assign_log", None)
    rows = [_scoped_ticket(r, scope) for r in rows]
    from google.cloud.firestore_v1.base_query import FieldFilter

    mine_open = sum(1 for d in db.collection(support.TICKETS).where(filter=FieldFilter("assigned_to", "==", str(admin_id))).stream()
                    if (d.to_dict() or {}).get("status") in support.ACTIVE)
    return {"rows": rows, "stats": {**support_stats(), "mine_open": mine_open}, "scope": scope}


def support_stats() -> dict:
    rows = [d.to_dict() or {} for d in db.collection(support.TICKETS).order_by("updated_at", direction="DESCENDING").limit(1000).stream()]
    active = [r for r in rows if r.get("status") in ("open", "in_progress", "escalated")]
    scores = [r["csat"]["score"] for r in rows if isinstance(r.get("csat"), dict) and r["csat"].get("score")]
    return {"open": len(active), "critical_open": sum(1 for r in active if r.get("priority") == "critical"),
            "escalated": sum(1 for r in active if r.get("status") == "escalated"),
            "resolved": sum(1 for r in rows if r.get("status") in ("resolved", "closed")),
            "csat_avg": round(sum(scores) / len(scores), 2) if scores else None, "csat_count": len(scores), "total": len(rows)}


@app.get("/api/admin/support/tickets/{tid}")
def admin_support_ticket(tid: str, admin_id: int = Depends(get_current_admin)):
    t = _ticket_guard(tid, admin_id)
    scope = admin_access.scope_of(db, ADMIN_IDS, admin_id)
    ctx = support.user_context(db, t["uid"])
    if scope["hide_money"]:  # إخفاء الأرصدة والمبالغ عن هذا العضو
        if ctx.get("live"):
            ctx["live"] = {**ctx["live"], "balance": "•••", "equity": "•••"}
        ctx["recent_payments"] = [{**p_, "usd": "•••"} for p_ in ctx.get("recent_payments") or []]
    return {"ticket": _scoped_ticket(t, scope), "messages": support.messages_of(db, tid), "context": ctx,
            "error": support.get_error(db, t.get("error_ref")) if t.get("error_ref") else None, "scope": scope,
            "agents": [{"id": a["id"], "name": a["name"], "available": a["available"]} for a in support.agents()],
            "categories": support.CATEGORY_LABEL}


class TicketReply(BaseModel):
    text: str = Field(min_length=1, max_length=3500)


@app.post("/api/admin/support/tickets/{tid}/reply")
def admin_support_reply(tid: str, body: TicketReply, admin_id: int = Depends(get_current_admin)):
    cur = _ticket_guard(tid, admin_id)
    member = admin_access.staff_members(db).get(str(admin_id)) or {}
    name = member.get("name") or ("المالك" if admin_id in ADMIN_IDS else str(admin_id))
    if not cur.get("assigned_to"):  # من يرد أولًا يستلم التذكرة (لا يتدخل المساعد بعدها)
        support.assign(db, support.get_config(db), cur, agent={"id": str(admin_id), "name": name}, by="claim", notify=False)
    t = support.agent_reply(db, support.get_config(db), tid, body.text.strip(), by=f"admin:{admin_id}", by_name=name)
    if not t:
        raise HTTPException(404, "not_found")
    return {"ok": True, "ticket": t}


class TicketStatus(BaseModel):
    status: str = Field(pattern="^(open|in_progress|escalated|resolved|closed)$")
    note: str = Field(default="", max_length=300)
    priority: str | None = Field(default=None, pattern="^(critical|medium|low)$")


@app.post("/api/admin/support/tickets/{tid}/status")
def admin_support_status(tid: str, body: TicketStatus, admin_id: int = Depends(get_current_admin)):
    _ticket_guard(tid, admin_id)
    if body.priority:
        db.collection(support.TICKETS).document(tid).set({"priority": body.priority}, merge=True)
    return {"ticket": support.set_status(db, support.get_config(db), tid, body.status, by=f"admin:{admin_id}", note=body.note)}


class TicketAssign(BaseModel):
    agent_id: str = Field(default="", pattern=r"^\d{0,15}$")  # فارغ = التالي بالتوزيع العادل


@app.post("/api/admin/support/tickets/{tid}/assign")
def admin_support_assign(tid: str, body: TicketAssign, admin_id: int = Depends(get_current_admin)):
    t = _ticket_guard(tid, admin_id)
    if admin_access.scope_of(db, ADMIN_IDS, admin_id)["tickets"] == "assigned" and body.agent_id != str(admin_id):
        raise HTTPException(403, "scope_assigned_only")  # العضو المقيّد لا يعيد توزيع التذاكر
    cfg = support.get_config(db)
    if body.agent_id:
        a = next((x for x in support.agents() if str(x["id"]) == body.agent_id), None)
        if not a and int(body.agent_id) not in ADMIN_IDS and body.agent_id not in admin_access.staff_members(db):
            raise HTTPException(404, "agent_not_found")
        a = a or {"id": body.agent_id, "name": (admin_access.staff_members(db).get(body.agent_id) or {}).get("name") or body.agent_id}
        support.assign(db, cfg, t, agent=a, by=f"admin:{admin_id}")
    elif not support.assign(db, {**cfg, "assign_mode": cfg.get("assign_mode") if cfg.get("assign_mode") != "off" else "round_robin"},
                            t, by=f"admin:{admin_id}", exclude=(t.get("assigned_to"),) if t.get("assigned_to") else ()):
        raise HTTPException(409, "no_available_agent")
    return {"ticket": support.get_ticket(db, tid)}


@app.post("/api/admin/support/tickets/{tid}/draft")
def admin_support_draft(tid: str, admin_id: int = Depends(get_current_admin)):
    _ticket_guard(tid, admin_id)
    try:
        return support.ai_draft(db, support.get_config(db), tid)
    except support.AiError as e:
        raise HTTPException(503, str(e)[:120])


@app.get("/api/admin/support/agents")
def admin_support_agents(admin_id: int = Depends(get_current_admin)):
    """لوحة الفريق: الحِمل الحالي، الإسنادات، المحلولة، ومتوسط التقييم لكل موظف."""
    loads = support.agent_loads(db)
    rr = support._rr(db)
    stats: dict = {}
    for d in db.collection(support.TICKETS).order_by("updated_at", direction="DESCENDING").limit(2000).stream():
        r = d.to_dict() or {}
        a = str(r.get("assigned_to") or "")
        if not a:
            continue
        st = stats.setdefault(a, {"resolved": 0, "scores": []})
        if r.get("status") in ("resolved", "closed"):
            st["resolved"] += 1
        if isinstance(r.get("csat"), dict) and r["csat"].get("score"):
            st["scores"].append(r["csat"]["score"])
    rows = []
    for a in support.agents():
        st = stats.get(str(a["id"]), {"resolved": 0, "scores": []})
        rows.append({**a, "active": loads.get(str(a["id"]), 0), "assigned_total": int((rr.get("counts") or {}).get(str(a["id"])) or 0),
                     "resolved": st["resolved"], "csat_avg": round(sum(st["scores"]) / len(st["scores"]), 2) if st["scores"] else None})
    cfg = support.get_config(db)
    return {"rows": rows, "next": (support.pick_agent(db, cfg, {"lang": "ar"}) or {}).get("id"), "mode": cfg.get("assign_mode"),
            "skills": admin_access.SKILLS}


class Availability(BaseModel):
    available: bool


@app.post("/api/admin/support/agents/me")
def admin_support_my_availability(body: Availability, admin_id: int = Depends(get_current_admin)):
    """الموظف يبدّل حالته (متاح/غير متاح لاستلام تذاكر جديدة) بنفسه."""
    ref = db.collection("config").document("staff")
    snap = ref.get()
    members = dict(((snap.to_dict() or {}).get("members") or {}) if snap.exists else {})
    m = members.get(str(admin_id))
    if not m:
        raise HTTPException(404, "not_a_member")
    m["agent"] = {**admin_access.clean_agent(m.get("agent")), "available": body.available}
    ref.set({"members": members})
    admin_access.invalidate()
    return {"ok": True, "agent": m["agent"]}


class KbEntry(BaseModel):
    q: str = Field(min_length=3, max_length=300)
    a: str = Field(min_length=3, max_length=2000)


@app.get("/api/admin/support/kb")
def admin_support_kb(admin_id: int = Depends(get_current_admin)):
    return {"rows": support.kb_entries(db)}


@app.post("/api/admin/support/kb")
def admin_support_kb_add(body: KbEntry, admin_id: int = Depends(get_current_admin)):
    ref = db.collection(support.KB).document()
    ref.set({"q": body.q.strip(), "a": body.a.strip(), "at": time.time(), "by": admin_id})
    return {"id": ref.id}


@app.delete("/api/admin/support/kb/{kid}")
def admin_support_kb_delete(kid: str, admin_id: int = Depends(get_current_admin)):
    db.collection(support.KB).document(kid).delete()
    return {"ok": True}


@app.get("/api/admin/support/fixes")
def admin_support_fixes(admin_id: int = Depends(get_current_admin)):
    return {"rows": [d.to_dict() or {} for d in db.collection(support.FIXES).order_by("at", direction="DESCENDING").limit(300).stream()]}


# ═══════════════════════════ محفظة TON (لوحة التحكم + OTP) ═══════════════════════════
def _send_otp(admin_id, text: str) -> bool:
    if tonadmin.OTP_BOT_TOKEN:
        return bool(support.bot_call(tonadmin.OTP_BOT_TOKEN, "sendMessage", chat_id=admin_id, text=text).get("ok"))
    return bool(tg("sendMessage", chat_id=admin_id, text=text).get("ok"))


class TonOtp(BaseModel):
    action: str = Field(pattern="^(set_wallet|set_window|toggle|transfer|gw_payout)$")
    params: dict = Field(default_factory=dict)


class TonExecute(BaseModel):
    otp_id: str = Field(min_length=8, max_length=40)
    code: str = Field(pattern=r"^\d{6}$")


class TonTransferResult(BaseModel):
    otp_id: str = Field(min_length=8, max_length=40)
    ok: bool
    boc: str = Field(default="", max_length=4000)
    error: str = Field(default="", max_length=300)


@app.get("/api/admin/ton/overview")
def admin_ton_overview(admin_id: int = Depends(get_current_admin)):
    return tonadmin.overview(db)


@app.post("/api/admin/ton/otp")
def admin_ton_otp(body: TonOtp, admin_id: int = Depends(get_current_admin)):
    try:
        return tonadmin.request_otp(db, admin_id, body.action, body.params, _send_otp)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))


@app.post("/api/admin/ton/execute")
def admin_ton_execute(body: TonExecute, admin_id: int = Depends(get_current_admin)):
    try:
        return tonadmin.execute(db, admin_id, body.otp_id, body.code)
    except PermissionError as e:
        raise HTTPException(403, str(e))


@app.post("/api/admin/ton/transfer-result")
def admin_ton_transfer_result(body: TonTransferResult, admin_id: int = Depends(get_current_admin)):
    try:
        tonadmin.transfer_result(db, admin_id, body.otp_id, body.ok, body.boc, body.error)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return {"ok": True}


@app.get("/api/admin/ton/log")
def admin_ton_log(admin_id: int = Depends(get_current_admin)):
    return {"rows": tonadmin.history(db)}


# ═══════════════════════════ بوابة الدفع الخاصة (AW Pay) ═══════════════════════════
def _gw_user(uid, text_ar: str, text_en: str):
    lang = ((user_ref(uid).get().to_dict() or {}).get("language")) or "ar"
    tg("sendMessage", chat_id=uid, text=text_ar if lang == "ar" else text_en)
    notifications.push(db, uid, "payment", "دفعة ناقصة" if "⚠️" in text_ar else "تحديث الدفع",
                       "Partial payment" if "⚠️" in text_en else "Payment update", text_ar, text_en)


def gw_hooks() -> dict:
    return {"paid": lambda oid, extra: activate_payment(oid, extra), "user": _gw_user, "admin": notify_admins}


def gateway_summary() -> str:
    """ملخص سريع لبوابة الدفع في البوت (/gateway للأدمن)."""
    o = gateway.overview(db)
    st, gas = o["stats"], gateway.gas_status(db)
    lines = ["💳 بوابة الدفع AW Pay", f"الحالة: {'✅ تعمل' if o['active'] else '⏸️ موقوفة'}",
             f"آخر 30 يومًا: {st['finished_30d']} دفعة · ${st['revenue_usd_30d']}",
             f"مفتوحة: {st['open']} · ناقصة: {st['partial']} · تحتاج قرارك: {st['underpaid']}"]
    for n, g in gas.items():
        lines.append(f"⛽ غاز {n.upper()}: {g.get('balance', '?')} {g.get('symbol', '')}{' ⚠️ منخفض' if g.get('low') else ''}")
    lines.append("التحكم الكامل: لوحة التحكم ← بوابة الدفع")
    return "\n".join(lines)


def backup_local_db(keep: int = 14):
    """نسخة يومية متّسقة من قاعدة SQLite في data/backups (آخر 14 يومًا)."""
    d = os.path.join(os.path.dirname(db.path), "backups")
    db.backup(os.path.join(d, f"aw-{time.strftime('%Y%m%d')}.db"))
    for old in sorted(f for f in os.listdir(d) if f.startswith("aw-") and f.endswith(".db"))[:-keep]:
        os.remove(os.path.join(d, old))
    res = db.maintenance(full=time.gmtime().tm_wday == 6)  # بعد النسخة: دمج WAL وتقليصه + فحص سلامة (كامل أسبوعيًا)
    if res.get("integrity") != "ok":
        notify_admins(f"⚠️ فحص سلامة قاعدة البيانات: {res.get('integrity')}\nالنسخ الاحتياطية في data/backups.")


def run_gateway_tick():
    if gateway.active(gateway.get_config(db)):
        gateway.tick(db, gw_hooks())
        _JOBS["gw_tick_run"] = {"last": time.time(), "ok": True}


def run_gateway_sweeps():
    gateway.sweep_tick(db, gw_hooks())


_gw_gas_alert = {"at": 0.0}


def run_gateway_gas_check():
    """تنبيه عند انخفاض خزان الغاز (مرة كل 6 ساعات كحد أقصى)."""
    cfg = gateway.get_config(db)
    if not gateway.active(cfg) or time.time() - _gw_gas_alert["at"] < 6 * 3600:
        return
    low = [f"{n.upper()}: {g.get('balance')} {g.get('symbol')} — {g['address']}" for n, g in gateway.gas_status(db).items() if g.get("low")]
    if low:
        _gw_gas_alert["at"] = time.time()
        notify_admins("⛽ خزان الغاز لبوابة الدفع منخفض — التجميع التلقائي قد يتوقف:\n" + "\n".join(low))


def _gw_http(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except gateway.GatewayError as e:
        raise HTTPException(e.status, e.code)
    except gateway.ch.ChainError as e:
        raise HTTPException(502, f"chain_error: {e}"[:160])


@app.get("/api/admin/gateway")
def admin_gateway(admin_id: int = Depends(get_current_admin)):
    out = gateway.overview(db)
    out["gas"] = gateway.gas_status(db)
    return out


@app.put("/api/admin/gateway")
def admin_gateway_save(patch: dict, admin_id: int = Depends(get_current_admin)):
    try:
        clean = gateway.clean_config(patch)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))
    if clean.get("enabled") and not gateway.master():
        raise HTTPException(422, "gateway_master_key_missing")
    db.collection(gateway.CONFIG_DOC[0]).document(gateway.CONFIG_DOC[1]).set({**clean, "updated_by": admin_id, "updated_at": time.time()}, merge=True)
    return gateway.overview(db)


@app.get("/api/admin/gateway/invoices")
def admin_gateway_invoices(status: str = "", limit: int = 100, admin_id: int = Depends(get_current_admin)):
    from google.cloud.firestore_v1.base_query import FieldFilter

    rows = []
    for d in db.collection("payments").where(filter=FieldFilter("method", "==", "gateway")).stream():
        p = d.to_dict() or {}
        if status and p.get("status") != status:
            continue
        a = gateway.ASSETS.get(p.get("asset"), {})
        rows.append({"id": d.id, "uid": p.get("uid"), "status": p.get("status"), "asset": p.get("asset"), "symbol": a.get("symbol"),
                     "network": p.get("network"), "address": p.get("address"), "memo": p.get("memo"), "amount": p.get("amount_text"),
                     "received": gateway.fmt_units(p["asset"], p.get("received_units") or 0) if p.get("asset") in gateway.ASSETS else None,
                     "amount_usd": p.get("amount_usd"), "created_at": p.get("created_at"), "expires_at": p.get("expires_at"),
                     "confirmed_at": p.get("confirmed_at"), "package_id": p.get("package_id"), "tx_hashes": p.get("tx_hashes"),
                     "manual_accept": p.get("manual_accept"), "check_error": p.get("check_error")})
    rows.sort(key=lambda r: -(r.get("created_at") or 0))
    return {"rows": rows[:max(1, min(500, limit))]}


class GwNote(BaseModel):
    note: str = Field(default="", max_length=200)


@app.post("/api/admin/gateway/invoices/{order_id}/check")
def admin_gateway_check(order_id: str, admin_id: int = Depends(get_current_admin)):
    return _gw_http(gateway.check_invoice, db, order_id, gw_hooks())


@app.post("/api/admin/gateway/invoices/{order_id}/accept")
def admin_gateway_accept(order_id: str, body: GwNote, admin_id: int = Depends(get_current_admin)):
    return _gw_http(gateway.accept_invoice, db, order_id, admin_id, gw_hooks(), body.note)


@app.post("/api/admin/gateway/invoices/{order_id}/cancel")
def admin_gateway_cancel(order_id: str, admin_id: int = Depends(get_current_admin)):
    return _gw_http(gateway.cancel_invoice, db, order_id, admin_id)


@app.get("/api/admin/gateway/addresses")
def admin_gateway_addresses(admin_id: int = Depends(get_current_admin)):
    rows = [{"id": d.id, **{k: v for k, v in (d.to_dict() or {}).items()}} for d in db.collection(gateway.ADDRS).stream()]
    rows.sort(key=lambda r: (not r.get("dirty"), not r.get("op"), -(r.get("created_at") or 0)))
    return {"rows": rows[:500]}


class GwSweep(BaseModel):
    network: str = Field(pattern=r"^(tron|bsc)$")
    uid: str = Field(pattern=r"^\d{1,15}$")


@app.post("/api/admin/gateway/sweep")
def admin_gateway_sweep(body: GwSweep, admin_id: int = Depends(get_current_admin)):
    return _gw_http(gateway.sweep_address, db, body.network, body.uid, gw_hooks(), True)


@app.get("/api/admin/gateway/sweeps")
def admin_gateway_sweeps(admin_id: int = Depends(get_current_admin)):
    rows = [d.to_dict() or {} for d in db.collection(gateway.SWEEPS).stream()]
    rows.sort(key=lambda r: -(r.get("at") or 0))
    return {"rows": rows[:200]}


@app.get("/api/admin/gateway/ton-incoming")
def admin_gateway_ton_incoming(admin_id: int = Depends(get_current_admin)):
    """آخر التحويلات الواردة لعنوان TON مع ما طابق منها فاتورة — لمطابقة التحويلات التي أُرسلت بلا تعليق يدويًا."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    cfg = gateway.get_config(db)
    addr = cfg["payout"].get("ton")
    if not addr:
        return {"rows": []}
    memos = {}
    for d in db.collection("payments").where(filter=FieldFilter("method", "==", "gateway")).stream():
        p = d.to_dict() or {}
        if p.get("memo"):
            memos[p["memo"]] = d.id
    rows = []
    for kind, fetch in (("ton", lambda: gateway.ch.ton_incoming(addr, 50)),
                        ("usdtton", lambda: gateway.ch.ton_jetton_incoming(addr, gateway.ch.USDT_TON_MASTER, 50))):
        try:
            for t in fetch():
                rows.append({**t, "asset": kind, "amount_text": gateway.fmt_units(kind, t["amount"]),
                             "order_id": memos.get(t["comment"].replace(" ", "").upper())})
        except gateway.ch.ChainError:
            continue
    rows.sort(key=lambda r: -r["utime"])
    return {"rows": rows}


# ═══════════════════════════ تنبيهات فورية داخل اللوحة ═══════════════════════════
@app.get("/api/admin/alerts")
def admin_alerts(since: float = 0, admin_id: int = Depends(get_current_admin)):
    """أحداث مهمة منذ since: خطأ حرج، تذكرة عاجلة/مصعّدة، دفعة كبيرة، عطل في النظام."""
    now = time.time()
    since = max(since, now - 7 * 86400)
    big = float(billing.get_settings(db).get("alert_large_payment_usd") or 400)
    out = []
    for d in db.collection(support.ERRORS).order_by("at", direction="DESCENDING").limit(50).stream():
        e = d.to_dict() or {}
        if (e.get("at") or 0) > since and e.get("priority") == "critical":
            out.append({"id": f"e-{d.id}", "type": "error", "level": "critical", "at": e["at"], "page": "support",
                        "title": f"خطأ حرج {e.get('ref')}", "text": f"{e.get('kind')} · {e.get('message') or e.get('code')}"[:160]})
    for d in db.collection(support.TICKETS).order_by("updated_at", direction="DESCENDING").limit(50).stream():
        t = d.to_dict() or {}
        if (t.get("updated_at") or 0) > since and t.get("status") in ("open", "in_progress", "escalated") \
                and (t.get("priority") == "critical" or t.get("status") == "escalated"):
            out.append({"id": f"t-{d.id}-{t.get('status')}", "type": "ticket", "level": "critical" if t.get("priority") == "critical" else "warn",
                        "at": t["updated_at"], "page": "support", "ref": d.id,
                        "title": f"تذكرة {'عاجلة' if t.get('priority') == 'critical' else 'مصعّدة'} #{d.id}", "text": (t.get("subject") or "")[:160]})
    for d in db.collection("payments").order_by("confirmed_at", direction="DESCENDING").limit(30).stream():
        p = d.to_dict() or {}
        usd = _pay_usd(p)
        if p.get("status") == "finished" and (p.get("confirmed_at") or 0) > since and usd >= big:
            out.append({"id": f"p-{d.id}", "type": "payment", "level": "info", "at": p["confirmed_at"], "page": "ceo",
                        "title": f"دفعة كبيرة ${round(usd, 2)}", "text": f"{p.get('method')} · {p.get('uid')}"})
    for d in db.collection("system_events").order_by("at", direction="DESCENDING").limit(20).stream():
        ev = d.to_dict() or {}
        if (ev.get("at") or 0) > since:
            out.append({"id": f"s-{d.id}", "type": "system", "level": "critical" if ev.get("type") in ("down", "stale") else "info",
                        "at": ev["at"], "page": "system", "title": f"حدث نظام: {ev.get('type')}", "text": str(ev.get("error") or ev.get("detail") or "")[:160]})
    out.sort(key=lambda x: -x["at"])
    return {"now": now, "alerts": out[:60], "support": support_stats()}


# ═══════════════════════════ مركز الدعم داخل التطبيق ═══════════════════════════
support.ACTIONS["unlink"] = do_unlink
support.ACTIONS["app_link"] = lambda: f"{WEBAPP_URL}?view=link"  # زر داخل مركز الدعم يفتح شاشة الربط
support.DB["v"] = db
support.APP_URL["v"] = WEBAPP_URL
support.bot_call = lambda _token, method, **p: tg(method, **p)  # تنبيهات الدعم تمر بنفس المسار (بطاقات GIF + إعادة المحاولة)
SUPPORT_MEDIA = os.getenv("SUPPORT_MEDIA_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "media", "support")
_SUP_NAME = re.compile(r"^[A-Za-z0-9_-]{22}\.(jpg|png|webp)$")


def save_support_image(b64: str) -> dict:
    """لقطة شاشة من المستخدم (≤ 3MB). الاسم عشوائي 128 بت (رابط غير قابل للتخمين)، والمساعد الذكي يقرأ الصورة."""
    try:
        raw = base64.b64decode(b64.split(",")[-1], validate=True)
    except (ValueError, TypeError):
        raise HTTPException(422, "bad_image")
    ext = _image_ext(raw)
    if len(raw) > 3_000_000 or not ext:
        raise HTTPException(422, "bad_image")
    os.makedirs(SUPPORT_MEDIA, exist_ok=True)
    name = f"{secrets.token_urlsafe(16)[:22]}.{ext}"
    path = os.path.join(SUPPORT_MEDIA, name)
    with open(path, "wb") as f:
        f.write(raw)
    return {"url": f"/api/support/media/{name}", "file": path}


@app.get("/api/support/media/{name}")
def support_media(name: str):
    path = os.path.join(SUPPORT_MEDIA, name)
    if not _SUP_NAME.match(name) or not os.path.exists(path):
        raise HTTPException(404, "not_found")
    return FileResponse(path, media_type=_MEDIA_TYPES[name.rsplit(".", 1)[-1]], headers={"Cache-Control": "private, max-age=86400"})


def _support_client_cfg(cfg: dict, lang: str) -> dict:
    return {"enabled": bool(cfg.get("enabled")), "ai_online": bool(cfg.get("ai_enabled") and support.ai_available(cfg)),
            "welcome": cfg.get(f"welcome_{lang}") or cfg.get("welcome_ar"), "quick": cfg.get(f"quick_{lang}") or [],
            "sounds": bool(cfg.get("sounds_enabled", True)), "attachments": bool(cfg.get("attachments_enabled", True)),
            "phone": cfg.get("support_phone") or ""}


@app.get("/api/support/thread")
def support_thread(init_data: str, lang: str = "ar"):
    user = verify_init_data(init_data)
    cfg = support.get_config(db)
    return {**support.app_thread(db, user["id"]), "config": _support_client_cfg(cfg, "en" if lang == "en" else "ar")}


class SupportSend(BaseModel):
    init_data: str
    text: str = Field(default="", max_length=2000)
    lang: str = Field(default="ar", pattern="^(ar|en)$")
    error_ref: str = Field(default="", max_length=12)
    image: str = Field(default="", max_length=4_200_000)


@app.post("/api/support/send")
def support_send(body: SupportSend):
    user = verify_init_data(body.init_data)
    cfg = support.get_config(db)
    if not cfg.get("enabled"):
        raise HTTPException(503, "support_disabled")
    text = body.text.strip()
    image = None
    if body.image:
        if not cfg.get("attachments_enabled", True):
            raise HTTPException(403, "attachments_disabled")
        image = save_support_image(body.image)
    ref = body.error_ref.strip().upper() or None
    if ref and not re.fullmatch(r"ERR-[A-Z0-9]{6}", ref):
        ref = None
    if not text and not image and not ref:
        raise HTTPException(422, "empty_message")
    if text and not image and support.text_command(db, cfg, user["id"], text, body.lang, "app"):
        return {"ok": True}
    support.handle_user_text(db, user["id"], text, body.lang, "app", ref, image)
    return {"ok": True}


class SupportAction(BaseModel):
    init_data: str
    kind: str = Field(pattern="^(csat|human|act)$")
    tid: str = Field(pattern=r"^T[A-Z0-9]{5}$")
    arg: str | None = Field(default=None, max_length=5)


@app.post("/api/support/action")
def support_action(body: SupportAction):
    user = verify_init_data(body.init_data)
    res = support.app_action(db, user["id"], body.kind, body.tid, body.arg)
    if not res.get("ok"):
        raise HTTPException(404 if res.get("reason") == "not_found" else 422, res.get("reason") or "invalid")
    return res


# ─── التعلّم: اقتراحات قاعدة المعرفة من التذاكر المحلولة ───
@app.get("/api/admin/support/suggestions")
def admin_kb_suggestions(admin_id: int = Depends(get_current_admin)):
    rows = [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(support.SUGGESTIONS).stream()]
    rows = [r for r in rows if r.get("status") == "pending"]
    rows.sort(key=lambda r: (-(r.get("score") or 0), -(r.get("at") or 0)))
    return {"rows": rows[:200]}


class KbApprove(BaseModel):
    q: str = Field(min_length=3, max_length=400)
    a: str = Field(min_length=3, max_length=1500)


@app.post("/api/admin/support/suggestions/{sid}/approve")
def admin_kb_suggestion_approve(sid: str, body: KbApprove, admin_id: int = Depends(get_current_admin)):
    ref = db.collection(support.SUGGESTIONS).document(sid)
    if not ref.get().exists:
        raise HTTPException(404, "not_found")
    db.collection(support.KB).document().set({"q": body.q.strip(), "a": body.a.strip(), "at": time.time(), "by": admin_id, "from_ticket": sid})
    ref.set({"status": "approved", "reviewed_by": admin_id, "reviewed_at": time.time()}, merge=True)
    return {"ok": True}


@app.delete("/api/admin/support/suggestions/{sid}")
def admin_kb_suggestion_reject(sid: str, admin_id: int = Depends(get_current_admin)):
    db.collection(support.SUGGESTIONS).document(sid).set({"status": "rejected", "reviewed_by": admin_id, "reviewed_at": time.time()}, merge=True)
    return {"ok": True}


# ═══════════════════════════ بطاقات GIF لرسائل البوت (لوحة التحكم) ═══════════════════════════
@app.get("/api/admin/cards")
def admin_cards(admin_id: int = Depends(get_current_admin)):
    cfg = cards_config()
    return {**cfg, "catalog": [{"kind": k, "label": v[0], "title_ar": v[1], "title_en": v[2]} for k, v in cards.KINDS.items()],
            "cached": sum(1 for _ in db.collection(CARD_FILES).stream())}


@app.put("/api/admin/cards")
def admin_cards_update(patch: dict, admin_id: int = Depends(get_current_admin)):
    out = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if isinstance(patch.get("kinds"), dict):
        out["kinds"] = {k: bool(v) for k, v in patch["kinds"].items() if k in cards.KINDS}
    db.collection(CARDS_DOC[0]).document(CARDS_DOC[1]).set(out, merge=True)
    _CARDS_CFG["v"] = None
    return cards_config()


@app.get("/api/admin/cards/preview")
def admin_cards_preview(text: str = "", kind: str = "", lang: str = "ar", title: str = "", hl: str | None = None,
                        admin_id: int = Depends(get_current_admin)):
    spec = cards.spec_for(text[:1000], "en" if lang == "en" else "ar", kind or None, title[:34] or None, hl[:14] if hl is not None else None)
    return FileResponse(cards.get_file(spec), media_type="image/gif", headers={"Cache-Control": "private, max-age=600", "X-Card-Kind": spec["kind"]})


@app.delete("/api/admin/cards/cache")
def admin_cards_cache_clear(admin_id: int = Depends(get_current_admin)):
    n = 0
    for d in db.collection(CARD_FILES).stream():
        db.collection(CARD_FILES).document(d.id).delete()
        n += 1
    return {"ok": True, "cleared": n}


# ═══════════════════════════ استوديو التصميم ═══════════════════════════
FRONTEND_INDEX = os.getenv("FRONTEND_INDEX") or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend", "dist", "index.html")


def _design_http(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except design.DesignError as e:
        raise HTTPException(422, str(e))


@app.get("/api/design")
def public_design():
    """التصميم المنشور (عام): يطبّقه التطبيق عند الفتح، ويُخزَّن على الجهاز لفتح فوري في المرة التالية."""
    return JSONResponse({**design.published(db), "bot": _bot_username() or ""}, headers={"Cache-Control": "public, max-age=30"})


@app.get("/api/admin/design")
def admin_design(admin_id: int = Depends(get_current_admin)):
    st = design.load(db)
    return {**st, "default": design.default(), "catalog": {
        "icons": list(design.ICONS), "home_blocks": list(design.HOME_BLOCKS), "start_blocks": list(design.START_BLOCKS),
        "quick_items": list(design.QUICK_ITEMS), "growth_cells": list(design.GROWTH_CELLS), "nav_items": list(design.NAV_ITEMS),
        "enums": design.ENUMS, "ranges": design.RANGES, "pages": list(design.PAGES),
        "presets": {k: {"name": v["name"], "desc": v["desc"]} for k, v in design.PRESETS.items()}},
        "bot_username": _bot_username() or "", "app_url": WEBAPP_URL}


class DesignBody(BaseModel):
    design: dict
    note: str = Field(default="", max_length=200)


@app.put("/api/admin/design/draft")
def admin_design_draft(body: DesignBody, admin_id: int = Depends(get_current_admin)):
    return {"draft": _design_http(design.save_draft, db, body.design)}


def _publish_design(d, admin_id, note, source):
    res = _design_http(design.publish, db, d, admin_id, note, source)
    _safe(lambda: design.write_seo(FRONTEND_INDEX, res["published"]["seo"], WEBAPP_URL))
    return res


@app.post("/api/admin/design/publish")
def admin_design_publish(body: DesignBody, admin_id: int = Depends(get_current_admin)):
    return _publish_design(body.design, admin_id, body.note, "manual")


@app.get("/api/admin/design/history")
def admin_design_history(admin_id: int = Depends(get_current_admin)):
    return {"rows": design.history(db)}


@app.get("/api/admin/design/history/{hid}")
def admin_design_history_item(hid: str, admin_id: int = Depends(get_current_admin)):
    row = design.history_item(db, hid)
    if not row:
        raise HTTPException(404, "not_found")
    return row


@app.post("/api/admin/design/history/{hid}/restore")
def admin_design_restore(hid: str, admin_id: int = Depends(get_current_admin)):
    res = _design_http(design.restore, db, hid, admin_id)
    _safe(lambda: design.write_seo(FRONTEND_INDEX, res["published"]["seo"], WEBAPP_URL))
    return res


@app.get("/api/admin/design/themes")
def admin_design_themes(admin_id: int = Depends(get_current_admin)):
    return {"rows": design.themes(db)}


class ThemeBody(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    scopes: list[str]
    tag: str = Field(default="", max_length=30)


@app.post("/api/admin/design/themes")
def admin_design_theme_save(body: ThemeBody, admin_id: int = Depends(get_current_admin)):
    return _design_http(design.save_theme, db, body.name, body.scopes, design.load(db)["draft"], admin_id, body.tag)


class ThemeApply(BaseModel):
    scopes: list[str] | None = None


@app.post("/api/admin/design/themes/{tid}/apply")
def admin_design_theme_apply(tid: str, body: ThemeApply, admin_id: int = Depends(get_current_admin)):
    return {"draft": _design_http(design.apply_theme, db, tid, body.scopes)}


@app.delete("/api/admin/design/themes/{tid}")
def admin_design_theme_delete(tid: str, admin_id: int = Depends(get_current_admin)):
    db.collection(design.THEMES).document(tid).delete()
    return {"ok": True}


@app.post("/api/admin/design/presets/{key}/apply")
def admin_design_preset(key: str, admin_id: int = Depends(get_current_admin)):
    return {"draft": _design_http(design.apply_preset, db, key)}


class DesignAi(BaseModel):
    scope: str = Field(pattern="^(global|start|home|nav|topbar|landing)$")
    question: str = Field(default="", max_length=600)
    design: dict | None = None


def _ai_cfg():
    cfg = support.get_config(db)
    if not support.ai_available(cfg):
        raise HTTPException(503, "ai_not_configured")
    return cfg


@app.post("/api/admin/design/ai")
def admin_design_ai(body: DesignAi, admin_id: int = Depends(get_current_admin)):
    cfg = _ai_cfg()
    draft = _design_http(design.clean, body.design) if body.design else design.load(db)["draft"]
    try:
        return design.ai_suggest(support.llm_text, cfg, draft, body.scope, body.question)
    except design.DesignError as e:
        raise HTTPException(422, str(e))
    except support.AiError as e:
        raise HTTPException(502, f"ai_failed: {str(e)[:160]}")


class IconAi(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    current: str = Field(default="", max_length=30)


@app.post("/api/admin/design/ai-icon")
def admin_design_ai_icon(body: IconAi, admin_id: int = Depends(get_current_admin)):
    cfg = _ai_cfg()
    try:
        return design.ai_icon(support.llm_text, cfg, body.label, body.current)
    except design.DesignError as e:
        raise HTTPException(422, str(e))
    except support.AiError as e:
        raise HTTPException(502, f"ai_failed: {str(e)[:160]}")


# ═══════════════════════════ التحليلات وتتبّع الزوار والأداء ═══════════════════════════
_TRACK_RL: dict = {}
TRACK_RL_MAX = 120  # دفعات لكل IP في الدقيقة


class TrackBody(BaseModel):
    init_data: str = Field(default="", max_length=8000)
    vid: str = Field(default="", max_length=40)
    sid: str = Field(max_length=40)
    lang: str = Field(default="", max_length=5)
    device: dict = Field(default_factory=dict)
    source: dict = Field(default_factory=dict)
    events: list = Field(default_factory=list, max_length=40)


@app.post("/api/track")
def track(body: TrackBody, request: Request):
    ip = admin_access.client_ip({k.lower(): v for k, v in request.headers.items()}, request.client.host if request.client else "")
    now = time.time()
    hits = [t for t in _TRACK_RL.get(ip, []) if now - t < 60]
    if len(hits) >= TRACK_RL_MAX:
        raise HTTPException(429, "too_many")
    _TRACK_RL[ip] = hits + [now]
    if len(_TRACK_RL) > 5000:
        _TRACK_RL.clear()
    uid = None
    if body.init_data:
        try:
            uid = verify_init_data(body.init_data)["id"]
        except HTTPException:
            uid = None  # الزائر يُتتبّع بمعرّفه المجهول فقط
    device = {**body.device, "ua": request.headers.get("user-agent", "")[:300]}
    return {"ok": True, "saved": tracking.ingest(db, uid, {**body.model_dump(), "device": device})}


@app.get("/api/admin/analytics")
def admin_analytics(days: int = 30, admin_id: int = Depends(get_current_admin)):
    return tracking.summary(db, days)


@app.get("/api/admin/analytics/user/{uid}")
def admin_analytics_user(uid: int, admin_id: int = Depends(get_current_admin)):
    return tracking.journey(db, uid)


@app.get("/api/admin/analytics/config")
def admin_analytics_config(admin_id: int = Depends(get_current_admin)):
    return tracking.get_config(db)


@app.put("/api/admin/analytics/config")
def admin_analytics_config_update(patch: dict, admin_id: int = Depends(get_current_admin)):
    try:
        return tracking.save_config(db, patch)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, str(e))


# ═══════════════════════════ النمو: كوبونات، هدايا، حملات، أتمتة، قمع، إحالة متدرّجة ═══════════════════════════
def _growth_http(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except growth.GrowthError as e:
        raise HTTPException(e.status, e.code)


GIFT_TEXT = {
    "days": ("🎁 هديتك: {v} يوم اشتراك مجاني أُضيفت لحسابك.", "🎁 Your gift: {v} free subscription days were added to your account."),
    "discount": ("🎁 هديتك: خصم {v}% في محفظة مكافآتك، يُطبَّق تلقائيًا عند الدفع.", "🎁 Your gift: {v}% off in your rewards wallet, applied automatically at checkout."),
    "free_days": ("🎁 هديتك: {v} يوم إضافي مع اشتراكك القادم.", "🎁 Your gift: {v} extra days with your next subscription."),
    "scratch": ("🎁 هديتك: بطاقة خدش جديدة تنتظرك في التطبيق!", "🎁 Your gift: a new scratch card is waiting in the app!"),
}
GIFT_ERR = {"gift_not_found": ("رابط الهدية غير صالح.", "This gift link isn't valid."), "gift_expired": ("انتهت صلاحية هذه الهدية.", "This gift has expired."),
            "gift_exhausted": ("نفدت هذه الهدية.", "This gift has run out."), "already_claimed": ("سبق أن حصلت على هذه الهدية ✅", "You've already claimed this gift ✅")}


def gift_message(uid, code: str, lang: str) -> str:
    i = 0 if lang == "ar" else 1
    try:
        r = growth.claim_gift(db, uid, code)
    except growth.GrowthError as e:
        return GIFT_ERR.get(e.code, ("تعذّر استلام الهدية.", "Couldn't claim the gift."))[i]
    return GIFT_TEXT[r["type"]][i].replace("{v}", str(r.get("value")))


class CodeBody(BaseModel):
    init_data: str
    code: str = Field(min_length=3, max_length=20)


@app.post("/api/coupons/redeem")
def coupon_redeem(body: CodeBody):
    user = verify_init_data(body.init_data)
    return _growth_http(growth.redeem_coupon, db, user["id"], body.code)


@app.post("/api/gifts/claim")
def gift_claim(body: CodeBody):
    user = verify_init_data(body.init_data)
    return _growth_http(growth.claim_gift, db, user["id"], body.code)


@app.post("/api/campaigns/track")
def campaign_track(body: CodeBody):
    """startapp=c_<slug> من داخل التطبيق (نفس منطق /start في البوت)."""
    user = verify_init_data(body.init_data)
    camp = growth.track_start(db, user["id"], body.code)
    return {"ok": bool(camp), "gift_code": (camp or {}).get("gift_code") or None}


@app.get("/api/referral/stats")
def referral_stats(init_data: str):
    user = verify_init_data(init_data)
    snap = user_ref(user["id"]).get()
    d = (snap.to_dict() or {}) if snap.exists else {}
    s_ = billing.get_settings(db)
    tiers = s_.get("referral_tiers") or growth.DEFAULT_TIERS
    paid = int(d.get("referral_paid_count") or 0)
    cur, nxt = growth.tier_for(tiers, paid)
    return {"paid": paid, "earned_days": int(d.get("referral_earned_days") or 0), "tier": cur, "next": nxt,
            "left": (nxt["min"] - paid) if nxt else 0, "tiers": tiers, "friend_days": s_.get("referral_days", 7)}


def run_growth_automations():
    def send(uid, text, lang):
        link = f"https://t.me/{_bot_username()}?start=offer" if _bot_username() else ""
        btn = {"inline_keyboard": [[{"text": "🎁 فتح العرض" if lang == "ar" else "🎁 Open offer", "web_app": {"url": WEBAPP_URL}}]]} if WEBAPP_URL else None
        tg("sendMessage", chat_id=uid, text=text, **({"reply_markup": btn} if btn else {}))
        return link

    def notify(uid, tar, ten, bar, ben):
        notifications.push(db, uid, "broadcast", tar, ten, bar, ben)

    return growth.run_automations(db, send, notify)


# ─── لوحة التحكم ───
@app.get("/api/admin/growth/funnel")
def admin_growth_funnel(campaign: str | None = None, admin_id: int = Depends(get_current_admin)):
    return growth.funnel(db, campaign)


@app.get("/api/admin/growth/coupons")
def admin_coupons(admin_id: int = Depends(get_current_admin)):
    return {"rows": [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(growth.COUPONS).stream()]}


@app.post("/api/admin/growth/coupons")
def admin_coupon_save(data: dict, admin_id: int = Depends(get_current_admin)):
    c = _growth_http(growth.clean_coupon, data)
    ref = db.collection(growth.COUPONS).document(c["code"])
    snap = ref.get()
    ref.set({**c, **({} if snap.exists else {"used_count": 0, "created_at": time.time(), "created_by": admin_id})}, merge=True)
    return {"id": c["code"], **(ref.get().to_dict() or {})}


@app.delete("/api/admin/growth/coupons/{code}")
def admin_coupon_delete(code: str, admin_id: int = Depends(get_current_admin)):
    db.collection(growth.COUPONS).document(code.upper()).delete()
    return {"ok": True}


def _gift_links(code: str) -> dict:
    bot = _bot_username()
    short = os.getenv("MINIAPP_SHORT_NAME", "")
    return {"bot_link": f"https://t.me/{bot}?start=gift_{code}" if bot else "",
            "app_link": f"https://t.me/{bot}/{short}?startapp=gift_{code}" if bot and short else ""}


@app.get("/api/admin/growth/gifts")
def admin_gifts(admin_id: int = Depends(get_current_admin)):
    return {"rows": [{"id": d.id, **(d.to_dict() or {}), **_gift_links(d.id)} for d in db.collection(growth.GIFTS).stream()]}


@app.post("/api/admin/growth/gifts")
def admin_gift_create(data: dict, admin_id: int = Depends(get_current_admin)):
    g = _growth_http(growth.clean_gift, data)
    code = str(data.get("code") or "").upper() or growth.new_gift_code()
    if not re.fullmatch(r"[A-Z0-9]{6,12}", code):
        raise HTTPException(422, "invalid_code")
    ref = db.collection(growth.GIFTS).document(code)
    snap = ref.get()
    ref.set({**g, **({} if snap.exists else {"claims": 0, "created_at": time.time(), "created_by": admin_id})}, merge=True)
    return {"id": code, **(ref.get().to_dict() or {}), **_gift_links(code)}


@app.delete("/api/admin/growth/gifts/{code}")
def admin_gift_delete(code: str, admin_id: int = Depends(get_current_admin)):
    db.collection(growth.GIFTS).document(code.upper()).delete()
    return {"ok": True}


@app.get("/api/admin/growth/campaigns")
def admin_campaigns(admin_id: int = Depends(get_current_admin)):
    bot = _bot_username()
    rows = []
    for d in db.collection(growth.CAMPAIGNS).stream():
        c = d.to_dict() or {}
        rows.append({"id": d.id, **c, "link": f"https://t.me/{bot}?start=c_{d.id}" if bot else "", "funnel": growth.funnel(db, d.id)})
    return {"rows": rows}


@app.post("/api/admin/growth/campaigns")
def admin_campaign_save(data: dict, admin_id: int = Depends(get_current_admin)):
    c = _growth_http(growth.clean_campaign, data)
    ref = db.collection(growth.CAMPAIGNS).document(c["slug"])
    snap = ref.get()
    ref.set({**c, **({} if snap.exists else {"clicks": 0, "created_at": time.time(), "created_by": admin_id})}, merge=True)
    return {"id": c["slug"], **(ref.get().to_dict() or {})}


@app.delete("/api/admin/growth/campaigns/{slug}")
def admin_campaign_delete(slug: str, admin_id: int = Depends(get_current_admin)):
    db.collection(growth.CAMPAIGNS).document(slug.lower()).delete()
    return {"ok": True}


@app.get("/api/admin/growth/automations")
def admin_automations(admin_id: int = Depends(get_current_admin)):
    log_rows = [d.to_dict() or {} for d in db.collection(growth.AUTO_LOG).order_by("at", direction="DESCENDING").limit(100).stream()]
    return {"rows": growth.list_automations(db), "triggers": growth.TRIGGER_LABEL, "log": log_rows}


@app.put("/api/admin/growth/automations/{rid}")
def admin_automation_save(rid: str, data: dict, admin_id: int = Depends(get_current_admin)):
    if not re.fullmatch(r"[a-z0-9_]{3,40}", rid):
        raise HTTPException(422, "invalid_id")
    a = _growth_http(growth.clean_automation, data)
    db.collection(growth.AUTOMATIONS).document(rid).set(a, merge=True)
    return {"id": rid, **a}


@app.delete("/api/admin/growth/automations/{rid}")
def admin_automation_delete(rid: str, admin_id: int = Depends(get_current_admin)):
    db.collection(growth.AUTOMATIONS).document(rid).delete()
    return {"ok": True}


@app.post("/api/admin/growth/automations/run")
def admin_automation_run(admin_id: int = Depends(get_current_admin)):
    return {"sent": run_growth_automations()}


# ─── باقة خاصة لمستخدم واحد ───
class PrivatePackage(BaseModel):
    uid: str = Field(pattern=r"^\d{1,15}$")
    name_ar: str = Field(min_length=2, max_length=60)
    name_en: str = Field(default="", max_length=60)
    price_usd: float = Field(gt=0, le=100000)
    duration_days: int = Field(ge=1, le=3650)
    price_stars: int | None = Field(default=None, ge=1, le=1000000)
    offer_hours: int = Field(default=72, ge=1, le=24 * 60)
    note_ar: str = Field(default="", max_length=300)
    note_en: str = Field(default="", max_length=300)
    via_bot: bool = True


@app.post("/api/admin/packages/private")
def admin_private_package(body: PrivatePackage, admin_id: int = Depends(get_current_admin)):
    if not user_ref(body.uid).get().exists:
        raise HTTPException(404, "user_not_found")
    now = time.time()
    ref = db.collection("packages").document()
    ref.set({"name_ar": body.name_ar, "name_en": body.name_en or body.name_ar, "price_usd": round(body.price_usd, 2),
             "duration_days": body.duration_days, "price_stars": body.price_stars, "active": True, "sort_order": 0, "featured": True,
             "tagline_ar": "باقة خاصة لك", "tagline_en": "Exclusively for you", "features_ar": [body.note_ar] if body.note_ar else [],
             "features_en": [body.note_en] if body.note_en else [], "private_uid": body.uid, "one_time": True, "used": False,
             "offer_expires_at": now + body.offer_hours * 3600, "created_by": admin_id, "created_at": now})
    title_ar, title_en = "🎁 باقة خاصة لك", "🎁 A package just for you"
    body_ar = f"{body.name_ar}: {body.duration_days} يوم بسعر ${body.price_usd:g} — صالحة {body.offer_hours} ساعة. {body.note_ar}".strip()
    body_en = f"{body.name_en or body.name_ar}: {body.duration_days} days for ${body.price_usd:g} — valid {body.offer_hours}h. {body.note_en}".strip()
    notifications.push(db, body.uid, "broadcast", title_ar, title_en, body_ar, body_en, ref.id)
    if body.via_bot:
        lang = ((user_ref(body.uid).get().to_dict() or {}).get("language")) or "ar"
        btn = {"inline_keyboard": [[{"text": "فتح الباقة" if lang == "ar" else "Open package", "web_app": {"url": WEBAPP_URL + "?view=plans"}}]]} if WEBAPP_URL else None
        tg("sendMessage", chat_id=body.uid, text=f"{title_ar if lang == 'ar' else title_en}\n\n{body_ar if lang == 'ar' else body_en}", **({"reply_markup": btn} if btn else {}))
    return {"id": ref.id}


# ─── تصدير البيانات (CSV يفتح في Excel) ───
def _csv_response(name: str, header: list, rows: list):
    import csv
    import io

    buf = io.StringIO()
    buf.write("﻿")  # BOM ليعرض Excel العربية بشكل صحيح
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow(["" if v is None else v for v in r])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}-{time.strftime("%Y%m%d")}.csv"'})


def _iso(ts):
    try:
        ts = ts.timestamp()
    except AttributeError:
        pass
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(float(ts))) if ts else ""


@app.get("/api/admin/export/{kind}")
def admin_export(kind: str, request: Request, admin_id: int = Depends(get_current_admin)):
    write_audit(admin_id, "EXPORT", f"/api/admin/export/{kind}", 200, {k.lower(): v for k, v in request.headers.items()},
                request.client.host if request.client else None, "")
    if kind == "users":
        rows = []
        for d in db.collection("users").stream():
            u = d.to_dict() or {}
            sub = u.get("subscription") or {}
            rows.append([d.id, u.get("nickname"), u.get("language"), u.get("status"), u.get("mt5_server"),
                         (u.get("live") or {}).get("balance"), (u.get("live") or {}).get("currency"), sub.get("package_name_en"),
                         _iso(sub.get("expires_at")), u.get("referred_by"), u.get("campaign"), _iso(u.get("first_seen")), _iso(u.get("last_seen"))])
        return _csv_response("users", ["telegram_id", "nickname", "language", "status", "mt5_server", "balance", "currency", "package",
                                       "expires_at_utc", "referred_by", "campaign", "first_seen_utc", "last_seen_utc"], rows)
    if kind == "payments":
        rows = [[d.id, p.get("uid"), p.get("method"), p.get("status"), p.get("package_id"), p.get("amount_usd"), p.get("amount_ton"),
                 p.get("amount_stars") or p.get("price_stars"), p.get("pay_currency"), _iso(p.get("created_at")), _iso(p.get("confirmed_at"))]
                for d in db.collection("payments").stream() for p in [d.to_dict() or {}]]
        return _csv_response("payments", ["order_id", "telegram_id", "method", "status", "package", "usd", "ton", "stars", "coin",
                                          "created_utc", "confirmed_utc"], rows)
    if kind == "tickets":
        rows = [[d.id, t.get("uid"), t.get("status"), t.get("priority"), t.get("channel"), t.get("lang"), t.get("subject"),
                 (t.get("csat") or {}).get("score") if isinstance(t.get("csat"), dict) else "", t.get("ai_attempts"),
                 _iso(t.get("created_at")), _iso(t.get("updated_at"))]
                for d in db.collection(support.TICKETS).stream() for t in [d.to_dict() or {}]]
        return _csv_response("tickets", ["ticket", "telegram_id", "status", "priority", "channel", "lang", "subject", "csat",
                                         "ai_replies", "created_utc", "updated_utc"], rows)
    raise HTTPException(404, "unknown_export")
