"""
AW Chain Crypto — تشفير الشبكات لبوابة الدفع الخاصة (بلا وسيط): TRON و BNB Smart Chain، وقراءة تعليقات TON.

  • المفاتيح: كل عنوان إيداع يُشتق حتميًا من مفتاح رئيسي واحد (GATEWAY_MASTER_KEY في .env فقط، لا يُخزَّن في
    قاعدة البيانات أبدًا): priv = HMAC-SHA512(master, "<network>/<purpose>/<id>")[:32] mod n. نفس المفتاح الرئيسي
    = نفس العناوين دائمًا، فيمكن استعادة أي محفظة بسكربت gateway_keys.py على السيرفر.
  • secp256k1 بمكتبة ecdsa (توقيع حتمي RFC6979 + low-s) + keccak256 من pycryptodome.
  • BSC: معاملات EIP-155 (legacy) مُرمَّزة RLP وموقّعة محليًا — المفتاح لا يغادر السيرفر.
  • TRON: العنوان base58check(0x41 + آخر 20 بايت من keccak(pubkey))؛ التوقيع r||s||v على sha256(raw_data).
  • TON: قراءة تعليق نصي من BOC (forward_payload لتحويلات USDT على TON).
"""
import base64
import hashlib
import hmac

from Crypto.Hash import keccak as _keccak
from ecdsa import SECP256k1, SigningKey
from ecdsa.ellipticcurve import Point
from ecdsa.numbertheory import inverse_mod
from ecdsa.util import sigencode_strings_canonize

N = SECP256k1.order
_CURVE = SECP256k1.curve
_G = SECP256k1.generator
_P = _CURVE.p()


def keccak256(data: bytes) -> bytes:
    h = _keccak.new(digest_bits=256)
    h.update(data)
    return h.digest()


# ───────────────────────── المفاتيح ─────────────────────────
def derive_private_key(master: bytes, path: str) -> bytes:
    if len(master) < 32:
        raise ValueError("master key must be at least 32 bytes")
    d = int.from_bytes(hmac.new(master, path.encode(), hashlib.sha512).digest()[:32], "big")
    return ((d % (N - 1)) + 1).to_bytes(32, "big")


def public_key(priv: bytes) -> bytes:
    """المفتاح العام غير المضغوط بلا البادئة 04 (64 بايت)."""
    return SigningKey.from_string(priv, curve=SECP256k1).get_verifying_key().to_string()


def eth_address_bytes(priv: bytes) -> bytes:
    return keccak256(public_key(priv))[12:]


def to_checksum(addr20: bytes) -> str:
    h = addr20.hex()
    digest = keccak256(h.encode()).hex()
    return "0x" + "".join(c.upper() if int(digest[i], 16) >= 8 else c for i, c in enumerate(h))


def eth_address(priv: bytes) -> str:
    return to_checksum(eth_address_bytes(priv))


def is_eth_address(addr: str) -> bool:
    a = str(addr or "")
    if len(a) != 42 or not a.startswith("0x"):
        return False
    try:
        bytes.fromhex(a[2:])
    except ValueError:
        return False
    body = a[2:]
    if body.lower() == body or body.upper() == body:
        return True
    return to_checksum(bytes.fromhex(body)) == a  # حالة مختلطة = يجب أن تطابق EIP-55


# ───────────────────────── التوقيع القابل للاسترجاع ─────────────────────────
def _recover(digest: bytes, r: int, s: int, recid: int) -> bytes | None:
    alpha = (pow(r, 3, _P) + 7) % _P
    beta = pow(alpha, (_P + 1) // 4, _P)
    y = beta if beta % 2 == recid else _P - beta
    if (y * y - alpha) % _P:
        return None
    R = Point(_CURVE, r, y, N)
    e = int.from_bytes(digest, "big") % N
    Q = inverse_mod(r, N) * (s * R + ((-e) % N) * _G)
    return Q.x().to_bytes(32, "big") + Q.y().to_bytes(32, "big")


def sign_digest(priv: bytes, digest: bytes) -> tuple[int, int, int]:
    """(r, s, recid) — توقيع حتمي RFC6979 بـ s منخفضة (مطلوبة في الشبكتين)."""
    sk = SigningKey.from_string(priv, curve=SECP256k1)
    r_b, s_b = sk.sign_digest_deterministic(digest, hashfunc=hashlib.sha256, sigencode=sigencode_strings_canonize)
    r, s = int.from_bytes(r_b, "big"), int.from_bytes(s_b, "big")
    pub = public_key(priv)
    for recid in (0, 1):
        if _recover(digest, r, s, recid) == pub:
            return r, s, recid
    raise ValueError("could not compute recovery id")


# ───────────────────────── RLP + EIP-155 (BSC) ─────────────────────────
def _int_bytes(v: int) -> bytes:
    return b"" if v == 0 else v.to_bytes((v.bit_length() + 7) // 8, "big")


def rlp(item) -> bytes:
    if isinstance(item, int):
        item = _int_bytes(item)
    if isinstance(item, bytes):
        if len(item) == 1 and item[0] < 0x80:
            return item
        return _rlp_len(len(item), 0x80) + item
    body = b"".join(rlp(x) for x in item)
    return _rlp_len(len(body), 0xC0) + body


def _rlp_len(n: int, offset: int) -> bytes:
    if n < 56:
        return bytes([offset + n])
    b = _int_bytes(n)
    return bytes([offset + 55 + len(b)]) + b


def sign_legacy_tx(priv: bytes, *, nonce: int, gas_price: int, gas: int, to: str, value: int, data: bytes, chain_id: int) -> tuple[str, str]:
    """يعيد (raw_tx_hex, tx_hash_hex) لمعاملة EIP-155 موقّعة."""
    to_b = bytes.fromhex(to[2:])
    fields = [nonce, gas_price, gas, to_b, value, data]
    digest = keccak256(rlp(fields + [chain_id, 0, 0]))
    r, s, recid = sign_digest(priv, digest)
    raw = rlp(fields + [recid + chain_id * 2 + 35, r, s])
    return "0x" + raw.hex(), "0x" + keccak256(raw).hex()


# ───────────────────────── ABI (ERC20/TRC20) ─────────────────────────
def abi_transfer(to20: bytes, amount: int) -> bytes:
    return bytes.fromhex("a9059cbb") + to20.rjust(32, b"\0") + amount.to_bytes(32, "big")


def abi_balance_of(addr20: bytes) -> bytes:
    return bytes.fromhex("70a08231") + addr20.rjust(32, b"\0")


# ───────────────────────── Base58 + TRON ─────────────────────────
_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58encode(b: bytes) -> str:
    n = int.from_bytes(b, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = _B58[r] + out
    return "1" * (len(b) - len(b.lstrip(b"\0"))) + out


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        i = _B58.find(c)
        if i < 0:
            raise ValueError("invalid base58")
        n = n * 58 + i
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    return b"\0" * (len(s) - len(s.lstrip("1"))) + body


def b58check_encode(payload: bytes) -> str:
    return b58encode(payload + hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4])


def b58check_decode(s: str) -> bytes:
    raw = b58decode(s)
    payload, chk = raw[:-4], raw[-4:]
    if len(raw) < 5 or hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] != chk:
        raise ValueError("bad checksum")
    return payload


def tron_address_from_20(addr20: bytes) -> str:
    return b58check_encode(b"\x41" + addr20)


def tron_address(priv: bytes) -> str:
    return tron_address_from_20(eth_address_bytes(priv))


def tron_to_20(addr: str) -> bytes:
    p = b58check_decode(addr)
    if len(p) != 21 or p[0] != 0x41:
        raise ValueError("not a TRON address")
    return p[1:]


def is_tron_address(addr: str) -> bool:
    try:
        return len(str(addr)) == 34 and str(addr).startswith("T") and len(tron_to_20(str(addr))) == 20
    except ValueError:
        return False


def tron_sign(priv: bytes, raw_data_hex: str) -> tuple[str, str]:
    """يعيد (txID, signature_hex). txID = sha256(raw_data)."""
    digest = hashlib.sha256(bytes.fromhex(raw_data_hex)).digest()
    r, s, recid = sign_digest(priv, digest)
    return digest.hex(), (r.to_bytes(32, "big") + s.to_bytes(32, "big") + bytes([recid])).hex()


# ───────────────────────── TON: قراءة تعليق من BOC ─────────────────────────
def _parse_boc(data: bytes) -> tuple[list, int]:
    if data[:4] != bytes.fromhex("b5ee9c72"):
        raise ValueError("unsupported BOC")
    flags = data[4]
    has_idx, size = flags & 0x80, flags & 0x07
    off = data[5]
    pos = 6
    rd = lambda n: int.from_bytes(data[pos:pos + n], "big")  # noqa: E731
    cells = rd(size); pos += size
    roots = rd(size); pos += size
    pos += size  # absent
    pos += off  # tot_cells_size
    root = rd(size); pos += size * roots
    if has_idx:
        pos += cells * off
    out = []
    for _ in range(cells):
        d1, d2 = data[pos], data[pos + 1]
        pos += 2
        nbytes = (d2 + 1) // 2
        body = data[pos:pos + nbytes]
        pos += nbytes
        bits = len(body) * 8
        if d2 % 2 and body:  # بايت أخير غير مكتمل: إزالة علامة الإكمال
            last = body[-1]
            trail = (last & -last).bit_length()
            bits -= trail
        refs = [int.from_bytes(data[pos + i * size:pos + (i + 1) * size], "big") for i in range(d1 & 7)]
        pos += size * (d1 & 7)
        out.append((body, bits, refs))
    return out, root


def boc_comment(b64: str | None) -> str | None:
    """نص التعليق (op=0) من BOC base64، أو None إن لم يكن تعليقًا نصيًا."""
    if not b64:
        return None
    try:
        cells, root = _parse_boc(base64.b64decode(b64))
        body, bits, refs = cells[root]
        if bits < 32 or bits % 8 or body[:4] != b"\0\0\0\0":  # التعليق بايتات كاملة دائمًا
            return None
        buf = body[4:bits // 8]
        seen = 0
        while refs and seen < 16:  # تعليق طويل مقسّم على خلايا متتالية (snake)
            body, bits, refs = cells[refs[0]]
            buf += body[:bits // 8]
            seen += 1
        return buf.decode("utf-8", "replace").strip()
    except (ValueError, IndexError):
        return None


def _comment_from(cells, idx, body, bits, refs) -> str | None:
    if bits < 32 or body[:4] != b"\0\0\0\0":
        return None
    buf = body[4:bits // 8]
    seen = 0
    while refs and seen < 16:
        body, bits, refs = cells[refs[0]]
        buf += body[:bits // 8]
        seen += 1
    return buf.decode("utf-8", "replace").strip()


def payload_comment(b64: str | None) -> str | None:
    """تعليق من forward_payload لتحويل USDT على TON، أيًّا كان شكله: خلية التعليق نفسها، أو Either
    (بت 0 ثم التعليق داخل الخلية نفسها، أو بت 1 والتعليق في خلية مرجعية)."""
    direct = boc_comment(b64)
    if direct is not None or not b64:
        return direct
    try:
        cells, root = _parse_boc(base64.b64decode(b64))
        body, bits, refs = cells[root]
        if bits < 1:
            return None
        if body[0] & 0x80:  # بت 1: الحمولة في المرجع
            if not refs:
                return None
            r = cells[refs[0]]
            return _comment_from(cells, refs[0], *r)
        n = int.from_bytes(body, "big") << 1  # بت 0: الحمولة بعده مباشرة — نزيح بتًا واحدًا
        shifted = (n & ((1 << (len(body) * 8)) - 1)).to_bytes(len(body), "big")
        return _comment_from(cells, root, shifted, bits - 1, refs)
    except (ValueError, IndexError):
        return None
