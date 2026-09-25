"""
AW Support Accounts — ردود الدعم من حسابات تلجرام حقيقية (MTProto عبر Telethon) مع تحويل احتياطي تلقائي.

  • الأدمن يضيف حسابًا من اللوحة: رقم الهاتف + API ID + API Hash (من my.telegram.org) + الأولوية،
    ثم يُدخل رمز الدخول الذي يصل لتطبيق تلجرام ذلك الحساب (وكلمة التحقق بخطوتين إن وُجدت).
  • الجلسة (StringSession) ومفتاح API يُحفظان مشفّرين (secretbox) في support_accounts/{id}.
  • حساب واحد فقط فعّال في أي لحظة: الأعلى أولوية من الحسابات السليمة. يستقبل رسائل المستخدمين الخاصة
    ويمررها لمحرك الدعم، وكل الردود تصدر منه وحده (support.ACCOUNT["send"]).
  • فحص صحة كل 30 ثانية: أي عطل قاتل (خروج من الجلسة، حظر، إلغاء الجلسة) أو 3 أعطال اتصال متتالية
    → يُعلَّم الحساب failed ويُفعَّل التالي في الترتيب تلقائيًا، مع تنبيه الأدمن. الرسائل التي لم تُرسل
    أثناء التبديل تُرسل من الحساب الجديد (لا تصدر من أي مصدر آخر).

ملاحظة: تلجرام يقيّد الحسابات التي ترسل كثيرًا لأشخاص لم يراسلوها؛ الحساب هنا يرد فقط على من راسله.
"""
import asyncio
import logging
import re
import threading
import time

import secretbox
import support

log = logging.getLogger("uvicorn.error")

COL = "support_accounts"
PEERS = "support_peers"
HEALTH_SEC = 30
FATAL = ("AuthKeyUnregisteredError", "UserDeactivatedBanError", "UserDeactivatedError", "SessionRevokedError",
         "AuthKeyDuplicatedError", "SessionExpiredError", "PhoneNumberBannedError")


def _client(session: str, api_id: int, api_hash: str):
    """مصنع العميل (يُستبدل في الاختبارات)."""
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    return TelegramClient(StringSession(session or ""), int(api_id), api_hash, device_model="AW Support", app_version="1.0")


CLIENT_FACTORY = {"fn": _client}


def public_row(d) -> dict:
    x = d.to_dict() or {}
    phone = x.get("phone") or ""
    return {"id": d.id, "phone": phone[:4] + "•••" + phone[-3:] if len(phone) > 7 else phone, "api_id": x.get("api_id"),
            "priority": x.get("priority", 1), "enabled": x.get("enabled", True), "status": x.get("status"),
            "username": x.get("username"), "tg_id": x.get("tg_id"), "last_error": x.get("last_error"),
            "active": x.get("status") == "active", "updated_at": x.get("updated_at"), "failed_at": x.get("failed_at")}


class Manager:
    def __init__(self, db, notify=None):
        self.db = db
        self.notify = notify or (lambda text: None)
        self.loop = None
        self.thread = None
        self.client = None
        self.active_id = None
        self.soft_fails = 0
        self._switch = None
        self._warned_none = False

    # ─────────── تشغيل الحلقة ───────────
    def start(self):
        if self.thread:
            return
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, daemon=True, name="support-accounts")
        self.thread.start()

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self._switch = asyncio.Lock()
        self.loop.create_task(self._supervise())
        self.loop.run_forever()

    def call(self, coro, timeout=60):
        """تشغيل coroutine على حلقة المدير من أي خيط."""
        if not self.loop:
            self.start()
            time.sleep(0.05)
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    # ─────────── البيانات ───────────
    def _ref(self, aid):
        return self.db.collection(COL).document(aid)

    def _mark(self, aid, **fields):
        self._ref(aid).set({**fields, "updated_at": time.time()}, merge=True)

    def rows(self) -> list:
        rows = [(d.id, d.to_dict() or {}) for d in self.db.collection(COL).stream()]
        return sorted(rows, key=lambda r: (int(r[1].get("priority") or 99), r[1].get("created_at") or 0))

    # ─────────── تسجيل الدخول (من اللوحة) ───────────
    async def begin_login(self, phone: str, api_id: int, api_hash: str, priority: int) -> str:
        ref = self.db.collection(COL).document()
        c = CLIENT_FACTORY["fn"]("", api_id, api_hash)
        await c.connect()
        try:
            sent = await c.send_code_request(phone)
            ref.set({"phone": phone, "api_id": int(api_id), "api_hash": secretbox.seal(api_hash), "priority": int(priority),
                     "enabled": True, "status": "pending_code", "tmp_session": secretbox.seal(c.session.save()),
                     "phone_code_hash": getattr(sent, "phone_code_hash", ""), "created_at": time.time(), "updated_at": time.time()})
        finally:
            await c.disconnect()
        return ref.id

    async def complete_login(self, aid: str, code: str, password: str = "") -> dict:
        snap = self._ref(aid).get()
        x = snap.to_dict() if snap.exists else None
        if not x or x.get("status") not in ("pending_code", "pending_password"):
            return {"ok": False, "reason": "no_pending_login"}
        c = CLIENT_FACTORY["fn"](secretbox.open_(x.get("tmp_session") or ""), x["api_id"], secretbox.open_(x["api_hash"]))
        await c.connect()
        try:
            try:
                if x["status"] == "pending_code":
                    await c.sign_in(phone=x["phone"], code=code, phone_code_hash=x.get("phone_code_hash"))
                else:
                    await c.sign_in(password=password)
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if name == "SessionPasswordNeededError":
                    if password:
                        await c.sign_in(password=password)
                    else:
                        self._mark(aid, status="pending_password", tmp_session=secretbox.seal(c.session.save()))
                        return {"ok": False, "reason": "password_required"}
                else:
                    return {"ok": False, "reason": name}
            me = await c.get_me()
            self._mark(aid, status="standby", session=secretbox.seal(c.session.save()), tmp_session=None, phone_code_hash=None,
                       username=getattr(me, "username", None), tg_id=getattr(me, "id", None), last_error=None)
        finally:
            await c.disconnect()
        await self.ensure_active()
        return {"ok": True}

    # ─────────── اختيار الحساب الفعّال والتحويل الاحتياطي ───────────
    async def ensure_active(self, force: bool = False):
        async with self._switch:
            if self.client and not force:
                return self.active_id
            await self._drop_client()
            for aid, x in self.rows():
                if not x.get("enabled", True) or x.get("status") not in ("standby", "active") or not x.get("session"):
                    continue
                try:
                    c = CLIENT_FACTORY["fn"](secretbox.open_(x["session"]), x["api_id"], secretbox.open_(x["api_hash"]))
                    await c.connect()
                    if not await c.is_user_authorized():
                        raise RuntimeError("AuthKeyUnregisteredError: not authorized")
                    me = await c.get_me()
                except Exception as e:  # noqa: BLE001
                    self._mark(aid, status="failed", last_error=f"{type(e).__name__}: {e}"[:200], failed_at=time.time())
                    self.notify(f"⚠️ حساب الدعم {x.get('username') or x.get('phone')} تعطّل: {type(e).__name__}. جارٍ التحويل للحساب التالي.")
                    continue
                self._attach(c)
                self.client, self.active_id, self.soft_fails = c, aid, 0
                for oid, _ in self.rows():
                    if oid != aid and _.get("status") == "active":
                        self._mark(oid, status="standby")
                self._mark(aid, status="active", username=getattr(me, "username", None), tg_id=getattr(me, "id", None), last_error=None)
                support.ACCOUNT["username"] = getattr(me, "username", None) or x.get("username")
                support.ACCOUNT["send"] = self.send_text
                log.info("support account active: %s", support.ACCOUNT["username"])
                self._warned_none = False
                self._flush_outbox()
                return aid
            support.ACCOUNT["send"] = None
            support.ACCOUNT["username"] = None
            if any(x.get("enabled", True) for _, x in self.rows()) and not self._warned_none:
                self._warned_none = True
                self.notify("🔴 لا يوجد أي حساب دعم فعّال — راجع قسم الحسابات في لوحة التحكم.")
            return None

    async def failover(self, reason: str):
        if self.active_id:
            self._mark(self.active_id, status="failed", last_error=reason[:200], failed_at=time.time())
            self.notify(f"⚠️ تعطّل حساب الدعم الفعّال ({reason[:80]}). تحويل تلقائي للحساب الاحتياطي التالي.")
        await self.ensure_active(force=True)

    async def _drop_client(self):
        c, self.client, self.active_id = self.client, None, None
        if c:
            try:
                await c.disconnect()
            except Exception:  # noqa: BLE001
                pass

    async def _supervise(self):
        while True:
            try:
                if not self.client:
                    await self.ensure_active()
                else:
                    await asyncio.wait_for(self.client.get_me(), 20)
                    self.soft_fails = 0
            except Exception as e:  # noqa: BLE001
                name = type(e).__name__
                if name in FATAL:
                    await self.failover(name)
                else:
                    self.soft_fails += 1
                    if self.soft_fails >= 3:
                        await self.failover(f"connection: {name}")
            await asyncio.sleep(HEALTH_SEC)

    # ─────────── الرسائل ───────────
    def _attach(self, c):
        try:
            from telethon import events
        except ImportError:  # الاختبارات بلا Telethon
            events = None
        if events is not None and hasattr(c, "add_event_handler"):
            c.add_event_handler(self._on_message, events.NewMessage(incoming=True))

    async def _on_message(self, event):
        if not event.is_private or getattr(event, "out", False):
            return
        sender = await event.get_sender()
        if getattr(sender, "bot", False) or getattr(sender, "is_self", False):
            return
        await self.incoming(sender, event.raw_text or "")

    async def incoming(self, sender, text: str):
        uid = int(sender.id)
        self.db.collection(PEERS).document(str(uid)).set({"username": getattr(sender, "username", None),
                                                          "access_hash": getattr(sender, "access_hash", None),
                                                          "account": self.active_id, "at": time.time()}, merge=True)
        lang = "ar" if re.search(r"[؀-ۿ]", text) or (getattr(sender, "lang_code", "") or "").startswith("ar") else "en"
        await self.loop.run_in_executor(None, support.handle_account_message, self.db, uid, text, lang)

    async def _send(self, uid, text: str) -> bool:
        c = self.client
        if not c:
            return False
        target = int(uid)
        try:
            await c.get_input_entity(target)
        except Exception:  # noqa: BLE001 — الحساب لا يعرف هذا المستخدم (بعد تحويل احتياطي): نحاول باسم المستخدم
            peer = (self.db.collection(PEERS).document(str(uid)).get().to_dict() or {})
            if not peer.get("username"):
                return False
            target = peer["username"]
        await c.send_message(target, text)
        return True

    def send_text(self, uid, text: str) -> bool:
        """يُستدعى من محرك الدعم (أي خيط). عند عطل قاتل: تحويل احتياطي ثم محاولة واحدة من الحساب الجديد.
        إن لم يبقَ حساب سليم تنتظر الرسالة في الصندوق لتُرسل من الحساب التالي عند تشغيله — لا من أي مصدر آخر."""
        try:
            if self.call(self._send(uid, text), timeout=30):
                return True
        except Exception as e:  # noqa: BLE001
            name = type(e).__name__
            log.warning("support account send failed: %s", name)
            if name in FATAL or name == "ConnectionError":
                self.call(self.failover(name), timeout=90)
                try:
                    if self.call(self._send(uid, text), timeout=30):
                        return True
                except Exception:  # noqa: BLE001
                    pass
        support.OUTBOX.append((uid, text))
        return False

    def _flush_outbox(self):
        pending, support.OUTBOX[:] = list(support.OUTBOX), []
        for uid, text in pending:
            self.loop.create_task(self._safe_send(uid, text))

    async def _safe_send(self, uid, text):
        try:
            await self._send(uid, text)
        except Exception:  # noqa: BLE001
            log.warning("outbox send failed for %s", uid)

    # ─────────── إدارة من اللوحة ───────────
    def update(self, aid: str, patch: dict):
        clean = {}
        if "priority" in patch:
            clean["priority"] = max(1, min(99, int(patch["priority"])))
        if "enabled" in patch:
            clean["enabled"] = bool(patch["enabled"])
        if patch.get("reset"):
            clean.update(status="standby", last_error=None)
        self._mark(aid, **clean)
        return self.call(self.ensure_active(force=True))

    def remove(self, aid: str):
        was_active = aid == self.active_id
        self._ref(aid).delete()
        if was_active:
            self.call(self.ensure_active(force=True))


MANAGER: dict = {"m": None}


def get(db, notify=None) -> Manager:
    if MANAGER["m"] is None:
        MANAGER["m"] = Manager(db, notify)
    return MANAGER["m"]
