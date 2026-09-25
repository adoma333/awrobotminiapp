"""
نقل كل بيانات Firebase (Firestore) إلى القاعدة المحلية SQLite — يُشغَّل تلقائيًا من aw-update.

  • ينسخ كل المجموعات وكل المستندات كما هي (التواريخ والقوائم والخرائط المتداخلة).
  • قابل للاستئناف: إن توقف في المنتصف (حد Firebase اليومي مثلًا) يكمل لاحقًا من حيث توقف دون إعادة القراءة.
  • يطابق عدد المستندات في كل مجموعة بين الطرفين قبل اعتماد النتيجة.
  • لا يحذف ولا يعدّل أي شيء في Firebase (يبقى نسخة احتياطية كاملة).

رموز الخروج: 0 نجح · 2 حد Firebase اليومي (أعد المحاولة لاحقًا) · 1 خطأ آخر
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(HERE, ".env"))

import localdb  # noqa: E402

FIRST = ["config", "users", "payments", "packages", "rewards_cards", "reward_cards", "support_tickets", "gw_addresses"]


def firestore_client():
    import firebase_admin
    from firebase_admin import credentials, firestore

    key_json = os.getenv("FIREBASE_KEY_JSON")
    key_path = os.getenv("FIREBASE_KEY_PATH", "firebase-adminsdk.json")
    if not os.path.isabs(key_path):
        key_path = os.path.join(HERE, key_path)
    cred = credentials.Certificate(json.loads(key_json)) if key_json else credentials.Certificate(key_path)
    try:
        firebase_admin.get_app()
    except ValueError:
        firebase_admin.initialize_app(cred)
    return firestore.client()


def is_quota(e: Exception) -> bool:
    return "ResourceExhausted" in type(e).__name__ or "Quota exceeded" in str(e) or "429" in str(e)[:40]


def _copy_all(fdb, con, names, done, summary, log):
    for name in names:
        if name in done:
            summary[name] = done[name]
            log(f"  ✔ {name}: {done[name]} (منقولة سابقًا)")
            continue
        rows = []
        for snap in fdb.collection(name).stream():
            rows.append((name, snap.id, json.dumps(localdb._enc(snap.to_dict() or {}), ensure_ascii=False, separators=(",", ":")), time.time()))
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM docs WHERE col=?", (name,))
        con.executemany("INSERT INTO docs(col, id, data, updated) VALUES (?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO _migrated(col, n, at) VALUES (?,?,?)", (name, len(rows), time.time()))
        con.execute("COMMIT")
        got = con.execute("SELECT COUNT(*) FROM docs WHERE col=?", (name,)).fetchone()[0]
        if got != len(rows):
            raise RuntimeError(f"count mismatch in {name}: firebase={len(rows)} sqlite={got}")
        summary[name] = got
        log(f"  ✔ {name}: {got}")


def migrate(fdb, final_path: str, log=print) -> dict:
    tmp_path = final_path + ".migrating"
    dest = localdb.Client(tmp_path)
    con = dest._conn()
    try:
        con.execute("CREATE TABLE IF NOT EXISTS _migrated (col TEXT PRIMARY KEY, n INTEGER, at REAL)")
        done = {r[0]: r[1] for r in con.execute("SELECT col, n FROM _migrated")}
        names = [c.id for c in fdb.collections()]
        names.sort(key=lambda n: (FIRST.index(n) if n in FIRST else len(FIRST), n))
        summary: dict = {}
        _copy_all(fdb, con, names, done, summary, log)
        con.execute("DROP TABLE _migrated")
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("PRAGMA journal_mode=DELETE")  # ملف واحد مكتمل قبل نقله لمكانه النهائي
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise  # ما نُقل محفوظ في الملف المؤقت للاستئناف
    finally:
        con.close()
        dest._local.c = None
    if os.path.exists(final_path):  # قاعدة محلية سابقة: تُحفظ جانبًا ولا تُحذف
        os.replace(final_path, f"{final_path}.before-{time.strftime('%Y%m%d-%H%M%S')}")
    os.replace(tmp_path, final_path)
    return summary


def main() -> int:
    final_path = os.getenv("DB_PATH") or localdb.DEFAULT_PATH
    try:
        fdb = firestore_client()
        summary = migrate(fdb, final_path)
    except Exception as e:  # noqa: BLE001
        if is_quota(e):
            print("⏳ حد Firebase اليومي ما زال مستنفدًا. ما نُقل محفوظ، وسيكمل النقل من حيث توقف عند إعادة المحاولة.")
            return 2
        print(f"❌ تعذّر النقل: {type(e).__name__}: {e}")
        return 1
    total = sum(summary.values())
    print(f"✅ نُقل {total} مستندًا من {len(summary)} مجموعة إلى {final_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
