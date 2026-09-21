#!/bin/bash
# نقطة الدخول الوحيدة:
#   • سيرفر جديد  → يثبّت كل شيء (يسألك عن الأسرار مرة واحدة).
#   • مثبّت مسبقًا → يحدّثه من GitHub (نفس aw-update).
#  --reinstall : يفرض التثبيت الكامل حتى لو وُجد .env
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
need_root

if [ -f "$APP_DIR/backend/.env" ] && [ "${1:-}" != "--reinstall" ]; then
  exec bash "$HERE/update.sh" "$@"
fi

# ───────────── الأسئلة ─────────────
ask() { # ask VAR "السؤال" [افتراضي] [secret]
  local var=$1 q=$2 def=${3:-} secret=${4:-} val=""
  [ -z "${!var:-}" ] || return 0
  [ -t 0 ] || die "القيمة $var مطلوبة، مرّرها كمتغير بيئة عند التشغيل"
  if [ "$secret" = secret ]; then read -rsp "$q: " val; echo; else read -rp "$q${def:+ [$def]}: " val; fi
  val=${val:-$def}
  [ -n "$val" ] || die "القيمة مطلوبة: $var"
  printf -v "$var" '%s' "$val"
}

say "معلومات التثبيت (Enter لقبول القيمة بين القوسين)"
PUBLIC_IP=$(curl -4fsS -m 8 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
if [ ! -s "$TOKEN_FILE" ]; then ask GH_TOKEN "GitHub token (قراءة فقط لهذا المستودع)" "" secret; fi
ask DOMAIN "الدومين (اتركه ليُنشأ دومين مجاني من الـ IP)" "${PUBLIC_IP//./-}.sslip.io"
ask BOT_TOKEN "توكن البوت من BotFather" "" secret
ask CHANNEL_ID "رقم قناة الأدمن (يبدأ بـ -100)"
ask ADMIN_IDS "آيديات الأدمن (مفصولة بفاصلة)"
ask FIREBASE_JSON "مسار ملف مفتاح Firebase على هذا السيرفر" "/root/firebase-adminsdk.json"
LE_EMAIL="${LE_EMAIL:-}"
# مفاتيح الدفع اختيارية: اتركها فارغة الآن وأضفها لاحقًا في backend/.env (الدفع بالنجوم لا يحتاجها)
NOWPAYMENTS_API_KEY="${NOWPAYMENTS_API_KEY:-}"
NOWPAYMENTS_IPN_SECRET="${NOWPAYMENTS_IPN_SECRET:-}"
if [ -t 0 ] && [ -z "$NOWPAYMENTS_API_KEY" ]; then
  read -rsp "مفتاح NOWPayments API (Enter للتخطي): " NOWPAYMENTS_API_KEY; echo
  [ -z "$NOWPAYMENTS_API_KEY" ] || { read -rsp "سر NOWPayments IPN: " NOWPAYMENTS_IPN_SECRET; echo; }
fi

[ -f "$FIREBASE_JSON" ] || die "لم أجد $FIREBASE_JSON. ارفعه أولًا من جهازك:  scp firebase.json root@$PUBLIC_IP:$FIREBASE_JSON"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); assert d.get("type")=="service_account"' "$FIREBASE_JSON" \
  || die "ملف Firebase ليس مفتاح حساب خدمة صالحًا"

say "التحقق من البوت والقناة"
ME=$(curl -fsS -m 10 "https://api.telegram.org/bot$BOT_TOKEN/getMe" 2>/dev/null) || die "توكن البوت غير صالح"
ok "البوت: @$(printf '%s' "$ME" | python3 -c 'import sys,json; print(json.load(sys.stdin)["result"]["username"])')"
curl -fsS -m 10 "https://api.telegram.org/bot$BOT_TOKEN/getChat?chat_id=$CHANNEL_ID" >/dev/null 2>&1 \
  && ok "القناة موجودة والبوت يصل إليها" \
  || warn "تعذّر الوصول للقناة $CHANNEL_ID. تأكد أن البوت مشرف فيها (سنكمل)"

# ───────────── النظام ─────────────
say "تثبيت الحزم الأساسية"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq nginx python3 python3-venv python3-pip git curl ca-certificates ufw \
  certbot python3-certbot-nginx openssl >/dev/null
if ! command -v node >/dev/null 2>&1 || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 18 ]; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash - >/dev/null
  apt-get install -y -qq nodejs >/dev/null
fi
ok "node $(node -v) · python $(python3 -V | cut -d' ' -f2)"

say "جدار الحماية"
SSH_PORT=$(ss -tlnp 2>/dev/null | awk '/sshd/ {n=split($4,a,":"); print a[n]; exit}')
ufw allow "${SSH_PORT:-22}/tcp" >/dev/null
ufw allow 'Nginx Full' >/dev/null
ufw --force enable >/dev/null
ok "مفتوح: SSH (${SSH_PORT:-22}) + 80/443 فقط"

# ───────────── الكود ─────────────
say "تنزيل المشروع"
id "$APP_USER" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$APP_USER" >/dev/null
chmod 711 "/home/$APP_USER"
save_token
git_setup
if [ ! -d "$APP_DIR/.git" ]; then
  [ ! -e "$APP_DIR" ] || [ -z "$(ls -A "$APP_DIR")" ] || die "$APP_DIR موجود وليس مستودعًا. انقله أولًا"
  git clone -q --branch "$BRANCH" "$REPO_URL" "$APP_DIR" || die "فشل الاستنساخ. تحقق من التوكن وصلاحيته لهذا المستودع"
fi
git -C "$APP_DIR" remote set-url origin "$REPO_URL"
chown -R "$APP_USER:" "$APP_DIR"
ok "$(git -C "$APP_DIR" log -1 --pretty='%h %s')"

# ───────────── الأسرار ─────────────
say "ملف الإعدادات"
B="$APP_DIR/backend"
install -o "$APP_USER" -g "$APP_USER" -m 600 "$FIREBASE_JSON" "$B/firebase-adminsdk.json"
[ -f "$B/.env" ] || install -o "$APP_USER" -g "$APP_USER" -m 600 /dev/null "$B/.env"
env_default "$B/.env" BOT_TOKEN "$BOT_TOKEN"
env_default "$B/.env" CHANNEL_ID "$CHANNEL_ID"
env_default "$B/.env" WEBHOOK_SECRET "$(openssl rand -hex 32)"
env_default "$B/.env" ADMIN_IDS "$ADMIN_IDS"
env_default "$B/.env" FRONTEND_ORIGIN "https://$DOMAIN"
env_default "$B/.env" WEBAPP_URL "https://$DOMAIN"
env_default "$B/.env" FIREBASE_KEY_PATH "firebase-adminsdk.json"
env_default "$B/.env" ADMIN_SESSION_SECRET "$(openssl rand -hex 32)"
[ -z "$NOWPAYMENTS_API_KEY" ] || env_default "$B/.env" NOWPAYMENTS_API_KEY "$NOWPAYMENTS_API_KEY"
[ -z "$NOWPAYMENTS_IPN_SECRET" ] || env_default "$B/.env" NOWPAYMENTS_IPN_SECRET "$NOWPAYMENTS_IPN_SECRET"
ok "$B/.env (صلاحية 600)"

# ───────────── بايثون والواجهة ─────────────
say "بيئة بايثون"
[ -x "$B/.venv/bin/python" ] || as_app python3 -m venv "$B/.venv"
as_app "$B/.venv/bin/pip" install -q --upgrade pip
pip_install "$B"
run_tests "$APP_DIR" || die "فشلت اختبارات المشروع بعد التثبيت"
ok "الحزم والاختبارات"

say "بناء الواجهة ولوحة الأدمن"
build_frontend
build_admin
ok "$APP_DIR/frontend/dist · $APP_DIR/admin/dist"

# ───────────── الخدمات و nginx و HTTPS ─────────────
say "الخدمات"
install_units
install_sudoers
install_cli
systemctl enable --now aw-backend
health && ok "الـ API يعمل" || die "الـ API لم يبدأ. راجع: journalctl -u aw-backend -n 40"

say "nginx و HTTPS"
render "$APP_DIR/deploy/templates/nginx.conf.tpl" > /etc/nginx/sites-available/aw
ln -sf /etc/nginx/sites-available/aw /etc/nginx/sites-enabled/aw
rm -f /etc/nginx/sites-enabled/default
nginx -t >/dev/null 2>&1 || die "إعداد nginx غير صالح"
systemctl reload nginx
CERT_MAIL=(--register-unsafely-without-email)
[ -z "$LE_EMAIL" ] || CERT_MAIL=(-m "$LE_EMAIL")
if certbot --nginx -d "$DOMAIN" --redirect -n --agree-tos "${CERT_MAIL[@]}" >/dev/null 2>&1; then
  ok "شهادة HTTPS جاهزة لـ $DOMAIN"
else
  warn "فشلت شهادة HTTPS. تأكد أن $DOMAIN يشير لهذا السيرفر والمنفذ 80 مفتوح، ثم شغّل: certbot --nginx -d $DOMAIN --redirect"
fi

systemctl restart aw-backend
sleep 8
webhook_report

cat <<DONE

$(printf '\033[1;32m✅ اكتمل التثبيت\033[0m')

الخطوات المتبقية (يدوية مرة واحدة):
  1) @BotFather ← Bot Settings ← Menu Button ← الرابط:  https://$DOMAIN
  2) أرسل /start لبوتك وتأكد أن الترحيب يصل. ولوحة الأدمن: أرسل /admin للبوت (رابط + رمز).
     (إن تخطّيت مفاتيح NOWPayments: أضفها في $B/.env ثم systemctl restart aw-backend)
  3) لتفعيل المزامنة الحية (MT5): شغّل  bash $APP_DIR/deploy/install-mt5.sh   (سيرفر جديد فقط)
     ثم  bash $APP_DIR/deploy/install-monitor.sh

أوامر ستحتاجها:
  aw-update   تحديث من GitHub (أضف --force لإعادة البناء)
  aw-doctor   فحص شامل لحالة كل شيء
DONE
