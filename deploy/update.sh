#!/bin/bash
# تحديث السيرفر من GitHub بأمر واحد (aw-update).
#  • أول مرة على سيرفر قائم: يربط المجلد بالمستودع (لا يمسّ .env ولا مفتاح Firebase ولا .venv).
#  • يختبر النسخة الجديدة في مجلد مؤقت قبل تفعيلها؛ فإن فشل شيء لا يتغيّر شيء.
#  • بعد التفعيل يفحص صحة الـ API، وإن فشل يتراجع تلقائيًا للنسخة السابقة.
#  --force : يعيد البناء والتشغيل حتى لو لا جديد.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
need_root

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

[ -d "$APP_DIR/backend" ] || die "المشروع غير مثبّت في $APP_DIR. للتثبيت الأول شغّل deploy/setup.sh"
[ -x "$APP_DIR/backend/.venv/bin/python" ] || die "لم أجد البيئة $APP_DIR/backend/.venv"

disk_guard
save_token
git_setup

BK=/root/aw-backup-$(date +%Y%m%d-%H%M%S)
mkdir -p "$BK"
tar czf "$BK/code-before.tgz" -C "$APP_DIR" --ignore-failed-read \
  backend/main.py backend/sync_worker.py frontend/src deploy 2>/dev/null || true
ok "نسخة احتياطية: $BK"
backup_db "$BK"

cd "$APP_DIR"
if [ ! -d .git ]; then
  say "ربط المجلد بالمستودع لأول مرة"
  git init -q -b "$BRANCH"
  git remote add origin "$REPO_URL"
fi
git remote set-url origin "$REPO_URL"

OLD=$(git rev-parse -q --verify HEAD 2>/dev/null || true)
[ -z "$OLD" ] || git diff HEAD > "$BK/local-changes.diff" 2>/dev/null || true

say "جلب آخر نسخة"
git fetch -q origin "$BRANCH" || die "تعذّر الجلب من $REPO_URL (تحقق من التوكن أو الاتصال)"
NEW=$(git rev-parse "origin/$BRANCH")
if [ -n "$OLD" ] && [ "$OLD" = "$NEW" ] && [ "$FORCE" = 0 ]; then
  ok "أنت على آخر نسخة ($(git rev-parse --short HEAD)). لا شيء لتحديثه."
  if ! db_is_local && [ -f "$APP_DIR/backend/migrate_sqlite.py" ]; then  # نقل لم يكتمل سابقًا (حد Firebase): نكمله الآن
    migrate_db
    systemctl restart aw-backend
    if systemctl is-enabled --quiet aw-sync 2>/dev/null; then systemctl restart aw-sync; fi
    health && ok "الـ API يعمل" || die "الـ API لا يستجيب. راجع: journalctl -u aw-backend -n 40"
  fi
  exit 0
fi

if [ -n "$OLD" ]; then CHANGED=$(git diff --name-only "$OLD" "$NEW"); else CHANGED="__first_time__"; fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
git archive "origin/$BRANCH" | tar -x -C "$TMP"
chown -R "$APP_USER:" "$TMP"

say "الحزم"
pip_install "$TMP/backend" || die "فشل تثبيت الحزم. لم أغيّر شيئًا"
ok "الحزم جاهزة"

say "اختبار النسخة الجديدة قبل تفعيلها"
run_tests "$TMP" || die "فشل اختبار. لم أغيّر شيئًا"
ok "الاختبارات نجحت"

say "تفعيل النسخة $(git rev-parse --short "origin/$BRANCH")"
git checkout -q -f -B "$BRANCH" "origin/$BRANCH"
git branch -q --set-upstream-to="origin/$BRANCH" "$BRANCH" 2>/dev/null || true
chown -R "$APP_USER:" "$APP_DIR"

changed_dir() { # هل تغيّر مجلد (أو لم يُبنَ بعد)؟
  [ "$FORCE" = 1 ] || [ "$CHANGED" = "__first_time__" ] || [ ! -f "$APP_DIR/$1/dist/index.html" ] \
    || printf '%s\n' "$CHANGED" | grep -q "^$1/"
}
BUILT_FRONT=0
BUILT_ADMIN=0
build_if_changed() { # build_if_changed <dir> <الدالة> <العلم> <عنوان>
  local dir=$1 fn=$2 flag=$3 title=$4
  [ -d "$APP_DIR/$dir" ] || return 0
  changed_dir "$dir" || return 0
  say "$title"
  FORCE_NPM_CI=0
  if [ "$FORCE" = 1 ] || printf '%s\n' "$CHANGED" | grep -q "^$dir/package"; then FORCE_NPM_CI=1; fi
  export FORCE_NPM_CI
  "$fn" || die "فشل $title. للتراجع: cd $APP_DIR && git checkout -f ${OLD:-<commit>}"
  printf -v "$flag" '%s' 1
  ok "$dir جاهز"
}
build_if_changed frontend build_frontend BUILT_FRONT "بناء الواجهة"
build_if_changed admin build_admin BUILT_ADMIN "بناء لوحة الأدمن"

install_units
install_sudoers
install_cli
tune_nginx

migrate_db

say "إعادة تشغيل الخدمات"
rollback() {
  warn "فشل الفحص الصحي: أتراجع إلى النسخة السابقة"
  [ -n "$OLD" ] || die "لا توجد نسخة سابقة للتراجع إليها. النسخة الاحتياطية: $BK"
  git checkout -q -f -B "$BRANCH" "$OLD"
  chown -R "$APP_USER:" "$APP_DIR"
  systemctl restart aw-backend || true
  if [ "$BUILT_FRONT" = 1 ]; then build_frontend || true; fi
  if [ "$BUILT_ADMIN" = 1 ]; then build_admin || true; fi
  die "تراجعت إلى $(git rev-parse --short "$OLD"). راجع: journalctl -u aw-backend -n 40"
}
systemctl restart aw-backend
if systemctl is-enabled --quiet aw-sync 2>/dev/null; then systemctl restart aw-sync; fi
health || rollback
ok "الـ API يعمل"

webhook_report
printf '\n\033[1;32m✅ تم التحديث:\033[0m %s\n' "$(git log -1 --pretty='%h %s')"
