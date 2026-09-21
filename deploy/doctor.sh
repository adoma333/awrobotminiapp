#!/bin/bash
# aw-doctor: فحص شامل للقراءة فقط. لا يغيّر شيئًا ولا يطبع أسرارًا.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"

PASS=0; WARN=0; FAIL=0
good() { PASS=$((PASS+1)); ok "$*"; }
meh()  { WARN=$((WARN+1)); warn "$*"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31m✖ %s\033[0m\n' "$*"; }

ENV="$APP_DIR/backend/.env"

say "الخدمات"
for s in aw-backend aw-sync nginx; do
  if systemctl is-active --quiet "$s"; then good "$s يعمل"; else bad "$s متوقف  ← systemctl status $s"; fi
done
if systemctl list-unit-files 2>/dev/null | grep -q '^mt5-bridge.service'; then
  systemctl is-active --quiet mt5-bridge && good "mt5-bridge (ترمنال الروبوت) يعمل" || meh "mt5-bridge متوقف"
fi
if systemctl is-active --quiet "$MON_SERVICE"; then good "$MON_SERVICE يعمل الآن (يُطفأ تلقائيًا عند الخمول)"; else good "$MON_SERVICE مُطفأ (طبيعي: يعمل عند الحاجة فقط)"; fi

say "الـ API و webhook"
if curl -fsS -m 4 http://127.0.0.1:8000/ >/dev/null 2>&1; then good "الـ API يرد"; else bad "الـ API لا يرد على 127.0.0.1:8000"; fi
T=$(env_get BOT_TOKEN "$ENV")
if [ -n "$T" ]; then
  INFO=$(curl -fsS -m 10 "https://api.telegram.org/bot$T/getWebhookInfo" 2>/dev/null || true)
  if [ -n "$INFO" ]; then
    printf '%s' "$INFO" | python3 -c '
import sys, json, time
r = json.load(sys.stdin).get("result", {})
url, pend, err = r.get("url"), r.get("pending_update_count", 0), r.get("last_error_message")
age = (time.time() - r["last_error_date"]) / 60 if r.get("last_error_date") else None
print("  url:", url or "غير مضبوط", "| معلّقة:", pend)
sys.exit(0 if url and not (err and age is not None and age < 15) else 3)' \
      && good "webhook سليم" || bad "webhook غير مضبوط أو فيه أخطاء حديثة (الحارس الذاتي يعيد ضبطه كل 5 دقائق)"
  else
    meh "تعذّر الاتصال بتلجرام"
  fi
else
  bad "BOT_TOKEN غير موجود في $ENV"
fi

say "الإعدادات (أسماء المفاتيح فقط)"
for k in BOT_TOKEN CHANNEL_ID WEBHOOK_SECRET ADMIN_IDS WEBAPP_URL FIREBASE_KEY_PATH; do
  [ -n "$(env_get "$k" "$ENV")" ] && good "$k" || bad "$k ناقص"
done
for k in ADMIN_SESSION_SECRET NOWPAYMENTS_API_KEY NOWPAYMENTS_IPN_SECRET; do
  [ -n "$(env_get "$k" "$ENV")" ] && good "$k" || meh "$k غير مضبوط (الميزة المرتبطة به معطّلة)"
done
[ -f "$APP_DIR/admin/dist/index.html" ] && good "لوحة الأدمن مبنية (/admin/)" || meh "لوحة الأدمن غير مبنية (aw-update --force)"
[ -f "$APP_DIR/frontend/dist/index.html" ] && good "واجهة المستخدم مبنية" || bad "واجهة المستخدم غير مبنية"
KEYFILE="$APP_DIR/backend/$(env_get FIREBASE_KEY_PATH "$ENV")"
[ -f "$KEYFILE" ] && good "ملف Firebase موجود" || bad "ملف Firebase غير موجود: $KEYFILE"
PERM=$(stat -c %a "$ENV" 2>/dev/null || echo "?")
[ "$PERM" = 600 ] && good ".env بصلاحية 600" || meh ".env بصلاحية $PERM (الأفضل 600)"

say "المنافذ (يجب أن تكون محلية فقط)"
for p in 8000 8001 8002; do
  L=$(ss -tln 2>/dev/null | awk -v p=":$p" '$4 ~ p"$" {print $4}' | head -1)
  if [ -z "$L" ]; then good "المنفذ $p غير مفتوح الآن"
  elif printf '%s' "$L" | grep -qE '^(127\.0\.0\.1|\[::1\])'; then good "المنفذ $p محلي فقط ($L)"
  else bad "المنفذ $p مكشوف على $L  ← غيّر --host إلى 127.0.0.1 وتأكد من ufw"; fi
done

say "شهادة HTTPS"
CERT=$(find /etc/letsencrypt/live -name cert.pem 2>/dev/null | head -1)
if [ -n "$CERT" ]; then
  END=$(openssl x509 -enddate -noout -in "$CERT" | cut -d= -f2)
  DAYS=$(( ($(date -d "$END" +%s) - $(date +%s)) / 86400 ))
  [ "$DAYS" -gt 14 ] && good "تنتهي بعد $DAYS يومًا (تجديد تلقائي)" || bad "تنتهي بعد $DAYS يومًا فقط"
else
  meh "لا توجد شهادة Let's Encrypt"
fi

say "الموارد"
MEM=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
[ "$MEM" -gt 250 ] && good "الذاكرة المتاحة ${MEM}MB" || meh "الذاكرة المتاحة ${MEM}MB فقط"
for r in cpu io; do
  V=$(awk -F'avg10=' 'NR==1 {split($2,a," "); print int(a[1])}' "/proc/pressure/$r" 2>/dev/null)
  [ -n "$V" ] && { [ "$V" -lt 70 ] && good "ضغط $r: ${V}%" || meh "ضغط $r مرتفع: ${V}%"; }
done
DISK=$(df --output=pcent / | tail -1 | tr -dc '0-9')
[ "$DISK" -lt 85 ] && good "القرص ممتلئ ${DISK}%" || meh "القرص ممتلئ ${DISK}%"

say "آخر نشاط للمزامنة"
journalctl -u aw-sync -n 4 --no-pager 2>/dev/null | cut -c1-150 | sed 's/^/  /'

say "النسخة المثبّتة"
git -C "$APP_DIR" log -1 --pretty='  %h  %s  (%cr)' 2>/dev/null || meh "المجلد غير مربوط بـ git (شغّل aw-update)"

printf '\n%s ناجح · %s تنبيه · %s فشل\n' "$PASS" "$WARN" "$FAIL"
[ "$FAIL" -eq 0 ]
