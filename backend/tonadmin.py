"""
AW TON Admin — التحكم بمحفظة TON من لوحة التحكم مع تحقق OTP عبر بوت تلجرام لكل عملية حساسة.

العرض (بلا OTP): الرصيد، سعر TON، آخر التحويلات الواردة ومطابقتها بالطلبات، الإعدادات الحالية.
العمليات الحساسة (OTP إلزامي، صالح 5 دقائق، 5 محاولات، استخدام واحد، مربوط بالأدمن وبالمعاملات نفسها):
  set_wallet   تغيير/ربط محفظة استلام جديدة (يُحفظ في config/ton ويُطبق فورًا)
  set_window   مهلة انتظار دفعة TON قبل اعتبارها منتهية
  toggle       تشغيل/إيقاف الدفع بـ TON
  transfer     تحويل/سحب: الخادم لا يحتفظ بالمفتاح الخاص إطلاقًا؛ بعد التحقق يُصدر طلب تحويل
               يوقّعه الأدمن من محفظته عبر TON Connect داخل اللوحة، ويُسجَّل الناتج.
كل محاولة (طلب رمز، رمز خاطئ، تنفيذ، نتيجة تحويل) تُسجَّل في ton_admin_log بالوقت وهوية المنفّذ.
"""
import hashlib
import hmac
import os
import re
import secrets
import time

import httpx

import ton
from retry import raise_for_retryable, with_backoff

CONFIG_DOC = ("config", "ton")
OTPS = "admin_otp"
LOG = "ton_admin_log"
ACTIONS = ("set_wallet", "set_window", "toggle", "transfer")
ACTION_LABEL = {"set_wallet": "تغيير محفظة الاستلام", "set_window": "تعديل مهلة الدفع", "toggle": "تشغيل/إيقاف الدفع بـ TON",
                "transfer": "تحويل TON"}
OTP_TTL = 300
OTP_ATTEMPTS = 5
ADDR_RE = r"(?:[EUk0]Q[A-Za-z0-9_-]{46}|-?\d:[0-9a-fA-F]{64})"


def load_override(db):
    """يطبّق إعدادات المحفظة المحفوظة من اللوحة (تتقدم على .env)."""
    snap = db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1]).get()
    cfg = (snap.to_dict() or {}) if snap.exists else {}
    if cfg.get("wallet"):
        ton.TON_WALLET = cfg["wallet"]
    if cfg.get("window_sec"):
        ton.TON_PAYMENT_WINDOW = int(cfg["window_sec"])
    return cfg


def log(db, admin_id, event: str, action: str, ok: bool, detail: dict | None = None):
    db.collection(LOG).document().set({"at": time.time(), "admin_id": admin_id, "event": event, "action": action,
                                       "label": ACTION_LABEL.get(action, action), "ok": ok, "detail": detail or {}})


@with_backoff(attempts=2)
def _balance_call() -> dict:
    headers = {"X-API-Key": ton.TONCENTER_KEY} if ton.TONCENTER_KEY else {}
    return raise_for_retryable(httpx.get(f"{ton.TONCENTER_API}/getAddressBalance", params={"address": ton.TON_WALLET},
                                         headers=headers, timeout=15)).json()


def balance_nano() -> int | None:
    if not ton.configured():
        return None
    try:
        data = _balance_call()
        return int(data.get("result")) if data.get("ok") else None
    except Exception:  # noqa: BLE001
        return None


def overview(db) -> dict:
    cfg = load_override(db)
    nano = balance_nano()
    rate = ton.usd_rate() if ton.configured() else None
    incoming, error = [], None
    if ton.configured():
        try:
            txs = ton.fetch_transactions(30)
            orders = {tx["comment"] for tx in txs if tx["comment"]}
            known = {oid for oid in orders if db.collection("payments").document(oid).get().exists}
            incoming = [{**tx, "ton": round(tx["value"] / ton.NANO, 4), "order": tx["comment"] if tx["comment"] in known else None}
                        for tx in txs[:30]]
        except ton.TonError as e:
            error = str(e)
    import billing

    return {
        "configured": ton.configured(), "wallet": ton.TON_WALLET, "source": "admin" if cfg.get("wallet") else "env",
        "balance_ton": None if nano is None else round(nano / ton.NANO, 4),
        "balance_usd": None if nano is None or not rate else round(nano / ton.NANO * rate, 2),
        "rate_usd": rate, "window_sec": ton.TON_PAYMENT_WINDOW,
        "enabled": bool(billing.get_settings(db).get("pay_ton_enabled", True)),
        "incoming": incoming, "error": error, "updated_by": cfg.get("updated_by"), "updated_at": cfg.get("updated_at"),
    }


def validate(action: str, params: dict) -> dict:
    if action not in ACTIONS:
        raise ValueError("unknown action")
    if action == "set_wallet":
        addr = str(params.get("address") or "").strip()
        if not re.fullmatch(ADDR_RE, addr):
            raise ValueError("invalid TON address")
        return {"address": addr}
    if action == "set_window":
        sec = int(params.get("seconds") or 0)
        if not 600 <= sec <= 86400:
            raise ValueError("window must be 600..86400 seconds")
        return {"seconds": sec}
    if action == "toggle":
        return {"enabled": bool(params.get("enabled"))}
    to = str(params.get("to") or "").strip()
    amount = float(params.get("amount_ton") or 0)
    if not re.fullmatch(ADDR_RE, to):
        raise ValueError("invalid destination address")
    if not 0 < amount <= 100000:
        raise ValueError("invalid amount")
    comment = str(params.get("comment") or "")[:100]
    if len(comment.encode()) > 120:
        raise ValueError("comment too long")
    return {"to": to, "amount_ton": round(amount, 4), "comment": comment}


def _digest(otp_id: str, code: str) -> str:
    return hmac.new(otp_id.encode(), code.encode(), hashlib.sha256).hexdigest()


def _params_hash(action: str, params: dict) -> str:
    return hashlib.sha256(repr((action, sorted(params.items()))).encode()).hexdigest()


def request_otp(db, admin_id, action: str, params: dict, send) -> dict:
    """ينشئ رمزًا ويرسله للأدمن عبر البوت. send(chat_id, text) -> ok."""
    params = validate(action, params)
    otp_id = secrets.token_urlsafe(12)
    code = f"{secrets.randbelow(900000) + 100000}"
    db.collection(OTPS).document(otp_id).set({
        "admin_id": admin_id, "action": action, "params": params, "params_hash": _params_hash(action, params),
        "code": _digest(otp_id, code), "expires": time.time() + OTP_TTL, "attempts": 0, "used": False, "at": time.time()})
    detail = ", ".join(f"{k}: {v}" for k, v in params.items())
    sent = send(admin_id, f"🔐 رمز تأكيد عملية حساسة في لوحة التحكم\n\nالعملية: {ACTION_LABEL[action]}\n{detail}\n\nالرمز: {code}\nصالح 5 دقائق. إن لم تطلب هذه العملية فتجاهل الرسالة وغيّر صلاحيات الفريق.")
    log(db, admin_id, "otp_requested", action, bool(sent), {"params": params})
    return {"otp_id": otp_id, "expires_in": OTP_TTL, "sent": bool(sent)}


def verify_otp(db, admin_id, otp_id: str, code: str) -> dict:
    ref = db.collection(OTPS).document(str(otp_id))
    snap = ref.get()
    row = snap.to_dict() if snap.exists else None
    if not row or row["admin_id"] != admin_id:
        log(db, admin_id, "otp_invalid", (row or {}).get("action", "?"), False)
        raise PermissionError("otp_invalid")
    if row["used"] or time.time() > row["expires"] or row["attempts"] >= OTP_ATTEMPTS:
        log(db, admin_id, "otp_expired", row["action"], False)
        raise PermissionError("otp_expired")
    if not hmac.compare_digest(row["code"], _digest(otp_id, str(code).strip())):
        ref.set({"attempts": row["attempts"] + 1}, merge=True)
        log(db, admin_id, "otp_wrong", row["action"], False, {"attempt": row["attempts"] + 1})
        raise PermissionError("otp_wrong")
    ref.set({"used": True, "used_at": time.time()}, merge=True)
    return row


def execute(db, admin_id, otp_id: str, code: str) -> dict:
    row = verify_otp(db, admin_id, otp_id, code)
    action, params = row["action"], row["params"]
    if _params_hash(action, params) != row["params_hash"]:
        raise PermissionError("otp_invalid")
    now = time.time()
    cfg_ref = db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1])
    result: dict = {"ok": True, "action": action}
    if action == "set_wallet":
        old = ton.TON_WALLET
        cfg_ref.set({"wallet": params["address"], "updated_by": admin_id, "updated_at": now}, merge=True)
        ton.TON_WALLET = params["address"]
        result["previous"] = old
    elif action == "set_window":
        cfg_ref.set({"window_sec": params["seconds"], "updated_by": admin_id, "updated_at": now}, merge=True)
        ton.TON_PAYMENT_WINDOW = params["seconds"]
    elif action == "toggle":
        import billing

        billing.update_settings(db, {"pay_ton_enabled": params["enabled"]})
    elif action == "transfer":
        msg = {"address": params["to"], "amount": str(ton.to_nano(params["amount_ton"]))}
        if params.get("comment"):
            msg["payload"] = ton.comment_payload(params["comment"])
        result["transaction"] = {"validUntil": int(now) + 300, "messages": [msg]}
        result["from_wallet"] = ton.TON_WALLET
    log(db, admin_id, "executed", action, True, {"params": params, **({"previous": result.get("previous")} if "previous" in result else {})})
    return result


def transfer_result(db, admin_id, otp_id: str, ok: bool, boc: str = "", error: str = ""):
    row = (db.collection(OTPS).document(str(otp_id)).get().to_dict() or {})
    if row.get("admin_id") != admin_id or row.get("action") != "transfer" or not row.get("used"):
        raise PermissionError("otp_invalid")
    log(db, admin_id, "transfer_signed" if ok else "transfer_failed", "transfer", ok,
        {"params": row.get("params"), "boc": boc[:600], "error": error[:300]})


def history(db, limit: int = 100) -> list:
    return [{"id": d.id, **(d.to_dict() or {})} for d in db.collection(LOG).order_by("at", direction="DESCENDING").limit(limit).stream()]


OTP_BOT_TOKEN = os.getenv("ADMIN_OTP_BOT_TOKEN", "")  # بوت تحقق مستقل للأدمن (اختياري؛ الافتراضي البوت الرئيسي)
