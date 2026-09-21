#!/bin/bash
# مكتبة مشتركة لسكربتات النشر. تُحمَّل بـ source ولا تُشغَّل وحدها.
# shellcheck disable=SC2034  # متغيرات تُستخدم في السكربتات التي تحمّل هذا الملف

APP_USER="${APP_USER:-aw}"
APP_DIR="${APP_DIR:-/home/$APP_USER/aw-mini-app}"
REPO="${AW_REPO:-adoma333/awrobotminiapp}"
BRANCH="${AW_BRANCH:-main}"
REPO_URL="${AW_REPO_URL:-https://github.com/$REPO.git}"
TOKEN_FILE="${AW_TOKEN_FILE:-/etc/aw/github_token}"
MON_SERVICE="mt5-monitor-bridge"

say()  { printf '\n\033[1;33m▶ %s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✔\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m⚠ %s\033[0m\n' "$*"; }
die()  { printf '\n\033[31m❌ %s\033[0m\n' "$*" >&2; exit 1; }

# AW_TEST=1 يعطّل لمس النظام (systemd/sudoers/nginx) لأغراض الاختبار فقط
is_test() { [ -n "${AW_TEST:-}" ]; }
need_root() { [ "$(id -u)" = 0 ] || is_test || die "شغّله بصلاحية root (sudo -i)"; }

as_app() {
  if [ "$(id -un)" = "$APP_USER" ]; then "$@"; else sudo -u "$APP_USER" -H "$@"; fi
}

# ───────────── GitHub ─────────────
save_token() {
  [ -n "${GH_TOKEN:-}" ] || return 0
  mkdir -p "$(dirname "$TOKEN_FILE")"
  (umask 077; printf '%s' "$GH_TOKEN" > "$TOKEN_FILE")
  chmod 600 "$TOKEN_FILE"
}

# مصادقة git عبر متغيرات البيئة فلا يظهر التوكن في قائمة العمليات
git_setup() {
  if [ -s "$TOKEN_FILE" ]; then
    local b64
    b64=$(printf 'x-access-token:%s' "$(cat "$TOKEN_FILE")" | base64 | tr -d '\n')
    export GIT_CONFIG_COUNT=1
    export GIT_CONFIG_KEY_0="http.https://github.com/.extraheader"
    export GIT_CONFIG_VALUE_0="AUTHORIZATION: basic $b64"
  fi
  export GIT_TERMINAL_PROMPT=0
  git config --global --get-all safe.directory 2>/dev/null | grep -qx '\*' \
    || git config --global --add safe.directory '*'
}

# ───────────── ملفات الإعداد ─────────────
env_default() { # يضيف المفتاح فقط إن لم يكن موجودًا (لا يستبدل قيمة موجودة)
  local f=$1 k=$2 v=$3
  grep -q "^$k=" "$f" 2>/dev/null || printf '%s=%s\n' "$k" "$v" >> "$f"
}
env_get() { grep -m1 "^$1=" "$2" 2>/dev/null | cut -d= -f2- | tr -d "\"' "; }

render() {
  sed -e "s#__APP_DIR__#$APP_DIR#g" -e "s#__APP_USER__#$APP_USER#g" -e "s#__DOMAIN__#${DOMAIN:-}#g" "$1"
}

# ───────────── النظام ─────────────
install_units() {
  is_test && return 0
  local t="$APP_DIR/deploy/templates"
  render "$t/aw-backend.service.tpl" > /etc/systemd/system/aw-backend.service
  render "$t/aw-sync.service.tpl" > /etc/systemd/system/aw-sync.service
  rm -rf /etc/systemd/system/aw-backend.service.d /etc/systemd/system/aw-sync.service.d
  systemctl daemon-reload
}

install_sudoers() { # يسمح لمستخدم التطبيق بتشغيل/إطفاء جسر المراقبة فقط
  is_test && return 0
  local tmp; tmp=$(mktemp)
  printf '%s ALL=(root) NOPASSWD: /usr/bin/systemctl restart %s, /usr/bin/systemctl start %s, /usr/bin/systemctl stop %s, /bin/systemctl restart %s, /bin/systemctl start %s, /bin/systemctl stop %s\n' \
    "$APP_USER" "$MON_SERVICE" "$MON_SERVICE" "$MON_SERVICE" "$MON_SERVICE" "$MON_SERVICE" "$MON_SERVICE" > "$tmp"
  visudo -cf "$tmp" >/dev/null || { rm -f "$tmp"; die "قاعدة sudoers غير صالحة"; }
  install -m 440 "$tmp" /etc/sudoers.d/aw-sync
  rm -f "$tmp"
}

install_cli() { # أوامر قصيرة: aw-update و aw-doctor
  is_test && return 0
  printf '#!/bin/bash\nexec bash %s/deploy/setup.sh "$@"\n' "$APP_DIR" > /usr/local/bin/aw-update
  printf '#!/bin/bash\nexec bash %s/deploy/doctor.sh "$@"\n' "$APP_DIR" > /usr/local/bin/aw-doctor
  chmod +x /usr/local/bin/aw-update /usr/local/bin/aw-doctor
}

# ───────────── البناء والاختبار ─────────────
pip_install() { # pip_install <مجلد backend>
  local pip="$APP_DIR/backend/.venv/bin/pip"
  as_app "$pip" install -q -r "$1/requirements.txt" || return 1
  # mt5linux بلا اعتمادياته: حزمته تفرض numpy==1.21.4 القديمة
  [ ! -f "$1/requirements-mt5.txt" ] || as_app "$pip" install -q --no-deps -r "$1/requirements-mt5.txt"
}

run_tests() { # run_tests <مجلد يحوي backend/>
  local d=$1 t
  for t in test_backend.py test_sync.py; do
    ( cd "$d/backend" && as_app "$APP_DIR/backend/.venv/bin/python" "$t" > "$d/$t.out" 2>&1 ) \
      || { tail -20 "$d/$t.out"; return 1; }
  done
}

npm_build() { # npm_build <frontend|admin>
  local d="$APP_DIR/$1"
  [ -d "$d" ] || return 0
  if [ ! -d "$d/node_modules" ] || [ "${FORCE_NPM_CI:-0}" = 1 ]; then
    ( cd "$d" && as_app npm ci --no-audit --no-fund --loglevel=error )
  fi
  ( cd "$d" && as_app npm run build --silent >/dev/null )
}

build_frontend() {
  local f="$APP_DIR/frontend"
  [ -f "$f/.env" ] || as_app sh -c "echo 'VITE_API_URL=' > '$f/.env'"
  npm_build frontend
}

build_admin() { npm_build admin; }

# القرص شبه ممتلئ أخطر ما يهدد السيرفر (بناء الواجهة والسجلات وWine): نرفض التحديث إن نفدت المساحة
disk_guard() {
  local free_mb
  free_mb=$(df -Pm "$APP_DIR" | awk 'NR==2 {print $4}')
  if [ "$free_mb" -lt 500 ]; then
    die "المساحة الحرة ${free_mb}MB فقط. نظّف القرص أولًا (مثلًا: journalctl --vacuum-size=200M && apt-get clean) ثم أعد المحاولة"
  fi
  [ "$free_mb" -ge 1500 ] || warn "المساحة الحرة ${free_mb}MB قليلة، راقب القرص (aw-doctor)"
}

# تسجيل الحساب يتحقق مباشرة عبر MT5 وقد يتجاوز 60ث (مهلة nginx الافتراضية): نرفعها إلى 180ث
tune_nginx() {
  local f="${NGINX_CONF_OVERRIDE:-}"
  if [ -z "$f" ]; then
    is_test && return 0
    f=$(grep -l 'location /api/' /etc/nginx/sites-enabled/* 2>/dev/null | head -1)
  fi
  [ -n "$f" ] || return 0
  grep -q 'proxy_read_timeout' "$f" && return 0
  cp "$f" "$f.aw-bak"
  python3 - "$f" <<'PY' || { cp "$f.aw-bak" "$f"; warn "تعذّر تعديل مهلة nginx"; return 0; }
import re, sys
p = sys.argv[1]
s = open(p).read()
m = re.search(r"location /api/ \{\n", s)
assert m, "لا يوجد location /api/"
s = s[:m.end()] + "        proxy_read_timeout 180s;\n        proxy_send_timeout 180s;\n" + s[m.end():]
open(p, "w").write(s)
PY
  if [ -n "${NGINX_CONF_OVERRIDE:-}" ] || { nginx -t >/dev/null 2>&1 && systemctl reload nginx; }; then
    ok "مهلة nginx للـ API رُفعت إلى 180ث"
  else
    cp "$f.aw-bak" "$f"
    warn "إعداد nginx الجديد غير صالح، أعدت الأصلي"
  fi
}

health() {
  local _
  for _ in $(seq 1 25); do
    curl -fsS -m 3 http://127.0.0.1:8000/ >/dev/null 2>&1 && return 0
    sleep 1
  done
  return 1
}

webhook_report() {
  local t; t=$(env_get BOT_TOKEN "$APP_DIR/backend/.env")
  [ -n "$t" ] || return 0
  curl -fsS -m 10 "https://api.telegram.org/bot$t/getWebhookInfo" 2>/dev/null | python3 -c '
import sys, json
r = json.load(sys.stdin).get("result", {})
print("  webhook :", r.get("url") or "غير مضبوط", "| معلّقة:", r.get("pending_update_count"),
      "| آخر خطأ:", r.get("last_error_message") or "لا يوجد")' || warn "تعذّر قراءة حالة webhook"
}
