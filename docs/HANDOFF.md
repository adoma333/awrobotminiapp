# AW Robot — ملف تسليم تقني كامل

**الغرض من هذا الملف:** أرسله بالكامل لأي مساعد ذكاء اصطناعي آخر (في أول رسالة له) قبل أن تطلب منه أي تعديل، حتى يفهم النظام بالكامل دون إعادة اكتشاف نفس المشاكل. اطلب منه أن يقرأه بالكامل أولاً ويؤكد فهمه قبل تنفيذ أي أمر.

---

## 1) الوصف العام

بوت تليجرام (**AWBOT**، `@awfxapp_bot`) + Mini App يتيح للمستخدمين ربط حساب **MetaTrader 5 (MT5)** ومتابعة أدائه لحظياً (رصيد، نمو، Win Rate)، مع نظام **اشتراكات شهرية مدفوعة** (USDT/TON عبر NOWPayments + Telegram Stars) يُشغّل **قبولاً تلقائياً بالكامل** بعد تحقق حي من صحة بيانات MT5 — بدون تدخل بشري.

---

## 2) الوصول للسيرفر

- **VPS:** Ubuntu، IP: `205.209.121.79`
- **الدومين المؤقت:** `https://205-209-121-79.sslip.io` (خدمة sslip.io تربط أي IP تلقائياً بدومين وهمي صالح لشهادة SSL — لو تغيّر IP يجب تحديث كل مكان يُستخدم فيه هذا الدومين، بما فيها ملف `.env` وnginx وwebhook تليجرام)
- **SSH:** `ssh root@205.209.121.79` (المستخدم `root` يدير النظام، المستخدم `aw` يملك ملفات المشروع)
- **مسار المشروع:** `/home/aw/aw-mini-app/`
  - `backend/` — FastAPI (Python)
  - `frontend/` — تطبيق المستخدم (React + Vite)
  - `admin/` — لوحة تحكم الأدمن (React + Vite، منفصلة تماماً)

---

## 3) البنية الكاملة (Architecture)

```
تليجرام ──webhook──▶ FastAPI (main.py, منفذ 8000 محلي) ──▶ nginx (443) ──▶ العالم
                              │
                              ├─▶ Firestore (قاعدة البيانات، عبر firebase-admin)
                              ├─▶ billing.py (إعدادات/باقات/اشتراك/إحالة)
                              ├─▶ payments.py (NOWPayments)
                              └─▶ sync_worker.py classes (Mt5Client, BridgeCtl) للتحقق الحي

MT5 على نفس السيرفر عبر Wine (لا يوجد VPS ويندوز منفصل):
  /root/.wine/drive_c/Program Files/MetaTrader 5/terminal64.exe   ← ترمنال البوت (منفذ 8001، خدمة mt5-bridge)
  /root/.wine/drive_c/Program Files/MT5-Monitor/terminal64.exe    ← ترمنال المراقبة (منفذ 8002، خدمة mt5-monitor-bridge، يُشغَّل/يُطفأ عند الحاجة)
  الجسر بينهما: مكتبة mt5linux (نسخة 0.1.9 تحديداً — الأحدث معطوبة، انظر القسم 6)

sync_worker.py: خدمة systemd مستقلة (aw-sync) تُحدّث بيانات الحسابات المقبولة دورياً عبر ترمنال المراقبة (8002)، بالتناوب، بحماية موارد كاملة.
```

### خدمات systemd الفعّالة:
- `aw-backend` — الباك اند (FastAPI/uvicorn)، به `never-stop.conf` drop-in (`Restart=always` + `StartLimitIntervalSec=0`، أي يعيد التشغيل للأبد).
- `mt5-bridge` — جسر Wine/MT5 الخاص بالبوت (منفذ 8001).
- `mt5-monitor-bridge` — جسر Wine/MT5 الخاص بالمزامنة (منفذ 8002)، يُشغَّل/يُطفأ تلقائياً بواسطة `sync_worker.py` (`BridgeCtl` class) عبر `sudo -n systemctl start/stop`.
- `aw-sync` — (تحقق من وجودها فعلياً؛ قد لا تكون مُفعَّلة بعد كخدمة دائمة — راجع القسم 7).

**صلاحية sudo بدون كلمة مرور:** المستخدم الذي يُشغّل الباك اند (`aw` أو `root` — تحقق فعلياً) يحتاج صلاحية `sudo -n systemctl {start,stop,restart} mt5-monitor-bridge` بدون كلمة مرور (موجودة في `/etc/sudoers.d/`) — ضرورية لعمل `BridgeCtl` في `sync_worker.py` وأيضاً استُخدمت مباشرة داخل `register()` في `main.py`.

---

## 4) قاعدة البيانات (Firestore)

### `users/{telegram_id}`
```
telegram_id, username, language (ar|en), nickname, avatar (boy|girl)
mt5_login, mt5_password, mt5_server   ← ملاحظة: كلمة مرور MT5 مخزّنة كنص صريح (قرار مقصود من صاحب المشروع، بلا تشفير)
status: "approved" | "rejected" | (قد لا يوجد status إطلاقاً لو لم يُسجَّل بعد)
rejection_reason, decided_at, created_at
link_fails: [أزمنة يونكس لمحاولات فاشلة، تُنظَّف تلقائياً بعد ساعة] ← لمنع القوة الغاشمة (3 محاولات/ساعة)
subscription: { package_id, package_name_ar, package_name_en, expires_at (يونكس), status: "active" }
referral_code: كود 6 أحرف فريد لكل مستخدم
referred_by: uid المُحيل (إن وُجد)
referral_reward_granted: bool (يمنع منح المكافأة أكثر من مرة)
live: { balance, equity, profit, margin, margin_free, margin_level, credit, leverage, currency }  ← يُحدَّثه sync_worker دورياً، ويُملأ أول مرة مباشرة من register()
sync: { state: "new"|"ok"|..., next_due, fails, first_fail }
report: { ... } ← تقرير الأداء (نمو يومي/أسبوعي/شهري/إجمالي، Win Rate) يُحدَّثه sync_worker
stats: { ... } ← إحصاءات تراكمية خام يستخدمها sync_worker داخلياً (v, wins, losses, pnl_cum, max_dd, ...)
```

### `packages/{auto_id}`
```
name_ar, name_en, price_usd (float), duration_days (int), active (bool), sort_order (int)
price_stars (int, اختياري) ← لو موجود، يظهر خيار الدفع بـ Telegram Stars لهذه الباقة
```

### `payments/{order_id}`  (order_id = "{uid}-{package_id}-{timestamp}")
```
uid, package_id, amount_usd أو amount_stars, method ("nowpayments" ضمنياً أو "stars")
status: "waiting" | "confirming" | ... | "finished"
created_at, confirmed_at, invoice_id (NOWPayments)، telegram_payment_charge_id (Stars)
```

### `blacklist/{mt5_login}`
```
reason, added_at, added_by  ← أي حساب هنا يُرفض تلقائياً في register() (لم تُبنَ واجهة إضافة لها في لوحة التحكم بعد — فقط الباك اند يتحقق منها)
```

### `config/settings` (وثيقة واحدة فقط)
```json
{
  "registration_policy": "both | real | demo",
  "leverage_min": 0,
  "leverage_max": 0,
  "referral_enabled": true,
  "referral_days": 7,
  "kill_switch": false
}
```
القيم 0 لـ leverage_min/max تعني "بلا حد".

---

## 5) الحالة الحالية بالتفصيل — ماذا يعمل الآن فعلياً

### ✅ الباك اند (main.py + billing.py + payments.py) — **مكتمل ومُختبر**
- `/api/register` — **تلقائي بالكامل** الآن: يتحقق من (بالترتيب): حالة approved سابقة → kill_switch → اشتراك نشط → معدّل المحاولات (rate limit) → القائمة السوداء → تكرار رقم الحساب لدى مستخدم آخر → سياسة نوع الحساب المسموح → **تحقق حي فعلي من MT5** (عبر `sync_worker.Mt5Client`/`BridgeCtl` على منفذ 8002) → نطاق الرافعة المسموح → قبول نهائي وكتابة `live` + `sync.state=new`.
  - أخطاء الـ HTTP المُرجَعة (`detail`): `approved`, `registration_paused`, `too_many_attempts`, `account_blacklisted`, `account_already_linked`, `account_type_not_allowed`, `cred`/`srv`/`elig` (فشل توثيق MT5 نفسه)، `leverage_not_allowed`, `verification_temporarily_unavailable` (خطأ مؤقت بالجسر، وليس رفضاً حقيقياً — يجب على الفرونت اند عرض "حاول مجدداً" وليس رسالة رفض نهائية).
  - ⚠️ **أول طلب بعد فترة خمول قد يأخذ حتى 60 ثانية** (إقلاع MT5 من الصفر عبر Wine). الفرونت اند **لم يُحدَّث بعد** لإظهار حالة "جارٍ التحقق..." لهذه المدة الطويلة (كان مصمَّماً على افتراض رد فوري/انتظار أدمن).
- `/api/status` — حالة الطلب (approved/rejected/none) + بيانات `live`/`report` عند approved. **لم يُراجَع بعد** بعد تغيير منطق register إلى تلقائي بالكامل — يُحتمل أنه يحتاج تحديثاً بسيطاً لعرض `subscription` أيضاً.
- تسجيل دخول الأدمن: أمر `/admin` في البوت → رابط + رمز تحقق (صالحان 5 دقائق) → `/api/admin/verify` → كوكي جلسة JWT (`aw_admin`, HttpOnly, Secure, SameSite=Strict, 12 ساعة). **ملاحظة تقنية مهمة:** PyJWT الحديثة تفرض أن `sub` نصّاً (string) — استخدمنا `str(admin_id)` عند الترميز و`int(payload["sub"])` عند فك التشفير، وإلا يفشل بصمت (`InvalidSubjectError`).
- إدارة الباقات: `GET/POST/PUT/DELETE /api/admin/packages`، `GET /api/packages` (عام، نشطة فقط).
- الإعدادات: `GET/PUT /api/admin/settings`.
- إدارة المستخدمين: `GET /api/admin/users` (فلاتر: status, account_type, leverage_min/max, search)، `GET /api/admin/users/{uid}`، `POST /api/admin/users/{uid}/decision` (موافقة/رفض يدوي — لا يزال موجوداً كاحتياطي رغم أن التسجيل صار تلقائياً).
- الدفع: `POST /api/payments/create` (NOWPayments Invoice، يدعم USDT-TRC20/USDT-TON/TON/BTC/... — القائمة الحالية المُفعَّلة في حساب NOWPayments: `BTC, USDTTRC20, DAI, USDTERC20, USDC, USDTBSC, USDTSOL, TON, USDTTON, SOON, NEWTERC20, JETTON`)، و`POST /api/payments/nowpayments-webhook` (يتحقق من التوقيع `x-nowpayments-sig` عبر HMAC-SHA512 على JSON مُرتَّب المفاتيح).
- `POST /api/payments/create-stars` — يستخدم `createInvoiceLink` (وليس `sendInvoice`) لأن الرابط يُفتح داخل الـ Mini App عبر `Telegram.WebApp.openInvoice(url)` بدون مغادرته. **الفرونت اند لم يُربط بهذا بعد.**
- معالجة Stars: `pre_checkout_query` (يجب الرد خلال 10 ثوانٍ عبر `answerPreCheckoutQuery`) و`successful_payment` داخل حدث `message` عادي (وليس نوع تحديث منفصل) — **مُهم:** `allowed_updates` عند تليجرام يجب أن يشمل `pre_checkout_query` (تم ضبطه فعلاً، تحقق: `getWebhookInfo`).
- الإحالة: كود 6 أحرف، مكافأة أيام مجانية (افتراضياً 7 لكل الطرفين) عند أول دفعة ناجحة فقط للمُحال عليه، تُمنح مرة واحدة (`referral_reward_granted`). **لم يُربط بعد** توليد الكود ولا تمرير `referred_by` في تدفق التسجيل الفعلي — الدوال جاهزة في `billing.py` (`ensure_referral_code`, `find_by_referral_code`) لكن **لم تُستدعَ من أي مكان بعد**.
- `/start` احترافي: فيديو/شعار متحرك (يُرفَع مرة واحدة لتليجرام ويُخزَّن `file_id` في `.welcome_logo_id` بجانب `main.py` لإعادة الاستخدام دون رفع متكرر)، نص كامل منفصل بالعربي/الإنجليزي حسب `language_code`.
- Webhook watchdog: خيط خلفي (`_watchdog`) يتحقق كل 5 دقائق أن `getWebhookInfo` سليم ويُصلحه تلقائياً لو انحرف.

### ✅ لوحة تحكم الأدمن (admin/) — **مبنية ومنشورة على `/admin/`**
React + Vite، منشورة عبر nginx على `https://205-209-121-79.sslip.io/admin/`. تصميم داكن بهوية "طرفية تداول" (خلفية `#0F1115`، لون العلامة البرتقالي `#E8963C`، خط Chakra Petch). تحتوي: تسجيل دخول برمز، إحصائيات سريعة (pending/approved/rejected)، فلاتر (حالة/نوع حساب/رافعة/بحث)، جدول (حاسوب)/بطاقات (هاتف)، لوحة تفاصيل منزلقة مع موافقة/رفض يدوي.

**❌ لم تُضَف بعد للوحة التحكم رغم أنها مطلوبة صراحةً من صاحب المشروع:**
- تبويب/شاشة **الباقات** (إنشاء/تعديل/حذف من الواجهة — الـ API جاهز، فقط الواجهة ناقصة).
- تبويب **الإعدادات العامة** (registration_policy, leverage_min/max, kill_switch, referral toggle/days — الـ API جاهز، الواجهة ناقصة).
- تبويب **الإحالات** (الـ API `/api/admin/referrals` جاهز، الواجهة ناقصة).
- **القائمة السوداء** — لا يوجد حتى API لإضافة/إزالة حساب من `blacklist` collection، فقط `register()` يتحقق منها. يحتاج: endpoints + واجهة.
- **سجل المدفوعات** (لا يوجد أصلاً endpoint لعرض `payments` collection في لوحة التحكم).
- مفتاح إيقاف طارئ ظاهر بوضوح (موجود ضمن settings لكن يحتاج واجهة مخصصة/بارزة).
- سجل تدقيق (Audit Log) — غير مبنيّ إطلاقاً لا بالباك اند ولا الواجهة.
- رسالة جماعية (Broadcast) — غير مبنية.
- مراقبة صحة النظام (حالة الجسور، آخر مزامنة) — غير مبنية.

### ⚠️ فرونت اند المستخدم (frontend/) — **يحتاج تحديثاً كبيراً، أهم عمل متبقٍّ**
البنية الحالية (`App.jsx`): `LanguageStep` → `ProfileStep` → `MT5FormStep` → إرسال لـ `/api/register` القديم (كان يتوقع رد `{"status":"pending"}` ثم شاشة انتظار مع polling، أو ردّ 409 لو معلّق/مقبول مسبقاً) → `StatusScreen` (pending/approved/rejected) → `Dashboard.jsx` (تُعرض فقط لو status="approved"، تعرض `live`/`report`).

**كل ما يلي غير مبنيّ إطلاقاً في الفرونت اند ويجب بناؤه من الصفر:**
1. **شاشة اختيار الباقة** (تقرأ `/api/packages`، تعرض السعر/المدة، وزر لكل طريقة دفع متاحة للباقة).
2. **شاشة الدفع**: زر NOWPayments (يفتح `invoice_url` في نافذة/تبويب خارجي أو `Telegram.WebApp.openLink`)، وزر Stars (يستدعي `/api/payments/create-stars` ثم `Telegram.WebApp.openInvoice(invoice_link, callback)`).
3. **بوابة قبل نموذج MT5**: التحقق أن `subscription.status === "active"` و`expires_at > الآن` قبل إظهار `MT5FormStep` أصلاً؛ وإلا توجيهه لشاشة الباقات.
4. **تحديث `MT5FormStep`/منطق الإرسال في `App.jsx`**: `register()` الجديد قد يستغرق حتى 60 ثانية ويُرجع مباشرة `{"status":"approved"}` أو خطأ (وليس `{"status":"pending"}` بعد الآن) — يجب: (أ) إظهار مؤشر تحميل واضح مع رسالة "قد يستغرق حتى دقيقة"، (ب) معالجة كل قيم `detail` الجديدة (`too_many_attempts` → رسالة انتظار، `cred`/`srv`/`elig` → رسالة خطأ واضحة قابلة لإعادة المحاولة فوراً، `verification_temporarily_unavailable` → "حاول مجدداً" وليس رفضاً نهائياً، `leverage_not_allowed`/`account_type_not_allowed`/`account_blacklisted`/`account_already_linked` → رسائل مخصصة).
5. **شاشة الإعدادات (Settings)** كاملة — **غير موجودة إطلاقاً بعد**: عرض الباقة الحالية + الأيام المتبقية، زر "ترقية/تجديد" (يعيد لشاشة الباقات)، **زر إلغاء الربط** (يحتاج endpoint جديد في الباك اند أيضاً — **غير موجود بعد**: شيء مثل `POST /api/unlink` يُصفّر `status`/`mt5_*` بشرط عدم إساءة الاستخدام، مع فترة تبريد Cooldown كما اتُّفق عليه سابقاً مع صاحب المشروع لكن **لم يُبنَ بعد**)، تبديل اللغة يدوياً، عرض/نسخ **كود الإحالة الخاص به** ورابط دعوة (`https://t.me/awfxapp_bot?start={referral_code}`) — **لا يوجد حالياً استقبال لـ `startPayload` في `/start` لتفعيل `referred_by` عند التسجيل عبر رابط الإحالة! هذا مفقود بالكامل في الباك اند أيضاً.**

---

### ✅ إضافات الدفعة الثانية (TON، الخدش، البث اللحظي، النبضة...)

**وحدات جديدة في `backend/`:** `ton.py` (TON Connect + تحقق on-chain عبر toncenter)، `retry.py` (tenacity)، `reminders.py` (تذكير التجديد)، `heartbeat.py` (نبضة ترمنال الروبوت)، `rewards.py` (بطاقات الخدش).

**مسارات جديدة:**
- `POST /api/payments/create-ton` · `POST /api/payments/ton-check` · `POST /api/payments/ton-webhook` (سر عبر `?secret=` أو `X-Webhook-Secret` أو `Authorization: Bearer`) · `GET /api/tonconnect-manifest.json`
- `GET /api/stream?init_data=` — بث SSE لحالة الحساب/الاشتراك (نفس شكل `/api/status`).
- `POST /api/onboarding/complete` · `POST /api/scratch/claim` · `POST /api/scratch/reveal` · `GET /api/rewards` · `POST /api/rewards/redeem`
- `POST /api/payments/create` و`create-stars` و`create-ton` تقبل `reward_id` اختياريًا (خصم/أيام مجانية).

**Firestore:** `webhook_inbox` (كل webhook وارد يُحفظ ثم يُعالَج في الخلفية ويُعاد كل دقيقة حتى ينجح)، `ton_txs` (معاملة واحدة لطلب واحد)، `scratch_cards/{uid}_{event}`، `phone_claims/{sha256}`، `system_events` (انقطاع/تنبيه/إعادة تشغيل/تعافي ترمنال الروبوت). حقول مستخدم جديدة: `trial_checked`, `trial_expires_at`, `trial`, `scratch_pending`, `achievements`, `phone_verified`, `subscription.reminders`. حقل باقة جديد: `price_ton`.

**إعدادات `config/settings` جديدة:** `trial_enabled` (افتراضيًا false)، `trial_days` (3..7)، `trial_max_lot`.

**متغيرات `.env` الجديدة (كلها اختيارية):**
- `TON_WALLET_ADDRESS` (بدونه يختفي الدفع بـ TON)، `TONCENTER_API_KEY`، `TONCENTER_API`، `TON_WEBHOOK_SECRET`، `TON_PAYMENT_WINDOW_SEC`
- `HEARTBEAT_ENABLED`، `HEARTBEAT_HOST`، `HEARTBEAT_PORT` (8001)، `HEARTBEAT_INTERVAL_SEC` (5)، `HEARTBEAT_ALERT_SEC` (15)، `HEARTBEAT_RESTART_COOLDOWN_SEC`، `HEARTBEAT_SERVICE` (mt5-bridge)
- `REWARD_TTL_HOURS` (24، الحد 72)، `REWARD_SECRET`، `PHONE_HASH_SALT`، `SSE_POLL_SEC` (5)، `N8N_HEALTH_URL`، `SYSTEM_DEGRADED_MS`، `RETRY_ATTEMPTS`، `RETRY_MAX_WAIT_SEC`

**ملاحظات تشغيل:** يجب تشغيل `pip install -r requirements.txt` (أُضيف `tenacity`) و`npm install` في `frontend/` (أُضيف `@tonconnect/ui` و`canvas-confetti`). قاعدة sudoers تسمح الآن أيضًا بـ `systemctl restart mt5-bridge` (يُعاد تثبيتها عبر `aw-update`). دالة `billing.auto_trade_allowed(user, volume)` جاهزة للاستدعاء قبل كل صفقة آلية، لكن كود الروبوت نفسه ليس في هذا الريبو.

### ✅ الدفعة الثالثة (واجهة التسويق والتحليلات والتحكم بالمكافآت)

- **الواجهة:** شريط علوي بشعار صغير (الشعار الكبير فقط في شاشة اللغة الأولى)، شريط سفلي بأيقونات SVG موحّدة (`Icon.jsx`) يضم: الرئيسية، التحليلات، الإحالة، المكافآت، الباقات، الإعدادات. زر التقييم صار صفًا في الإعدادات. شاشة الاسم/الصورة/النوع تظهر مرة واحدة فقط (بعد فكّ الربط يعود المستخدم مباشرة لخطوة MT5).
- **التحليلات (`Analytics.jsx`):** مؤشرات (إجمالي الأرباح، الإحالات الناجحة، معدل التحويل)، رسم أسبوعي/شهري ومنحنى تراكمي (Recharts)، مستوى الإحالة وقسم تحفيزي، الأقسام المنقولة من الرئيسية (نسبة الربح، الأداء، الحساب)، وعرض توضيحي متحرك لمحرك n8n (`N8nFlow.jsx`).
- **الإحالة (`Referral.jsx` + `story.js`):** مستويات (برونزي→أسطوري حسب الإحالات الناجحة، `tiers.js`)، بطاقة قصة 9:16 تُرسم على الجهاز (Canvas + رمز QR عبر مكتبة `qrcode`)، نصوص جاهزة بوسوم، Web Share API مع أزرار تلجرام/واتساب/X/فيسبوك.
- **الأيقونات:** من الحزمة المرسلة في `frontend/src/assets/icons/` (مصغّرة): صور الفتى/الفتاة، محفظة TON، العملة، شارات المستويات، كرة البرق لمحرك n8n، صورة الأصدقاء، GIF الاحتفال، أيقونات المنصات.
- **الخلفية:** `GET /api/analytics` (المدعوون/الناجحة/الدافعون/التحويل). `STATS_VERSION=3` في المزامنة: يعيد قراءة السجل مرة واحدة لكل حساب لبناء `report.series` (ربح كل يوم، آخر 120 يومًا).
- **لوحة الأدمن:** صفحات جديدة: المكافآت والكوبونات (تشغيل/إيقاف، المحفزات، الصلاحية، اشتراط الهاتف، جدول الجوائز والأوزان والاحتمالات، منح بطاقة أو كوبون يدويًا، تمديد/إلغاء)، الباقات (أسعار $/⭐/TON)، الإعدادات (التسجيل، الرافعة، الإحالة، الفترة التجريبية). تُحفظ إعدادات المكافآت في `config/rewards`. مسارات: `GET/PUT /api/admin/rewards/config`، `GET /api/admin/rewards/cards`، `POST /api/admin/rewards/grant`، `POST /api/admin/rewards/{id}/revoke|extend`.

### ✅ الدفعة الرابعة (الباقات، الدفع المخصّص، المشاركة، الترتيب، الشروط)

- **الشعار:** `frontend/src/assets/logo-wordmark.png` (خلفية شفافة)، يسارًا دائمًا في كل اللغات.
- **Terms & Risks:** صف موافقة قبل ربط MT5 + صفحة الشروط (`TermsRisks.jsx`). الخادم يرفض الربط بلا `terms_accepted` (`400 terms_required`) ويحفظ `users.terms {version, accepted_at}` (`TERMS_VERSION` في main.py).
- **الباقات:** حقول جديدة `tagline_ar/en`, `features_ar/en` (قائمة)، `featured`. استيراد Starter/Pro/Premium من لوحة الأدمن (`POST /api/admin/packages/seed`). بعد "اشترك" تظهر خطوة طرق الدفع.
- **سعر TON متغيّر:** يُحسب من `price_usd` بسعر TON الحالي (CoinGecko ثم TonAPI احتياطًا، مخزّن 5 دقائق). حقل `price_ton` اليدوي لم يعد مستخدمًا.
- **بوابة العملات الرقمية المخصّصة:** `POST /api/payments/create` مع `pay_currency` ينشئ دفعة NOWPayments مباشرة (عنوان + مبلغ + memo) وتعرضها `CryptoPay.jsx`. `POST /api/payments/status` يسأل NOWPayments (كل 10ث كحد أدنى) ويفعّل عند `finished`. العملات: `NP_CURRENCIES` في `.env`.
- **المشاركة:** `POST /api/share/create` يرفع صورتي القصة (9:16) والمنشور (1:1) إلى `backend/media/share/` (تُحذف بعد 30 يومًا)، ويعيد رابطًا عامًا للقصة (Telegram `shareToStory`) وصفحة منشور بوسوم Open Graph (`/api/share/p/{id}`) لفيسبوك/X/واتساب/تلجرام. يلزم `client_max_body_size 6m` في nginx (يضيفه `aw-update` تلقائيًا).
- **ترتيب الأسبوع:** `GET /api/leaderboard` (`leaderboard.py`): المستخدمون الحقيقيون بنمو أسبوعهم الفعلي + منافسون محاكاة اختياريون (`leaderboard_sim`, `leaderboard_sim_count` في الإعدادات) يظهرون دائمًا بشارة "محاكاة".
- **إصلاح سجل الفواتير:** الاستعلام لم يعد يجمع `where` مع `order_by` (كان يتطلب فهرسًا مركّبًا غير موجود).

### ✅ الدفعة الخامسة (لوحة الأدمن الاحترافية، الصلاحيات، سجل العمليات، الخوادم، الملف الشخصي)

- **الصلاحيات (`backend/admin_access.py`):** أدوار owner (من `ADMIN_IDS`) / manager / support / viewer، وأعضاء الفريق في `config/staff.members`. الوسيط `AdminGuard` في main.py يفحص كل طلب لمسارات `/api/admin/*` و`/api/system/status` حسب `PERMS` (قراءة/كتابة لكل قسم) ويرد `403 forbidden_role`.
- **سجل العمليات:** كل طلب كتابة (POST/PUT/DELETE) + تسجيل الدخول يُحفظ في `audit_log` مع IP (X-Forwarded-For/X-Real-IP) والجهاز (من User-Agent) وملخّص آمن للمحتوى (تُخفى التوكنات/الرموز/الصور). `GET /api/admin/audit`.
- **لوحة CEO:** `GET /api/admin/ceo` أرقام بلغة بسيطة (المستخدمون، الاشتراكات، الإيرادات بالدولار — TON × سعره وقت الدفع، طرق الدفع، الباقات، منحنى 30 يومًا).
- **مركز التحكم:** تشغيل/إيقاف كل طريقة دفع (`pay_ton_enabled`, `pay_crypto_enabled`, `pay_stars_enabled` — الخادم يرفض الطريقة الموقوفة `403 payment_method_disabled`)، رابط الدعم `support_url`، إعلان أعلى الرئيسية.
- **خوادم MT5 (`backend/servers.py`):** لا توجد API عامة لقائمة خوادم الوسطاء؛ السجل يتعلّم من كل ربط ناجح (موثّق) + استيراد الأدمن + مزامنة الحسابات المربوطة. `GET /api/servers?q=` للاقتراح أثناء الكتابة مع نوع demo/real.
- **الصور:** `POST /api/profile/photo` (JPEG ≤ 400KB) و`POST /api/admin/leaderboard/photo`، تُخدم من `/api/media/avatars/`. المنافسون المحاكاة يُستوردون من ملف CSV/JSON (`name,gender,tier,photo`).
- **TON Connect:** تُفصل المحفظة بعد كل معاملة أو بعد 3 دقائق خمول ليختار المستخدم محفظة أخرى لاحقًا.
- **تنسيق الأرقام:** `frontend/src/format.js` مصدر واحد لكل الأرقام والتواريخ (أرقام لاتينية دائمًا).

### ✅ الدفعة السادسة (الدعم الذكي، الإشعارات، نافذة التحديثات، محفظة TON، لوحة بمستوى الشركات)

- **متغيرات .env جديدة:** `ANTHROPIC_API_KEY` (المساعد الذكي؛ بدونه يعمل الدعم بقاعدة المعرفة + التحويل للبشري)، `ADMIN_OTP_BOT_TOKEN` (اختياري: بوت مستقل لرموز التحقق، الافتراضي البوت الرئيسي). ثبّت `anthropic` من requirements.txt.
- **الدعم الذكي (`backend/support.py`):** بوت الدعم = توكن مستقل من اللوحة (يُضبط webhook تلقائيًا على `/api/support-webhook`) أو البوت الرئيسي. تذاكر `support_tickets` + رسائل `support_messages`، أولوية تلقائية (حرجة/متوسطة/بسيطة)، رد أولي فوري برقم التذكرة والوقت المتوقع، قاعدة معرفة `support_kb` أولًا، تصعيد تلقائي بعد `escalation_threshold` ردود بلا حل إلى `support_chat_id` (يرد بـ Reply)، CSAT، حد رسائل، كشف اللغة. System Prompt قابل للتعديل من اللوحة.
- **الإصلاح الذاتي (قائمة بيضاء فقط، كل تنفيذ في `auto_fix_log`):** `resync_account` (sync.state→new)، `recheck_payment` (يسأل المزوّد؛ لا تفعيل بلا تأكيده)، `reset_stuck_link` (pending أقدم من 30د→none)، `set_language`. لا يستطيع المساعد تعديل الاشتراكات أو الأرصدة أو كلمات المرور أو الحذف.
- **الأخطاء:** `POST /api/errors` يسجّل في `client_errors` برقم `ERR-XXXXXX`؛ أخطاء الخادم غير المتوقعة تُسجَّل تلقائيًا وتعيد `ref`. زر "تواصل مع الدعم" في كل رسالة خطأ يفتح بوت الدعم بـ `/start err_<ref>` فيبدأ المساعد بتفاصيل الخطأ، وينسخ التفاصيل للحافظة كبديل.
- **الإشعارات (`notifications.py`):** `notifications` (تلقائية: دفع، إيداع/سحب، صفقات، أمان، حالة الحساب، التذاكر) + `broadcasts` من الأدمن (مستخدم/فلتر/الجميع، مع خيار إرسال عبر البوت). المقروء: `users.notif_seen_at`.
- **نافذة "ما الجديد" (`announcements.py`):** مجموعة `announcements` مع التكرار والجمهور والتواريخ و"لا تظهر مرة أخرى"؛ نافذة الإطلاق الافتراضية تُنشأ عند أول تشغيل.
- **محفظة TON من اللوحة (`tonadmin.py`):** الرصيد والتحويلات الواردة؛ تغيير المحفظة/المهلة/التشغيل/التحويل يتطلب OTP عبر البوت ويُسجَّل في `ton_admin_log`. الخادم لا يحتفظ بالمفتاح الخاص: التحويل يوقّعه الأدمن عبر TON Connect. تشغيل/إيقاف TON لم يعد ممكنًا من الإعدادات العامة (OTP فقط).
- **ترتيب الأسبوع:** البيانات المؤكَّدة ثابتة (قيم أساسية `base_usd` أو مولَّدة حتميًا من الاسم)، محرك محاكاة بفاصل ونطاق يحددهما الأدمن، ووضع `group` بعدد ثابت يضم المستخدم نفسه. سطر توضيحي واحد أسفل القائمة بدل علامة ⚡.
- **اللوحة:** أقسام جديدة (المالية، الدعم، الإشعارات، النمو)، تنبيهات فورية `GET /api/admin/alerts` كل 20ث، وضع نهاري/ليلي، بحث وفلاتر في السجلات.

## 6) دروس مُستفادة بصعوبة — لا تكرر نفس الأخطاء

1. **حزمة `mt5linux` الحديثة (1.1.1) معطوبة مع Python الحديث**: تحتوي f-strings ممتدة على عدة أسطر (غير صالحة نحوياً إلا من Python 3.12+)، وبنيتها الداخلية تغيّرت بالكامل لتعتمد "container runtime" (Docker) بدل الاستدعاء المباشر. **الحل الذي نجح: تثبيت `mt5linux==0.1.9` تحديداً** على الجانبين (Wine وLinux)، مع `--no-deps` على جانب لينكس (لأن اعتمادياته القديمة `numpy==1.21.4` لا تدعم بايثون 3.14 الحديث). الصيغة الصحيحة للتشغيل في هذا الإصدار: **يُشغَّل من بايثون-لينكس** (وليس من داخل Wine!) هكذا: `python -m mt5linux "<مسار python.exe داخل Wine>" --host 0.0.0.0 -p <منفذ> -w wine -s <مجلد مؤقت>`. خدمة `mt5-bridge`/`mt5-monitor-bridge` في systemd يجب أن تُشغَّل كـ **root** (وليس `sudo -u aw`) لأن بيئة Wine (`WINEPREFIX=/root/.wine`) خاصة بـ root تحديداً — تشغيلها بمستخدم آخر يُنشئ بيئة Wine فارغة جديدة بلا MT5.
2. **PyJWT**: يفرض أن `sub` في الـ payload نصّاً وليس رقماً (`InvalidSubjectError` بصمت لو رقم) — دائماً `str(admin_id)` عند encode، `int(...)` عند decode.
3. **علامات اقتباس في `.env`**: لو أضفت قيمة بعلامتي اقتباس (`KEY="value"`) عبر `nano` بالخطأ، تصبح علامتا الاقتباس **جزءاً من القيمة نفسها** عند القراءة بـ `python-dotenv`/`os.getenv` (بخلاف bash الذي يزيلها). أي مفتاح API يُرفض بغرابة ("Invalid api key") تحقق من هذا أولاً.
4. **اختبار متغيرات `.env` يدوياً**: `python -c "..."` مباشرة **لا يقرأ `.env` تلقائياً** إلا إن حمّلته صراحة (`set -a && source .env && set +a`) قبله في نفس السطر.
5. **`sudo -E` غير مدعوم** على إعدادات هذا السيرفر تحديداً — لا تستخدمه، مرّر أو صدّر المتغيرات بطريقة أخرى.
6. **القرص شبه ممتلئ باستمرار** (كان عند 88% مبكراً في المشروع) — راقب `df -h /root` بانتظام، خصوصاً بعد أي تثبيت جديد داخل Wine.
7. **تعديل ملفات كبيرة عن بعد**: الطريقة الموثوقة الوحيدة التي نجحت مراراً هي: التحقق من وجود نص المرساة (anchor) **بدقة حرفية** (`assert old_text in content`) قبل الاستبدال عبر سكربت بايثون (heredoc)، **أبداً** لا تفترض محتوى ملف بعيد دون التحقق أولاً (اطلب من المستخدم إرسال الملف الفعلي عبر `tar` + رفعه للمحادثة عند الشك).
8. **لا تُنفّذ أوامر متعددة الأسطر وتقطعها بـ Ctrl+C في المنتصف** — الرموز (توكنات) أحادية الاستخدام (`/admin` مثلاً) تُستهلك عند أول نجاح جزئي حتى لو قُطع الأمر بعده.
9. **`allowed_updates` عند `setWebhook`**: أي نوع حدث تليجرام جديد تحتاجه (مثل `pre_checkout_query`) **يجب إضافته صراحة** في القائمة، وإلا فلن يصل مهما كان الكود جاهزاً لاستقباله.
10. **خدمة `sync_worker.py` منفصلة تماماً عن ترمنال البوت** (منفذ 8001 مقابل 8002) عمداً — لا تخلط بينهما أبداً عند إضافة تحقق حي جديد في أي endpoint.

---

## 7) أول ما يجب التحقق منه قبل أي عمل جديد

نفّذ هذه على السيرفر واعرض النتائج للمستخدم/تأكد بنفسك قبل أي تعديل:
```bash
systemctl status aw-backend mt5-bridge mt5-monitor-bridge aw-sync --no-pager | head -60
cd /home/aw/aw-mini-app/backend && grep -E '^NOWPAYMENTS_|^ADMIN_SESSION_SECRET=|^WEBAPP_URL=' .env | sed 's/=.*/=***/'
curl -s http://127.0.0.1:8000/api/packages
curl -s http://127.0.0.1:8000/api/admin/settings -b /tmp/admin_cookie.txt 2>/dev/null || echo "لا توجد جلسة أدمن محفوظة، سجّل دخولاً جديداً عبر /admin"
```
وتحقّق فعلياً هل خدمة `aw-sync` (تشغيل `sync_worker.py` بشكل دائم) موجودة ومُفعَّلة أصلاً — لم نؤكد إنشاءها بشكل قاطع في هذا التسليم.

---

## 8) أولوية العمل المقترحة للمتابعة

1. تحديث `frontend/App.jsx` بالكامل ليتوافق مع `register()` الجديد (تحميل طويل + كل رسائل الخطأ الجديدة) — **الأهم، بدونه لا يمكن لأي مستخدم التسجيل فعلياً الآن**.
2. بناء شاشة الباقات + الدفع (NOWPayments + Stars) في الفرونت اند.
3. بناء شاشة الإعدادات (باقة حالية، إلغاء ربط، إحالة، لغة) + endpoint `/api/unlink` الناقص بالكامل بالباك اند.
4. ربط `referred_by` فعلياً: قراءة `ctx.startPayload` في `/start`، `find_by_referral_code`، حفظه في مستند المستخدم عند أول ظهور له قبل التسجيل.
5. إكمال لوحة التحكم: تبويبات الباقات/الإعدادات/الإحالات/القائمة السوداء.
6. إضافات اختيارية لاحقة: سجل مدفوعات، Broadcast، Audit Log، مراقبة صحة النظام.

---

## 9) الدفعة 7 — متغيرات وإعدادات جديدة

| المتغير (.env) | الغرض |
|---|---|
| `GEMINI_API_KEY` | الذكاء الاصطناعي للدعم (Gemini Flash، مجاني من aistudio.google.com). يمكن بدلًا منه وضع المفتاح من «الدعم ← القناة والإعدادات» (يُحفظ مشفّرًا). |
| `SECRETS_KEY` | مفتاح تشفير الأسرار في قاعدة البيانات (توكن بوت الدعم، مفتاح Gemini، جلسات تلجرام). إن لم يُضبط يُستخدم `WEBHOOK_SECRET`. **لا تغيّره بعد الضبط** وإلا تعذّر فك الأسرار المحفوظة. |
| `MINIAPP_SHORT_NAME` | اسم الـ Mini App المختصر في BotFather لتوليد روابط `t.me/<bot>/<short>?startapp=gift_…` (اختياري). |

- **حسابات تلجرام الحقيقية للدعم**: تتطلب `telethon` (في requirements) و API ID/Hash من my.telegram.org. تُضاف من «الدعم ← حسابات تلجرام». الرد يكون من الحساب النشط فقط، مع انتقال تلقائي للحساب التالي حسب الأولوية.
- **مراقبة التشغيل**: `aw-uptime.timer` كل دقيقة يفحص الـ API والرابط العام و`aw-sync` و`mt5-bridge`، ويرسل تنبيه تلجرام للأدمن بعد فشلين متتاليين ورسالة عند العودة.
- **التحديث الفوري للأجهزة المفتوحة**: كل بناء يولّد `version.json`؛ التطبيق يتحقق كل 45 ثانية ويعيد التحميل تلقائيًا عند الخمول (nginx: `index.html` و`version.json` بلا تخزين مؤقت).
- **أيقونات WebM**: ضع الملفات في `frontend/src/assets/anim/` بنفس اسم المستوى أو نوع الجائزة (انظر README هناك).
- **الأتمتة (رسائل الاسترجاع)** تبدأ موقوفة؛ تُفعَّل من «النمو والتسويق ← الأتمتة والاسترجاع».
