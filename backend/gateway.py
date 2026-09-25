"""
AW Pay — بوابة الدفع الخاصة بالمشروع (بديل NOWPayments، بلا وسيط).

الشبكات والعملات:
  • TRON: USDT (TRC20) و TRX       — عنوان إيداع خاص لكل مستخدم يُشتق من المفتاح الرئيسي.
  • BSC : USDT (BEP20) و BNB       — نفس الفكرة (عنوان إيداع لكل مستخدم).
  • TON : TON و USDT على TON       — الدفع مباشرة لعنوانك مع تعليق (memo) فريد لكل فاتورة، فلا تجميع ولا رسوم.

دورة الفاتورة:
  waiting → (partially_paid) → finished        أو expired → (قبول متأخر خلال late_accept_hours) → finished / underpaid
  • التحقق ديناميكي من الشبكة مباشرة وبأرصدة مؤكَّدة فقط (لا يُصدَّق أي شيء من الواجهة).
  • هامش قبول (tolerance_pct) لفروقات التقريب، والدفع الناقص يطلب من المستخدم المبلغ المتبقي على نفس العنوان.
  • الدفع الزائد يُقبل ويُسجَّل ويُنبَّه الأدمن.

التجميع (Sweep) لـ TRON و BSC:
  عند وصول رصيد عنوان إيداع إلى الحد الأدنى (sweep_min_usd) ولا توجد فاتورة مفتوحة عليه: إن لم يكفِ رصيد الغاز
  يُموَّل من «خزان الغاز» (محفظة مشتقة لكل شبكة) ثم يُحوَّل الرصيد إلى عنوان الاستلام الذي اخترته. كل خطوة تنتظر
  تأكيد الشبكة قبل التالية، وكل عملية تُسجَّل في gw_sweeps.

الأمان:
  • GATEWAY_MASTER_KEY في .env فقط (hex ≥ 32 بايت). لا مفاتيح خاصة في قاعدة البيانات، ولا في لوحة التحكم.
  • عناوين الاستلام لا تتغير إلا برمز OTP (tonadmin: gw_payout).
"""
import math
import os
import secrets
import time

import chain_crypto as cc
import gw_chains as ch

CONFIG_DOC = ("config", "gateway")
ADDRS = "gw_addresses"
SWEEPS = "gw_sweeps"
OPEN = ("waiting", "partially_paid", "expired")

ASSETS = {
    "usdttrc20": {"symbol": "USDT", "network": "tron", "label": "TRON (TRC20)", "kind": "token", "contract": ch.USDT_TRC20, "decimals": 6, "stable": True},
    "trx": {"symbol": "TRX", "network": "tron", "label": "TRON", "kind": "native", "decimals": 6, "rate": "trx", "precision": 2},
    "usdtbsc": {"symbol": "USDT", "network": "bsc", "label": "BNB Smart Chain (BEP20)", "kind": "token", "contract": ch.USDT_BEP20, "decimals": 18, "stable": True},
    "bnbbsc": {"symbol": "BNB", "network": "bsc", "label": "BNB Smart Chain (BEP20)", "kind": "native", "decimals": 18, "rate": "bnb", "precision": 5},
    "ton": {"symbol": "TON", "network": "ton", "label": "TON", "kind": "native", "decimals": 9, "rate": "ton", "precision": 2},
    "usdtton": {"symbol": "USDT", "network": "ton", "label": "TON", "kind": "jetton", "contract": ch.USDT_TON_MASTER, "decimals": 6, "stable": True},
}
NETWORKS = ("tron", "bsc", "ton")
NATIVE = {"tron": "trx", "bsc": "bnbbsc", "ton": "ton"}

DEFAULT = {
    "enabled": False,               # تشغيل البوابة الخاصة بدل NOWPayments
    "assets": {k: True for k in ASSETS},
    "payout": {"tron": "", "bsc": "", "ton": ""},  # يتغير برمز OTP فقط
    "window_min": 60,               # مهلة الدفع
    "partial_grace_min": 120,       # تمديد المهلة عند وصول دفعة ناقصة
    "late_accept_hours": 48,        # قبول الدفعات المتأخرة بعد انتهاء المهلة
    "tolerance_pct": 1.0,           # قبول نقص حتى هذه النسبة
    "auto_sweep": True,
    "sweep_min_usd": {"tron": 30, "bsc": 5},
    "bsc_confirmations": 12,
    "tron_fee_limit_trx": 60,
    "gas_alert": {"tron": 50, "bsc": 0.01},  # تنبيه عند انخفاض خزان الغاز (TRX / BNB)
}


class GatewayError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


# ───────────────────────── الإعدادات والمفاتيح ─────────────────────────
def master() -> bytes | None:
    raw = os.getenv("GATEWAY_MASTER_KEY", "").strip()
    try:
        b = bytes.fromhex(raw)
    except ValueError:
        return None
    return b if len(b) >= 32 else None


def get_config(db) -> dict:
    snap = db.collection(CONFIG_DOC[0]).document(CONFIG_DOC[1]).get()
    saved = (snap.to_dict() or {}) if snap.exists else {}
    cfg = {**DEFAULT, **saved}
    for k in ("assets", "payout", "sweep_min_usd", "gas_alert"):
        cfg[k] = {**DEFAULT[k], **(saved.get(k) or {})}
    if not cfg["payout"].get("ton"):
        import ton  # عنوان محفظة TON الحالية افتراضيًا

        cfg["payout"]["ton"] = ton.TON_WALLET or ""
    return cfg


def clean_config(patch: dict) -> dict:
    """كل الإعدادات عدا عناوين الاستلام (تلك برمز OTP فقط)."""
    out = {}
    if "enabled" in patch:
        out["enabled"] = bool(patch["enabled"])
    if "auto_sweep" in patch:
        out["auto_sweep"] = bool(patch["auto_sweep"])
    if "assets" in patch:
        out["assets"] = {k: bool((patch["assets"] or {}).get(k, True)) for k in ASSETS}
    lims = {"window_min": (10, 1440), "partial_grace_min": (10, 2880), "late_accept_hours": (0, 720),
            "bsc_confirmations": (3, 60), "tron_fee_limit_trx": (10, 300)}
    for k, (lo, hi) in lims.items():
        if k in patch:
            out[k] = max(lo, min(hi, int(patch[k])))
    if "tolerance_pct" in patch:
        out["tolerance_pct"] = max(0.0, min(5.0, float(patch["tolerance_pct"])))
    for k, lim in (("sweep_min_usd", 100000.0), ("gas_alert", 100000.0)):
        if k in patch:
            out[k] = {n: max(0.0, min(lim, float((patch[k] or {}).get(n, DEFAULT[k][n])))) for n in DEFAULT[k]}
    return out


def valid_payout(network: str, addr: str) -> bool:
    import tonadmin

    import re

    if network == "tron":
        return cc.is_tron_address(addr)
    if network == "bsc":
        return cc.is_eth_address(addr)
    if network == "ton":
        return bool(re.fullmatch(tonadmin.ADDR_RE, str(addr or "")))
    return False


def network_ready(cfg: dict, network: str) -> bool:
    if not cfg["payout"].get(network):
        return False
    return network == "ton" or master() is not None


def active(cfg: dict) -> bool:
    return bool(cfg.get("enabled")) and any(network_ready(cfg, n) for n in NETWORKS)


def currencies(cfg: dict) -> list:
    return [{"code": k, "symbol": a["symbol"], "network": a["label"]} for k, a in ASSETS.items()
            if cfg["assets"].get(k) and network_ready(cfg, a["network"])]


def _priv(network: str, purpose: str, ident) -> bytes:
    m = master()
    if not m:
        raise GatewayError("gateway_not_configured", 503)
    return cc.derive_private_key(m, f"{network}/{purpose}/{ident}")


def address_of(network: str, priv: bytes) -> str:
    return cc.tron_address(priv) if network == "tron" else cc.eth_address(priv)


def deposit_key(network: str, uid) -> bytes:
    return _priv(network, "deposit", uid)


def gas_key(network: str) -> bytes:
    return _priv(network, "gas", 0)


def deposit_address(db, network: str, uid) -> dict:
    ref = db.collection(ADDRS).document(f"{network}-{uid}")
    snap = ref.get()
    if snap.exists:
        return {"id": ref.id, **snap.to_dict()}
    row = {"network": network, "uid": str(uid), "address": address_of(network, deposit_key(network, uid)),
           "created_at": time.time(), "op": None, "open_order": None, "dirty": False}
    ref.set(row)
    return {"id": ref.id, **row}


# ───────────────────────── الأرصدة ─────────────────────────
def balance(cfg: dict, asset: str, address: str) -> int:
    a = ASSETS[asset]
    if a["network"] == "tron":
        return ch.tron_trc20_balance(a["contract"], address) if a["kind"] == "token" else ch.tron_trx_balance(address)
    if a["network"] == "bsc":
        c = int(cfg.get("bsc_confirmations") or 12)
        return ch.bsc_token_balance(a["contract"], address, c) if a["kind"] == "token" else ch.bsc_native_balance(address, c)
    raise GatewayError("unsupported")


def to_units(asset: str, amount: float) -> int:
    return int(round(float(amount) * 10 ** ASSETS[asset]["decimals"]))


def from_units(asset: str, units: int) -> float:
    return int(units or 0) / 10 ** ASSETS[asset]["decimals"]


def fmt_units(asset: str, units: int) -> str:
    a = ASSETS[asset]
    v = from_units(asset, units)
    places = 2 if a.get("stable") else a.get("precision", 4)
    s = f"{v:.{places}f}".rstrip("0").rstrip(".")
    return s or "0"


def quote(asset: str, amount_usd: float) -> tuple[int, str]:
    """المبلغ المطلوب بوحدات العملة: USDT = الدولار نفسه (12 لا 12.000850)، وغيرها بسعر السوق الحالي مقرّبًا لأعلى."""
    a = ASSETS[asset]
    if a.get("stable"):
        units = to_units(asset, amount_usd)
    else:
        rate = ch.usd_rates().get(a["rate"])
        if not rate:
            raise GatewayError("rate_unavailable", 503)
        p = a["precision"]
        amt = math.ceil(amount_usd / rate * 10 ** p) / 10 ** p
        units = to_units(asset, amt)
    return units, fmt_units(asset, units)


def usd_value(asset: str, units: int) -> float:
    a = ASSETS[asset]
    if a.get("stable"):
        return from_units(asset, units)
    return from_units(asset, units) * float(ch.usd_rates().get(a["rate"]) or 0)


# ───────────────────────── الفواتير ─────────────────────────
def _memo() -> str:
    return "AW" + "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(7))


def create_invoice(db, uid, asset: str, amount_usd: float, order_id: str, base: dict, now: float | None = None) -> dict:
    """ينشئ فاتورة ويعيد ما تعرضه شاشة الدفع. base: حقول الطلب (package_id، المكافأة…)."""
    now = time.time() if now is None else now
    cfg = get_config(db)
    a = ASSETS.get(asset)
    if not a or not cfg["assets"].get(asset) or not active(cfg) or not network_ready(cfg, a["network"]):
        raise GatewayError("unsupported_currency")
    net = a["network"]
    doc = {**base, "uid": uid, "method": "gateway", "asset": asset, "network": net, "amount_usd": amount_usd,
           "status": "waiting", "created_at": now, "expires_at": now + cfg["window_min"] * 60, "received_units": 0}
    if net == "ton":
        doc.update(address=cfg["payout"]["ton"], memo=_memo())
    else:
        addr = deposit_address(db, net, uid)
        if addr.get("op"):
            raise GatewayError("gateway_busy_retry", 409)
        prev_id = addr.get("open_order")
        if prev_id:
            prev_ref = db.collection("payments").document(prev_id)
            prev = (prev_ref.get().to_dict() or {})
            if prev.get("status") in OPEN and int(prev.get("received_units") or 0) > 0 and prev.get("asset") == asset:
                return public_invoice(prev_id, prev)  # دفعة ناقصة قائمة: يكمل المتبقي على نفس الفاتورة
            if prev.get("status") in OPEN:
                prev_ref.set({"status": "replaced", "replaced_by": order_id}, merge=True)
        aref = db.collection(ADDRS).document(addr["id"])
        aref.set({"open_order": order_id}, merge=True)  # نحجز العنوان أولًا ثم نتأكد أن لا تجميع بدأ بالتوازي
        if (aref.get().to_dict() or {}).get("op"):
            aref.set({"open_order": None}, merge=True)
            raise GatewayError("gateway_busy_retry", 409)
        doc.update(address=addr["address"], baseline_units=balance(cfg, asset, addr["address"]))
    units, text = quote(asset, amount_usd)
    doc.update(amount_units=units, amount_text=text)
    db.collection("payments").document(order_id).set(doc)
    return public_invoice(order_id, doc)


def public_invoice(order_id: str, p: dict) -> dict:
    a = ASSETS[p["asset"]]
    need, got = int(p["amount_units"]), int(p.get("received_units") or 0)
    link = None
    if a["network"] == "ton":
        link = (f"ton://transfer/{p['address']}?amount={need - got if got else need}&text={p['memo']}" if a["kind"] == "native"
                else f"ton://transfer/{p['address']}?jetton={a['contract']}&amount={need - got if got else need}&text={p['memo']}")
    return {
        "order_id": order_id, "amount_usd": p.get("amount_usd"), "provider": "aw",
        "pay_address": p["address"], "pay_amount": p["amount_text"], "display_amount": p["amount_text"],
        "pay_currency": p["asset"], "symbol": a["symbol"], "network": a["label"], "payin_extra_id": p.get("memo"),
        "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p["expires_at"])),
        "status": p.get("status"), "received": fmt_units(p["asset"], got), "remaining": fmt_units(p["asset"], max(0, need - got)),
        "wallet_link": link,
    }


_TON_CACHE: dict = {}  # قائمة التحويلات لكل عنوان لـ 10 ثوانٍ: كثرة المستخدمين لا تتجاوز حد toncenter


def _ton_received(cfg: dict, p: dict, cache: dict) -> tuple[int, list]:
    a = ASSETS[p["asset"]]
    key = (p["asset"], p["address"])
    if key not in cache:
        hit = _TON_CACHE.get(key)
        if hit and time.time() - hit[0] < 10:
            cache[key] = hit[1]
        else:
            cache[key] = (ch.ton_incoming(p["address"]) if a["kind"] == "native"
                          else ch.ton_jetton_incoming(p["address"], a["contract"]))
            _TON_CACHE[key] = (time.time(), cache[key])
    memo = str(p.get("memo") or "").upper()
    txs = [t for t in cache[key] if t["comment"].replace(" ", "").upper() == memo and t["utime"] >= p["created_at"] - 600]
    return sum(t["amount"] for t in txs), [t["hash"] for t in txs]


def check_invoice(db, order_id: str, hooks: dict, now: float | None = None, cache: dict | None = None) -> dict:
    """يتحقق من الشبكة ويحدّث الفاتورة. hooks: paid(order_id, extra), user(uid, ar, en), admin(text)."""
    now = time.time() if now is None else now
    cache = {} if cache is None else cache
    ref = db.collection("payments").document(order_id)
    snap = ref.get()
    p = snap.to_dict() if snap.exists else None
    if not p or p.get("method") != "gateway" or p.get("status") not in OPEN:
        return public_invoice(order_id, p) if p and p.get("method") == "gateway" else {"status": (p or {}).get("status")}
    cfg = get_config(db)
    if p["network"] == "ton":
        got, hashes = _ton_received(cfg, p, cache)
    else:
        got, hashes = max(0, balance(cfg, p["asset"], p["address"]) - int(p.get("baseline_units") or 0)), []
    need = int(p["amount_units"])
    tol = float(cfg.get("tolerance_pct") or 0)
    upd = {"received_units": got, "checked_at": now, **({"tx_hashes": hashes} if hashes else {})}
    sym = ASSETS[p["asset"]]["symbol"]
    if got >= need * (1 - tol / 100):
        upd["overpaid_units"] = max(0, got - need)
        ref.set(upd, merge=True)
        extra = {"gw_received": fmt_units(p["asset"], got), "gw_asset": p["asset"],
                 **({"accepted_partial": True} if got < need else {}), **({"late": True} if now > p["expires_at"] else {})}
        _close_address(db, p, order_id, dirty=True)
        hooks["paid"](order_id, extra)
        if got > need * 1.02:
            hooks["admin"](f"💰 دفعة زائدة على البوابة\nالطلب: {order_id}\nالمطلوب: {p['amount_text']} {sym}\nالمستلم: {fmt_units(p['asset'], got)} {sym}")
        p = {**p, **upd, "status": "finished"}
        return public_invoice(order_id, p)
    if got > 0 and p["status"] != "partially_paid":
        upd["status"] = "partially_paid"
        upd["expires_at"] = max(p["expires_at"], now + cfg["partial_grace_min"] * 60)
        rem = fmt_units(p["asset"], need - got)
        hooks["user"](p["uid"],
                      f"⚠️ وصلتنا دفعة ناقصة: {fmt_units(p['asset'], got)} من {p['amount_text']} {sym}.\nأرسل المتبقي {rem} {sym} إلى نفس العنوان"
                      f"{' مع نفس التعليق ' + p['memo'] if p.get('memo') else ''} ليُفعَّل اشتراكك تلقائيًا.",
                      f"⚠️ We received a partial payment: {fmt_units(p['asset'], got)} of {p['amount_text']} {sym}.\nSend the remaining {rem} {sym} to the same address"
                      f"{' with the same comment ' + p['memo'] if p.get('memo') else ''} and your subscription activates automatically.")
        hooks["admin"](f"⚠️ دفعة ناقصة على البوابة\nالطلب: {order_id}\nالمستخدم: {p['uid']}\nوصل {fmt_units(p['asset'], got)} من {p['amount_text']} {sym}")
    elif now > p["expires_at"] and p["status"] == "waiting":
        upd["status"] = "expired"
    elif p["status"] == "partially_paid" and now > p["expires_at"]:
        upd["status"] = "expired"
    late_end = p["expires_at"] + cfg["late_accept_hours"] * 3600
    if now > late_end:
        upd["status"] = "underpaid" if got > 0 else "closed"
        _close_address(db, p, order_id, dirty=got > 0)
        if got > 0:
            hooks["admin"](f"🔴 فاتورة أُغلقت بدفع ناقص (تحتاج قرارك من «بوابة الدفع»)\nالطلب: {order_id}\nوصل {fmt_units(p['asset'], got)} من {p['amount_text']} {sym}")
    ref.set(upd, merge=True)
    return public_invoice(order_id, {**p, **upd})


def _close_address(db, p: dict, order_id: str, dirty: bool):
    if p.get("network") in ("tron", "bsc"):
        ref = db.collection(ADDRS).document(f"{p['network']}-{p['uid']}")
        snap = ref.get()
        if snap.exists and (snap.to_dict() or {}).get("open_order") == order_id:
            ref.set({"open_order": None, **({"dirty": True} if dirty else {})}, merge=True)


def tick(db, hooks: dict, now: float | None = None) -> int:
    """كل الفواتير المفتوحة (مع نافذة القبول المتأخر). طلب واحد لكل عنوان TON في الدورة."""
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    cache: dict = {}
    n = 0
    for d in db.collection("payments").where(filter=FieldFilter("method", "==", "gateway")).stream():
        p = d.to_dict() or {}
        if p.get("status") not in OPEN:
            continue
        try:
            check_invoice(db, d.id, hooks, now, cache)
            n += 1
        except Exception as e:  # noqa: BLE001 — فاتورة لا توقف البقية
            db.collection("payments").document(d.id).set({"check_error": f"{type(e).__name__}: {e}"[:200]}, merge=True)
    return n


def accept_invoice(db, order_id: str, admin_id, hooks: dict, note: str = "") -> dict:
    """قبول يدوي من الأدمن (دفعة ناقصة/تحويل بلا تعليق)."""
    ref = db.collection("payments").document(order_id)
    p = (ref.get().to_dict() or {})
    if p.get("method") != "gateway":
        raise GatewayError("not_found", 404)
    if p.get("status") == "finished":
        raise GatewayError("already_finished", 409)
    ref.set({"manual_accept": {"by": admin_id, "at": time.time(), "note": str(note)[:200]}}, merge=True)
    _close_address(db, p, order_id, dirty=True)
    hooks["paid"](order_id, {"manual_accept": True})
    return {"ok": True}


def cancel_invoice(db, order_id: str, admin_id) -> dict:
    ref = db.collection("payments").document(order_id)
    p = (ref.get().to_dict() or {})
    if p.get("method") != "gateway" or p.get("status") == "finished":
        raise GatewayError("not_cancellable", 409)
    ref.set({"status": "cancelled", "cancelled_by": admin_id, "cancelled_at": time.time()}, merge=True)
    _close_address(db, p, order_id, dirty=int(p.get("received_units") or 0) > 0)
    return {"ok": True}


# ───────────────────────── التجميع إلى عنوان الاستلام ─────────────────────────
def _net_assets(network: str) -> list:
    return [k for k, a in ASSETS.items() if a["network"] == network]


def _send(cfg, network: str, priv: bytes, asset: str, to: str, units: int) -> str:
    a = ASSETS[asset]
    if network == "tron":
        if a["kind"] == "token":
            return ch.tron_send_trc20(priv, a["contract"], to, units, int(cfg["tron_fee_limit_trx"]) * 1_000_000)
        return ch.tron_send_trx(priv, to, units)
    gp = ch.bsc_gas_price()
    if a["kind"] == "token":
        return ch.bsc_send_token(priv, a["contract"], to, units, gp)
    return ch.bsc_send_native(priv, to, units, gp)


def _tx_status(network: str, tx: str) -> str:
    return ch.tron_tx_status(tx) if network == "tron" else ch.bsc_tx_status(tx)


def _token_fee(cfg, network: str, addr: str, asset: str, units: int) -> int:
    """كلفة تحويل التوكن بعملة الشبكة (sun / wei)."""
    if network == "tron":
        try:
            return ch.tron_trc20_fee_sun(addr, ASSETS[asset]["contract"], cfg["payout"]["tron"], units)
        except ch.ChainError:  # عنوان غير مفعّل بعد على الشبكة: تقدير محافظ
            return 35_000_000
    return int(ch.bsc_gas_price() * ch.BSC_TOKEN_GAS * 1.2)


def _native_reserve(network: str) -> int:
    return 1_100_000 if network == "tron" else int(ch.bsc_gas_price() * 21000 * 1.1)


def sweep_address(db, network: str, uid, hooks: dict, force: bool = False, now: float | None = None) -> dict:
    """خطوة واحدة من آلة الحالة للتجميع. يُستدعى دوريًا؛ force يتجاهل الحد الأدنى (زر «تجميع الآن»)."""
    now = time.time() if now is None else now
    cfg = get_config(db)
    to = cfg["payout"].get(network)
    if not to:
        return {"state": "no_payout"}
    ref = db.collection(ADDRS).document(f"{network}-{uid}")
    row = ref.get().to_dict() or {}
    if not row:
        return {"state": "unknown"}
    if row.get("open_order"):
        return {"state": "open_invoice"}
    addr, priv = row["address"], deposit_key(network, uid)
    op = row.get("op")
    if op and op.get("stage") == "claim":  # حجز لم يكتمل (خطأ أثناء الإرسال)
        if now - op["at"] < 120:
            return {"state": "claim"}
        ref.set({"op": None}, merge=True)
        op = None
    if op:  # متابعة عملية جارية
        st = _tx_status(network, op["tx"])
        if st == "pending":
            if now - op["at"] > 900:
                ref.set({"op": None}, merge=True)
                hooks["admin"](f"⏱️ عملية تجميع لم تتأكد خلال 15 دقيقة ({network} · {addr}) — أُعيدت للمحاولة لاحقًا.\nTX: {op['tx']}")
            return {"state": op["stage"]}
        if st == "failed":
            ref.set({"op": None}, merge=True)
            hooks["admin"](f"❌ فشلت عملية {'تمويل الغاز' if op['stage'] == 'funding' else 'تجميع'} ({network} · {addr})\nTX: {op['tx']}")
            return {"state": "failed"}
        if op["stage"] == "funding":  # الغاز وصل → نحوّل التوكن
            units = balance(cfg, op["asset"], addr)
            tx = _send(cfg, network, priv, op["asset"], to, units)
            ref.set({"op": {**op, "stage": "sweeping", "tx": tx, "at": now, "units": units}}, merge=True)
            return {"state": "sweeping", "tx": tx}
        db.collection(SWEEPS).document().set({"network": network, "uid": str(uid), "address": addr, "to": to, "asset": op["asset"],
                                              "units": op.get("units"), "amount": fmt_units(op["asset"], op.get("units") or 0),
                                              "tx": op["tx"], "at": now, "gas_tx": op.get("gas_tx")})
        ref.set({"op": None, "last_sweep_at": now}, merge=True)
        return {"state": "done", "tx": op["tx"]}

    min_usd = 0.0 if force else float(cfg["sweep_min_usd"].get(network) or 0)
    ref.set({"op": {"stage": "claim", "at": now}}, merge=True)  # نحجز العنوان ثم نتأكد أن لا فاتورة فُتحت بالتوازي
    if (ref.get().to_dict() or {}).get("open_order"):
        ref.set({"op": None}, merge=True)
        return {"state": "open_invoice"}
    try:
        res = _sweep_start(db, cfg, ref, network, addr, priv, to, min_usd, force, now)
    except Exception:
        ref.set({"op": None}, merge=True)
        raise
    if res["state"] == "idle":
        ref.set({"op": None, "dirty": False}, merge=True)
    return res


def _sweep_start(db, cfg, ref, network, addr, priv, to, min_usd, force, now) -> dict:
    bals = {k: balance(cfg, k, addr) for k in _net_assets(network)}
    ref.set({"balances": {k: fmt_units(k, v) for k, v in bals.items()}, "balances_at": now}, merge=True)
    native = NATIVE[network]
    for asset in _net_assets(network):
        if ASSETS[asset]["kind"] != "token" or bals[asset] <= 0 or usd_value(asset, bals[asset]) < max(min_usd, 0.01):
            continue
        fee = _token_fee(cfg, network, addr, asset, bals[asset])
        if bals[native] < fee:  # تمويل الغاز من الخزان
            gas_priv = gas_key(network)
            need = fee - bals[native] + (1_000_000 if network == "tron" else 0)
            gtx = _send(cfg, network, gas_priv, native, addr, need)
            ref.set({"op": {"stage": "funding", "asset": asset, "tx": gtx, "gas_tx": gtx, "at": now}}, merge=True)
            return {"state": "funding", "tx": gtx}
        tx = _send(cfg, network, priv, asset, to, bals[asset])
        ref.set({"op": {"stage": "sweeping", "asset": asset, "tx": tx, "at": now, "units": bals[asset]}}, merge=True)
        return {"state": "sweeping", "tx": tx}
    spare = bals[native] - _native_reserve(network)
    if spare > 0 and usd_value(native, spare) >= max(min_usd, 0.5 if force else min_usd):
        tx = _send(cfg, network, priv, native, to, spare)
        ref.set({"op": {"stage": "sweeping", "asset": native, "tx": tx, "at": now, "units": spare}}, merge=True)
        return {"state": "sweeping", "tx": tx}
    return {"state": "idle"}


def sweep_tick(db, hooks: dict, now: float | None = None) -> int:
    """يمر على العناوين التي وصلها مال (dirty) أو عليها عملية جارية."""
    cfg = get_config(db)
    if not cfg.get("auto_sweep") or not master():
        return 0
    n = 0
    for d in db.collection(ADDRS).stream():
        row = d.to_dict() or {}
        if not (row.get("dirty") or row.get("op")) or row.get("network") not in ("tron", "bsc"):
            continue
        try:
            sweep_address(db, row["network"], row["uid"], hooks, now=now)
            n += 1
        except Exception as e:  # noqa: BLE001
            db.collection(ADDRS).document(d.id).set({"sweep_error": f"{type(e).__name__}: {e}"[:200], "sweep_error_at": time.time()}, merge=True)
    return n


# ───────────────────────── خزان الغاز + نظرة عامة ─────────────────────────
def gas_status(db) -> dict:
    cfg = get_config(db)
    out = {}
    if not master():
        return out
    for net in ("tron", "bsc"):
        addr = address_of(net, gas_key(net))
        try:
            bal = balance(cfg, NATIVE[net], addr)
            val = from_units(NATIVE[net], bal)
            out[net] = {"address": addr, "balance": fmt_units(NATIVE[net], bal), "symbol": ASSETS[NATIVE[net]]["symbol"],
                        "low": val < float(cfg["gas_alert"].get(net) or 0)}
        except Exception as e:  # noqa: BLE001
            out[net] = {"address": addr, "error": f"{type(e).__name__}"}
    return out


def overview(db, now: float | None = None) -> dict:
    from google.cloud.firestore_v1.base_query import FieldFilter

    now = time.time() if now is None else now
    cfg = get_config(db)
    stats = {"finished_30d": 0, "revenue_usd_30d": 0.0, "open": 0, "partial": 0, "underpaid": 0, "by_asset": {}}
    for d in db.collection("payments").where(filter=FieldFilter("method", "==", "gateway")).stream():
        p = d.to_dict() or {}
        st = p.get("status")
        if st == "finished" and now - float(p.get("confirmed_at") or p.get("created_at") or 0) < 30 * 86400:
            stats["finished_30d"] += 1
            stats["revenue_usd_30d"] += float(p.get("amount_usd") or 0)
            stats["by_asset"][p.get("asset")] = stats["by_asset"].get(p.get("asset"), 0) + 1
        elif st in ("waiting", "expired"):
            stats["open"] += 1
        elif st == "partially_paid":
            stats["partial"] += 1
        elif st == "underpaid":
            stats["underpaid"] += 1
    stats["revenue_usd_30d"] = round(stats["revenue_usd_30d"], 2)
    return {"config": cfg, "master_key": master() is not None, "active": active(cfg),
            "ready": {n: network_ready(cfg, n) for n in NETWORKS}, "stats": stats,
            "assets": {k: {"symbol": a["symbol"], "network": a["network"], "label": a["label"]} for k, a in ASSETS.items()}}
