# AW Robot

منصة داخل تلجرام (Mini App) لربط حسابات MT5 ومتابعتها مباشرة: المستخدم يشترك، يربط حسابه فيُتحقق منه تلقائيًا عبر MT5، ثم يرى لوحة بأرقامه وإحصاءاته. ولوحة أدمن للإدارة.

```
Mini App (React)  ─┐
لوحة الأدمن (React) ─┼─ nginx ─ FastAPI ─ Firestore
                    │                └─ Telegram Bot API (webhook)
aw-sync (كل ساعة) ──┴─ ترمنال المراقبة (Wine + mt5linux) ← يقرأ حسابات العملاء بالتناوب
```

## الهيكل

| المجلد | المحتوى |
|---|---|
| `backend/` | `main.py` (الـ API + webhook)، `billing.py` (الباقات والاشتراك والإحالة)، `payments.py` (NOWPayments)، `sync_worker.py` (المزامنة)، الاختبارات |
| `frontend/` | تطبيق المستخدم: لغة ← ملف ← باقات ودفع ← ربط الحساب ← لوحة وإعدادات |
| `admin/` | لوحة الأدمن (`/admin/`) |
| `deploy/` | التثبيت والتحديث والفحص (`setup.sh`، `update.sh`، `doctor.sh`…) |
| `docs/HANDOFF.md` | ملف التسليم: قرارات المشروع والدروس والأولويات |

## سيرفر جديد: أمر واحد

جهّز قبلها: دومين (أو اتركه ليُنشأ دومين مجاني من الـ IP)، وملف مفتاح Firebase على السيرفر (`scp firebase.json root@IP:/root/firebase-adminsdk.json`)، وبوتًا وقناة أدمن. ثم بصفة root:

```bash
export GH_TOKEN="github_pat_..." && rm -rf /tmp/aw-src && mkdir -p /tmp/aw-src \
 && curl -fsSL -H "Authorization: Bearer $GH_TOKEN" https://api.github.com/repos/adoma333/awrobotminiapp/tarball/main \
    | tar xz -C /tmp/aw-src --strip-components=1 && bash /tmp/aw-src/deploy/setup.sh
```

يسألك عن توكن البوت والقناة والأدمن، يثبّت كل شيء، يتحقق من الاختبارات، يبني الواجهتين، ويجلب شهادة HTTPS. بعده خطوتان يدويتان: رابط الميني آب في BotFather، ثم `/start` للبوت.
التوكن يكفيه صلاحية **Contents: Read-only** لهذا المستودع فقط، ويُحفظ في `/etc/aw/github_token` (600).

## سيرفر قائم: الأمر نفسه

الأمر أعلاه يكتشف أن المشروع مثبّت فيحوّل تلقائيًا إلى التحديث. أول مرة يربط المجلد بالمستودع (لا يمسّ `.env` ولا مفتاح Firebase ولا `.venv`). بعدها فقط:

```bash
aw-update            # تحديث من GitHub
aw-update --force    # إعادة بناء وتشغيل حتى لو لا جديد
aw-doctor            # فحص شامل للقراءة فقط
```

التحديث آمن: يختبر النسخة الجديدة في مجلد مؤقت **قبل** تفعيلها، وبعد التفعيل يفحص الـ API ويتراجع تلقائيًا للنسخة السابقة إن لم يعمل. ويرفض العمل إن كان القرص شبه ممتلئ.

## سير العمل اليومي

```bash
git add -A && git commit -m "وصف التعديل" && git push    # على جهازك
aw-update                                                 # على السيرفر
```
أو من GitHub: تبويب **Actions ← deploy ← Run workflow** (يتطلب سرّي `VPS_HOST` و`VPS_SSH_KEY`، اختياري).
كل push يشغّل اختبارات الباك اند وبناء الواجهتين وفحص السكربتات تلقائيًا.

## الأسرار

لا تُرفع أبدًا (مستثناة في `.gitignore`): `backend/.env`، مفتاح Firebase، أي `*.pem`/`*.key`. القالب: `backend/.env.example`.
كلمات مرور MT5 محفوظة كما هي (بدون تشفير، قرار المالك) ولذلك القناة والدخول للوحة الأدمن للأدمن الموثوقين فقط.

## طبقة MT5

`deploy/install-monitor.sh` يركّب ترمنال مراقبة منفصل عن ترمنال الروبوت (لا يُنسخ إليه أي روبوت، والتداول الآلي معطّل فيه)، وجسره يعمل عند الحاجة فقط. القفل المشترك (`/tmp/aw-mt5.lock`) يمنع تداخل حسابين على الترمنال نفسه بين الـ API والمزامنة.
`deploy/install-mt5.sh` (Wine + MT5 على سيرفر جديد): **غير مختبر على سيرفر حقيقي**، راجعه قبل الاعتماد عليه.

## الاختبارات

```bash
cd backend && python test_backend.py && python test_sync.py
cd frontend && npm ci && npm run build      # وكذلك admin/
```
