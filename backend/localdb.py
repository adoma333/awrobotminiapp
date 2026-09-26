"""
AW LocalDB — قاعدة بيانات محلية (SQLite) بنفس واجهة Firestore التي يستخدمها المشروع، بلا حدود يومية ولا تكلفة.

تدعم كل ما يستخدمه الكود: collection / document / get / set(merge) / update (مسارات بنقاط) / delete / create
/ where (== != والمقارنات و in و FieldFilter) / order_by / limit / select / stream، و SERVER_TIMESTAMP.

  • كل مستند = صف JSON في جدول docs(col, id, data). التواريخ تُحفظ {"__ts__": epoch} وتعود datetime (UTC).
  • وضع WAL: الخادم (aw-backend) والمزامنة (aw-sync) يقرآن ويكتبان معًا بأمان؛ كل تعديل ذرّي (BEGIN IMMEDIATE).
  • المسار: DB_PATH أو <المشروع>/data/aw.db
"""
import json
import re
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timezone

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "aw.db")


class _ServerTimestamp:
    def __repr__(self):
        return "SERVER_TIMESTAMP"


SERVER_TIMESTAMP = _ServerTimestamp()


class Query:  # للتوافق مع firestore.Query.DESCENDING
    ASCENDING = "ASCENDING"
    DESCENDING = "DESCENDING"


try:
    from google.api_core.exceptions import AlreadyExists
except ImportError:  # pragma: no cover
    class AlreadyExists(Exception):
        pass


# ───────────────────────── الترميز ─────────────────────────
def _now():
    return datetime.now(timezone.utc)


def _enc(v):
    if v is SERVER_TIMESTAMP:
        return {"__ts__": _now().timestamp()}
    if isinstance(v, datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return {"__ts__": v.timestamp()}
    if isinstance(v, dict):
        return {str(k): _enc(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_enc(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        return {"__bytes__": bytes(v).hex()}
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    return str(v)  # أنواع Firestore النادرة (GeoPoint/Reference) كنص


def _dec(v):
    if isinstance(v, dict):
        if len(v) == 1 and "__ts__" in v:
            return datetime.fromtimestamp(float(v["__ts__"]), tz=timezone.utc)
        if len(v) == 1 and "__bytes__" in v:
            return bytes.fromhex(v["__bytes__"])
        return {k: _dec(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_dec(x) for x in v]
    return v


def _merge(dst: dict, src: dict):
    for k, v in src.items():
        if isinstance(v, dict) and not ("__ts__" in v and len(v) == 1) and isinstance(dst.get(k), dict):
            _merge(dst[k], v)
        else:
            dst[k] = v


def _get_path(d, path: str):
    cur = d
    for p in path.split("."):
        if not isinstance(cur, dict) or p not in cur:
            return False, None
        cur = cur[p]
    return True, cur


def _cmp_key(v):
    """ترتيب ثابت بين الأنواع (كما في Firestore تقريبًا)."""
    if v is None:
        return (0, 0)
    if isinstance(v, bool):
        return (1, int(v))
    if isinstance(v, (int, float)):
        return (2, v)
    if isinstance(v, datetime):
        return (3, v.timestamp())
    if isinstance(v, str):
        return (4, v)
    return (5, json.dumps(_enc(v), sort_keys=True))


_OPS = {
    "==": lambda a, b: a == b, "EQUAL": lambda a, b: a == b,
    "!=": lambda a, b: a != b, "NOT_EQUAL": lambda a, b: a != b,
    "<": lambda a, b: _cmp_key(a) < _cmp_key(b), "LESS_THAN": lambda a, b: _cmp_key(a) < _cmp_key(b),
    "<=": lambda a, b: _cmp_key(a) <= _cmp_key(b), "LESS_THAN_OR_EQUAL": lambda a, b: _cmp_key(a) <= _cmp_key(b),
    ">": lambda a, b: _cmp_key(a) > _cmp_key(b), "GREATER_THAN": lambda a, b: _cmp_key(a) > _cmp_key(b),
    ">=": lambda a, b: _cmp_key(a) >= _cmp_key(b), "GREATER_THAN_OR_EQUAL": lambda a, b: _cmp_key(a) >= _cmp_key(b),
    "in": lambda a, b: a in (b or []), "IN": lambda a, b: a in (b or []),
    "not-in": lambda a, b: a not in (b or []), "NOT_IN": lambda a, b: a not in (b or []),
    "array_contains": lambda a, b: isinstance(a, list) and b in a, "ARRAY_CONTAINS": lambda a, b: isinstance(a, list) and b in a,
    "array_contains_any": lambda a, b: isinstance(a, list) and any(x in a for x in (b or [])),
    "ARRAY_CONTAINS_ANY": lambda a, b: isinstance(a, list) and any(x in a for x in (b or [])),
}


def _match(d: dict, field: str, op, value) -> bool:
    name = getattr(op, "name", op)  # FieldFilter يحوّل == None / != None إلى IS_NULL / IS_NOT_NULL
    has, cur = _get_path(d, field)
    if name == "IS_NULL" or (name in ("==", "EQUAL") and value is None):
        return has and cur is None
    if name == "IS_NOT_NULL" or (name in ("!=", "NOT_EQUAL") and value is None):
        return has and cur is not None
    if not has:
        return False  # كما في Firestore: المستند بلا الحقل لا يطابق أي شرط عليه
    fn = _OPS.get(name)
    if fn is None:
        raise ValueError(f"unsupported operator: {name}")
    try:
        return bool(fn(cur, value))
    except TypeError:
        return False


# ───────────────────────── الاتصال ─────────────────────────
# الحقول الأكثر استعلامًا في المشروع (uid/status/method…) + حقول التحليلات الزمنية
INDEXED = ("uid", "status", "method", "key", "started", "at")
_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*$")  # مسار الحقل يُكتب حرفيًا في SQL (ليطابق الفهرس) فيُقيَّد بصرامة


def _jpath(field: str) -> str:
    return "$." + ".".join(f'"{p}"' for p in field.split("."))


class Client:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("DB_PATH") or DEFAULT_PATH
        if self.path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._local = threading.local()
        self._mem = None
        if self.path == ":memory:":  # للاختبارات: اتصال واحد مشترك
            self._mem = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
            self._mem_lock = threading.RLock()
        c = self._conn()
        c.execute("CREATE TABLE IF NOT EXISTS docs (col TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, "
                  "updated REAL, PRIMARY KEY (col, id)) WITHOUT ROWID")
        for f in INDEXED:  # فهارس تعبيرية: الاستعلام بالمساواة/النطاق على هذه الحقول لا يمسح المجموعة كاملة
            name = "ix_" + re.sub(r"\W", "_", f)
            c.execute(f"CREATE INDEX IF NOT EXISTS {name} ON docs(col, json_extract(data, '{_jpath(f)}'))")

    def _conn(self) -> sqlite3.Connection:
        if self._mem is not None:
            return self._mem
        c = getattr(self._local, "c", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None, check_same_thread=False)
            c.execute("PRAGMA journal_mode=WAL")       # قرّاء متزامنون مع كاتب واحد بلا حجب
            c.execute("PRAGMA synchronous=NORMAL")     # آمن تمامًا مع WAL (لا تلف عند انقطاع الكهرباء)، وأسرع بكثير من FULL
            c.execute("PRAGMA busy_timeout=30000")
            c.execute("PRAGMA cache_size=-65536")      # 64MB ذاكرة صفحات لكل اتصال
            c.execute("PRAGMA mmap_size=268435456")    # قراءة عبر الذاكرة المعيّنة (256MB) بدل نسخ الصفحات
            c.execute("PRAGMA temp_store=MEMORY")
            c.execute("PRAGMA wal_autocheckpoint=1000")
            c.execute("PRAGMA journal_size_limit=67108864")  # ملف WAL لا يتضخم فوق 64MB بعد كل checkpoint
            self._local.c = c
        return c

    def _tx(self):
        return _Tx(self)

    def collection(self, name: str) -> "CollectionReference":
        return CollectionReference(self, str(name))

    def collections(self) -> list:
        return [CollectionReference(self, r[0]) for r in self._conn().execute("SELECT DISTINCT col FROM docs ORDER BY col")]

    # ───── أدوات داخلية ─────
    def _read(self, col: str, id_: str):
        row = self._conn().execute("SELECT data FROM docs WHERE col=? AND id=?", (col, id_)).fetchone()
        return json.loads(row[0]) if row else None

    def _write(self, col: str, id_: str, data: dict):
        self._conn().execute("INSERT INTO docs(col, id, data, updated) VALUES (?,?,?,?) "
                             "ON CONFLICT(col, id) DO UPDATE SET data=excluded.data, updated=excluded.updated",
                             (col, id_, json.dumps(data, ensure_ascii=False, separators=(",", ":")), time.time()))

    def maintenance(self, full: bool = False) -> dict:
        """صيانة دورية: دمج WAL في الملف الرئيسي وتقليصه + تحديث إحصاءات الفهارس (+ فحص سلامة كامل عند full)."""
        c = self._conn()
        busy, wal_pages, moved = c.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        try:
            c.execute("PRAGMA optimize")  # قد يصطدم بكاتب آخر (SQLITE_BUSY_SNAPSHOT) — إحصاءات فقط، يُعاد غدًا
        except sqlite3.OperationalError:
            pass
        check = c.execute("PRAGMA integrity_check" if full else "PRAGMA quick_check").fetchone()[0]
        return {"checkpoint_busy": bool(busy), "wal_pages": wal_pages, "moved": moved, "integrity": check}

    def health(self) -> dict:
        c = self._conn()
        page, count, free = (c.execute(f"PRAGMA {p}").fetchone()[0] for p in ("page_size", "page_count", "freelist_count"))
        wal = self.path + "-wal"
        return {"backend": "sqlite", "path": self.path, "journal_mode": c.execute("PRAGMA journal_mode").fetchone()[0],
                "size_mb": round(page * count / 1e6, 2), "free_mb": round(page * free / 1e6, 2),
                "wal_mb": round(os.path.getsize(wal) / 1e6, 2) if os.path.exists(wal) else 0.0,
                "docs": c.execute("SELECT COUNT(*) FROM docs").fetchone()[0], "indexes": list(INDEXED)}

    def backup(self, dest: str):
        """نسخة احتياطية متّسقة أثناء العمل (SQLite backup API)."""
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        out = sqlite3.connect(dest)
        with out:
            self._conn().backup(out)
        out.close()


class _Tx:
    """معاملة كتابة حصرية (تمنع تداخل عمليتي قراءة-تعديل-كتابة بين العمليات)."""

    def __init__(self, client: Client):
        self.client = client

    def __enter__(self):
        if self.client._mem is not None:
            self.client._mem_lock.acquire()
        self.c = self.client._conn()
        self.c.execute("BEGIN IMMEDIATE")
        return self.c

    def __exit__(self, et, ev, tb):
        try:
            self.c.execute("ROLLBACK" if et else "COMMIT")
        finally:
            if self.client._mem is not None:
                self.client._mem_lock.release()
        return False


class DocumentSnapshot:
    def __init__(self, ref, data):
        self.reference, self.id = ref, ref.id
        self._data = data
        self.exists = data is not None

    def to_dict(self):
        return _dec(self._data) if self._data is not None else None

    def get(self, field: str):
        has, v = _get_path(self._data or {}, field)
        return _dec(v) if has else None


class DocumentReference:
    def __init__(self, client: Client, col: str, id_: str):
        self._c, self._col, self.id = client, col, str(id_)

    @property
    def path(self):
        return f"{self._col}/{self.id}"

    def get(self, *_a, **_kw) -> DocumentSnapshot:
        return DocumentSnapshot(self, self._c._read(self._col, self.id))

    def set(self, data: dict, merge: bool = False):
        new = _enc(dict(data))
        with self._c._tx():
            if merge:
                cur = self._c._read(self._col, self.id)
                if cur is not None:
                    _merge(cur, new)
                    new = cur
            self._c._write(self._col, self.id, new)

    def update(self, data: dict):
        with self._c._tx():
            cur = self._c._read(self._col, self.id)
            if cur is None:
                from google.api_core.exceptions import NotFound

                raise NotFound(f"No document to update: {self.path}")
            for k, v in data.items():
                *parts, last = str(k).split(".")
                d = cur
                for p in parts:
                    if not isinstance(d.get(p), dict):
                        d[p] = {}
                    d = d[p]
                d[last] = _enc(v)
            self._c._write(self._col, self.id, cur)

    def create(self, data: dict):
        with self._c._tx():
            if self._c._read(self._col, self.id) is not None:
                raise AlreadyExists(f"Document already exists: {self.path}")
            self._c._write(self._col, self.id, _enc(dict(data)))

    def delete(self):
        with self._c._tx():
            self._c._conn().execute("DELETE FROM docs WHERE col=? AND id=?", (self._col, self.id))


class BaseQuery:
    def __init__(self, client: Client, col: str, filters=None, order=None, lim=None):
        self._c, self._col = client, col
        self._filters, self._order, self._lim = filters or [], order or [], lim

    def _copy(self, **kw):
        q = BaseQuery(self._c, self._col, list(self._filters), list(self._order), self._lim)
        for k, v in kw.items():
            setattr(q, k, v)
        return q

    def where(self, field_path=None, op_string=None, value=None, filter=None):
        if filter is not None:
            field_path, op_string, value = filter.field_path, filter.op_string, filter.value
        return self._copy(_filters=self._filters + [(field_path, op_string, value)])

    def order_by(self, field_path: str, direction: str = "ASCENDING"):
        return self._copy(_order=self._order + [(field_path, str(direction).upper() == "DESCENDING")])

    def limit(self, n: int):
        return self._copy(_lim=int(n))

    def select(self, _fields):
        return self

    def _rows(self) -> list:
        sql, args = "SELECT id, data FROM docs WHERE col=?", [self._col]
        for f, op, v in self._filters:  # فلترة أولية داخل SQLite (تستخدم الفهارس)؛ التحقق الكامل بدلالة Firestore في بايثون
            if not _SAFE_FIELD.match(f):
                continue
            name = getattr(op, "name", op)
            if name in ("==", "EQUAL") and isinstance(v, str):
                sql += f" AND json_extract(data, '{_jpath(f)}') = ?"
                args.append(v)
            elif name in (">=", ">", "GREATER_THAN", "GREATER_THAN_OR_EQUAL") and isinstance(v, (int, float)) and not isinstance(v, bool):
                sql += f" AND json_extract(data, '{_jpath(f)}') >= ?"  # مجموعة أوسع دائمًا (النصوص والكائنات > الأرقام في SQLite)
                args.append(v)
        sql += " ORDER BY id"
        out = []
        for id_, raw in self._c._conn().execute(sql, args):
            d = json.loads(raw)
            if all(_match(d, f, op, v) for f, op, v in self._filters):
                out.append((id_, d))
        for field, desc in reversed(self._order):
            out = [r for r in out if _get_path(r[1], field)[0]]  # كما في Firestore: بلا الحقل = خارج الترتيب
            out.sort(key=lambda r: _cmp_key(_dec(_get_path(r[1], field)[1])), reverse=desc)
        if self._lim is not None:
            out = out[: self._lim]
        return [DocumentSnapshot(DocumentReference(self._c, self._col, i), d) for i, d in out]

    def stream(self, *_a, **_kw):
        return iter(self._rows())

    def get(self, *_a, **_kw):
        return self._rows()

    def count(self):
        n = len(self._rows())

        class _Agg:
            def get(self_inner):
                return [[type("R", (), {"value": n})()]]

        return _Agg()


class CollectionReference(BaseQuery):
    def __init__(self, client: Client, col: str):
        super().__init__(client, col)
        self.id = col

    def document(self, id_: str | None = None) -> DocumentReference:
        return DocumentReference(self._c, self._col, id_ if id_ is not None else secrets.token_urlsafe(15)[:20])

    def add(self, data: dict):
        ref = self.document()
        ref.set(data)
        return time.time(), ref


_CLIENT = {"v": None}


def client(path: str | None = None) -> Client:
    if _CLIENT["v"] is None or path:
        _CLIENT["v"] = Client(path)
    return _CLIENT["v"]
