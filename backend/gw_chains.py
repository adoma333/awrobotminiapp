"""
AW Gateway Chains — عملاء الشبكات لبوابة الدفع الخاصة: TRON (TronGrid) و BSC (JSON-RPC) و TON (toncenter).

كل الأرصدة تُقرأ مؤكَّدة فقط: TRON من العقدة المُصلَّبة (walletsolidity)، BSC عند (آخر كتلة − عدد التأكيدات)،
و TON من المعاملات النهائية. كل المعاملات تُوقَّع محليًا (chain_crypto) ولا يغادر أي مفتاح خاص السيرفر.
الطبقة HTTP قابلة للاستبدال (HTTP["post"/"get"]) للاختبارات.
"""
import os
import time

import httpx

import chain_crypto as cc
from retry import raise_for_retryable, with_backoff

TRON_API = os.getenv("TRON_API", "https://api.trongrid.io").rstrip("/")
TRON_KEY = os.getenv("TRON_API_KEY", "")
BSC_RPC = os.getenv("BSC_RPC", "https://bsc-dataseed.bnbchain.org").rstrip("/")
BSC_CHAIN_ID = 56
TONCENTER_V2 = os.getenv("TONCENTER_API", "https://toncenter.com/api/v2").rstrip("/")
TONCENTER_V3 = os.getenv("TONCENTER_V3_API", "https://toncenter.com/api/v3").rstrip("/")
TONCENTER_KEY = os.getenv("TONCENTER_API_KEY", "")
TONAPI = os.getenv("TONAPI_URL", "https://tonapi.io").rstrip("/")
TONAPI_KEY = os.getenv("TONAPI_KEY", "")

USDT_TRC20 = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
USDT_BEP20 = "0x55d398326f99059fF775485246999027B3197955"
USDT_TON_MASTER = "EQCxE6mUtQJKFnGfaROTKOt1lZbDiiX1kCixRv7Nw2Id_sDs"


class ChainError(Exception):
    pass


@with_backoff()
def _post(url: str, body: dict, headers: dict | None = None) -> dict:
    return raise_for_retryable(httpx.post(url, json=body, headers=headers or {}, timeout=20)).json()


@with_backoff()
def _get(url: str, params: dict | None = None, headers: dict | None = None) -> dict:
    return raise_for_retryable(httpx.get(url, params=params or {}, headers=headers or {}, timeout=20)).json()


HTTP = {"post": _post, "get": _get}


# ═══════════════════════════ TRON ═══════════════════════════
def _tron_headers():
    return {"TRON-PRO-API-KEY": TRON_KEY} if TRON_KEY else {}


def _tron(path: str, body: dict) -> dict:
    res = HTTP["post"](f"{TRON_API}{path}", body, _tron_headers())
    if isinstance(res, dict) and res.get("Error"):
        raise ChainError(f"tron: {res['Error']}")
    return res


def tron_trx_balance(addr: str) -> int:
    """رصيد TRX بالـ sun (مُصلَّب)."""
    return int(_tron("/walletsolidity/getaccount", {"address": addr, "visible": True}).get("balance") or 0)


def tron_trc20_balance(contract: str, addr: str) -> int:
    res = _tron("/walletsolidity/triggerconstantcontract", {  # المستدعي = العقد نفسه (موجود دائمًا، عكس عنوان إيداع جديد)
        "owner_address": contract, "contract_address": contract, "function_selector": "balanceOf(address)",
        "parameter": cc.abi_balance_of(cc.tron_to_20(addr))[4:].hex(), "visible": True})
    out = (res.get("constant_result") or ["0"])[0] or "0"
    return int(out, 16)


def _tron_broadcast(priv: bytes, tx: dict, expect: dict) -> str:
    """يتحقق أن المعاملة المبنية من العقدة تطابق ما طلبناه ثم يوقّعها ويبثّها."""
    if not tx or "raw_data_hex" not in tx:
        raise ChainError(f"tron build failed: {str(tx)[:160]}")
    val = ((tx.get("raw_data") or {}).get("contract") or [{}])[0].get("parameter", {}).get("value", {})
    for k, v in expect.items():
        if str(val.get(k, "")).lower() != str(v).lower():
            raise ChainError(f"tron tx mismatch on {k}")
    txid, sig = cc.tron_sign(priv, tx["raw_data_hex"])
    if tx.get("txID") and tx["txID"] != txid:
        raise ChainError("tron txID mismatch")
    res = _tron("/wallet/broadcasttransaction", {**tx, "signature": [sig]})
    if not res.get("result"):
        raise ChainError(f"tron broadcast: {res.get('code')} {res.get('message')}")
    return txid


def tron_send_trx(priv: bytes, to: str, amount_sun: int) -> str:
    frm = cc.tron_address(priv)
    tx = _tron("/wallet/createtransaction", {"owner_address": frm, "to_address": to, "amount": int(amount_sun), "visible": True})
    return _tron_broadcast(priv, tx, {"owner_address": frm, "to_address": to, "amount": int(amount_sun)})


def tron_send_trc20(priv: bytes, contract: str, to: str, amount: int, fee_limit_sun: int) -> str:
    frm = cc.tron_address(priv)
    data = cc.abi_transfer(cc.tron_to_20(to), int(amount))
    res = _tron("/wallet/triggersmartcontract", {
        "owner_address": frm, "contract_address": contract, "function_selector": "transfer(address,uint256)",
        "parameter": data[4:].hex(), "fee_limit": int(fee_limit_sun), "call_value": 0, "visible": True})
    return _tron_broadcast(priv, res.get("transaction") or {}, {"owner_address": frm, "contract_address": contract, "data": data.hex()})


def tron_trc20_fee_sun(frm: str, contract: str, to: str, amount: int) -> int:
    """تقدير كلفة تحويل TRC20 بالـ sun (طاقة × سعر الطاقة الحالي + هامش)."""
    res = _tron("/wallet/triggerconstantcontract", {
        "owner_address": frm, "contract_address": contract, "function_selector": "transfer(address,uint256)",
        "parameter": cc.abi_transfer(cc.tron_to_20(to), int(amount))[4:].hex(), "visible": True})
    energy = int(res.get("energy_used") or 65000)
    price = 420
    for p in (_tron("/wallet/getchainparameters", {}).get("chainParameter") or []):
        if p.get("key") == "getEnergyFee":
            price = int(p.get("value") or price)
    return int(energy * price * 1.15) + 1_000_000  # +1 TRX لعرض النطاق (bandwidth)


def tron_tx_status(txid: str) -> str:
    info = _tron("/walletsolidity/gettransactioninfobyid", {"value": txid})
    if not info or not info.get("id"):
        return "pending"
    if (info.get("receipt") or {}).get("result") not in (None, "SUCCESS") or info.get("result") == "FAILED":
        return "failed"
    return "success"


# ═══════════════════════════ BSC ═══════════════════════════
def _rpc(method: str, params: list):
    res = HTTP["post"](BSC_RPC, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    if res.get("error"):
        raise ChainError(f"bsc {method}: {res['error'].get('message')}")
    return res.get("result")


def bsc_block() -> int:
    return int(_rpc("eth_blockNumber", []), 16)


def _tag(confirmations: int) -> str:
    return hex(max(0, bsc_block() - confirmations)) if confirmations else "latest"


def bsc_native_balance(addr: str, confirmations: int = 0) -> int:
    return int(_rpc("eth_getBalance", [addr, _tag(confirmations)]), 16)


def bsc_token_balance(contract: str, addr: str, confirmations: int = 0) -> int:
    data = "0x" + cc.abi_balance_of(bytes.fromhex(addr[2:])).hex()
    out = _rpc("eth_call", [{"to": contract, "data": data}, _tag(confirmations)]) or "0x0"
    return int(out, 16) if out != "0x" else 0


def bsc_gas_price() -> int:
    return int(_rpc("eth_gasPrice", []), 16)


def _bsc_send(priv: bytes, to: str, value: int, data: bytes, gas: int, gas_price: int) -> str:
    frm = cc.eth_address(priv)
    nonce = int(_rpc("eth_getTransactionCount", [frm, "pending"]), 16)
    raw, h = cc.sign_legacy_tx(priv, nonce=nonce, gas_price=gas_price, gas=gas, to=to, value=value, data=data, chain_id=BSC_CHAIN_ID)
    got = _rpc("eth_sendRawTransaction", [raw])
    if got and got.lower() != h.lower():
        raise ChainError("bsc hash mismatch")
    return h


def bsc_send_native(priv: bytes, to: str, value: int, gas_price: int) -> str:
    return _bsc_send(priv, to, value, b"", 21000, gas_price)


BSC_TOKEN_GAS = 70000


def bsc_send_token(priv: bytes, contract: str, to: str, amount: int, gas_price: int) -> str:
    return _bsc_send(priv, contract, 0, cc.abi_transfer(bytes.fromhex(to[2:]), int(amount)), BSC_TOKEN_GAS, gas_price)


def bsc_tx_status(h: str, confirmations: int = 5) -> str:
    rcpt = _rpc("eth_getTransactionReceipt", [h])
    if not rcpt:
        return "pending"
    if int(rcpt.get("status") or "0x0", 16) != 1:
        return "failed"
    return "success" if bsc_block() - int(rcpt["blockNumber"], 16) >= confirmations else "pending"


# ═══════════════════════════ TON (الدفع المباشر بتعليق) ═══════════════════════════
def _hex_hash(h) -> str | None:
    """toncenter يعيد التجزئة base64؛ المستكشفات تحتاجها hex."""
    if not h:
        return None
    try:
        import base64

        raw = base64.b64decode(str(h) + "=" * (-len(str(h)) % 4), altchars=b"-_" if ("-" in str(h) or "_" in str(h)) else None)
        return raw.hex() if len(raw) == 32 else str(h)
    except (ValueError, TypeError):
        return str(h)


def _ton_headers():
    return {"X-API-Key": TONCENTER_KEY} if TONCENTER_KEY else {}


def ton_incoming(address: str, limit: int = 100) -> list:
    """تحويلات TON الواردة لعنوان الاستلام: [{hash, utime, amount (nano), comment, source}]."""
    res = HTTP["get"](f"{TONCENTER_V2}/getTransactions", {"address": address, "limit": limit, "archival": "true"}, _ton_headers())
    if not res.get("ok", True):
        raise ChainError(f"ton: {res.get('error')}")
    out = []
    for tx in res.get("result") or []:
        m = tx.get("in_msg") or {}
        if not m.get("source") or int(m.get("value") or 0) <= 0:
            continue
        comment = m.get("message") or cc.boc_comment(((m.get("msg_data") or {}).get("body")))
        out.append({"hash": _hex_hash((tx.get("transaction_id") or {}).get("hash")), "utime": int(tx.get("utime") or 0),
                    "amount": int(m["value"]), "comment": (comment or "").strip(), "source": m.get("source")})
    return out


def ton_jetton_incoming(owner: str, master: str, limit: int = 100) -> list:
    """تحويلات USDT (jetton) الواردة لعنوان الاستلام مع تعليق كل تحويل.

    المصدر الأساسي tonapi (نفس مصدر Tonviewer): يقرأ التعليق حتى في سحوبات المنصات المجمّعة (Binance وغيرها)
    التي يعيد فيها toncenter التعليق فارغًا. toncenter احتياطي فقط إن تعطل tonapi."""
    try:
        return _tonapi_jetton_incoming(owner, master, limit)
    except Exception:  # noqa: BLE001 — نكمل بالمصدر الاحتياطي
        return _toncenter_jetton_incoming(owner, master, limit)


def _tonapi_jetton_incoming(owner: str, master: str, limit: int) -> list:
    me, jetton = cc.ton_raw(owner), cc.ton_raw(master)
    headers = {"Authorization": f"Bearer {TONAPI_KEY}"} if TONAPI_KEY else {}
    res = HTTP["get"](f"{TONAPI}/v2/accounts/{owner}/jettons/{master}/history", {"limit": min(100, limit)}, headers)
    if "events" not in res:
        raise ChainError(f"tonapi: {str(res)[:120]}")
    out = []
    for ev in res.get("events") or []:
        for act in ev.get("actions") or []:
            t = act.get("JettonTransfer") or {}
            if act.get("type") != "JettonTransfer" or act.get("status") != "ok":
                continue
            try:  # واردة لعنواننا فعلًا، ومن عقد USDT الحقيقي (لا توكن مزيف بنفس الاسم)
                if cc.ton_raw((t.get("recipient") or {}).get("address")) != me or cc.ton_raw((t.get("jetton") or {}).get("address")) != jetton:
                    continue
            except ValueError:
                continue
            out.append({"hash": ev.get("event_id"), "utime": int(ev.get("timestamp") or 0), "amount": int(t.get("amount") or 0),
                        "comment": str(t.get("comment") or "").strip(), "source": (t.get("sender") or {}).get("address")})
    return out


def _toncenter_jetton_incoming(owner: str, master: str, limit: int) -> list:
    res = HTTP["get"](f"{TONCENTER_V3}/jetton/transfers", {"owner_address": owner, "jetton_master": master, "direction": "in",
                                                          "limit": limit, "sort": "desc"}, _ton_headers())
    out = []
    for t in res.get("jetton_transfers") or []:
        if t.get("transaction_aborted"):
            continue
        comment = (t.get("decoded_forward_payload") or {}).get("comment") if isinstance(t.get("decoded_forward_payload"), dict) else None
        comment = comment or cc.payload_comment(t.get("forward_payload"))
        out.append({"hash": _hex_hash(t.get("transaction_hash")), "utime": int(t.get("transaction_now") or 0), "amount": int(t.get("amount") or 0),
                    "comment": (comment or "").strip(), "source": t.get("source")})
    return out


def ton_balance(address: str) -> int:
    res = HTTP["get"](f"{TONCENTER_V2}/getAddressBalance", {"address": address}, _ton_headers())
    return int(res.get("result") or 0)


# ═══════════════════════════ أسعار العملات (للعملات غير المستقرة) ═══════════════════════════
_RATES = {"at": 0.0, "v": {}}
COINGECKO_IDS = {"trx": "tron", "bnb": "binancecoin", "ton": "the-open-network"}


def usd_rates(ttl: int = 60) -> dict:
    if time.time() - _RATES["at"] < ttl and _RATES["v"]:
        return _RATES["v"]
    try:
        res = HTTP["get"]("https://api.coingecko.com/api/v3/simple/price",
                          {"ids": ",".join(COINGECKO_IDS.values()), "vs_currencies": "usd"}, {})
        v = {k: float((res.get(cid) or {}).get("usd") or 0) for k, cid in COINGECKO_IDS.items()}
        if all(v.values()):
            _RATES.update(at=time.time(), v=v)
    except Exception:  # noqa: BLE001 — نبقي آخر سعر معروف
        pass
    return _RATES["v"]
