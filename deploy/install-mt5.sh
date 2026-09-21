#!/bin/bash
# تثبيت طبقة MT5 على سيرفر جديد: شاشة افتراضية + Wine + MetaTrader 5 + Python للويندوز + جسر mt5linux.
#
# ⚠️ هذا السكربت مكتوب بحسب توثيق mt5linux ولم يُختبر على سيرفر حقيقي.
#    تثبيت Wine قد يحتاج تدخلًا يدويًا (مهلات، اختلاف إصدارات). شغّله داخل tmux/screen وراجع سجله.
#    يرفض العمل إن كان MT5 مثبّتًا أصلًا حتى لا يمسّ سيرفرًا يعمل.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
need_root

MT5_DIR="/root/.wine/drive_c/Program Files/MetaTrader 5"
PY_EXE='C:\Program Files\Python310\python.exe'
LOG=/var/log/aw-mt5-install.log

if [ -f "$MT5_DIR/terminal64.exe" ]; then
  ok "MT5 مثبّت مسبقًا في $MT5_DIR: لن ألمس شيئًا."
  exit 0
fi
[ -x "$APP_DIR/backend/.venv/bin/python" ] || die "ثبّت المشروع أولًا (deploy/setup.sh)"

say "الحزم (Wine + شاشة افتراضية)"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq wine wine64 xvfb winbind wget cabextract >>"$LOG" 2>&1 || die "فشل تثبيت Wine. راجع $LOG"

say "الشاشة الافتراضية :10"
render "$APP_DIR/deploy/templates/aw-xvfb.service.tpl" > /etc/systemd/system/aw-xvfb.service
systemctl daemon-reload
systemctl enable --now aw-xvfb
sleep 2

export WINEPREFIX=/root/.wine WINEARCH=win64 DISPLAY=:10.0 WINEDEBUG=-all

say "تهيئة Wine"
wineboot -i >>"$LOG" 2>&1 || warn "wineboot أرجع تحذيرًا (نتابع)"

say "تثبيت Python 3.10 للويندوز داخل Wine"
wget -q -O /tmp/py310.exe https://www.python.org/ftp/python/3.10.11/python-3.10.11-amd64.exe
timeout 600 wine /tmp/py310.exe /quiet InstallAllUsers=1 'TargetDir=C:\Program Files\Python310' \
  PrependPath=0 Include_launcher=0 Include_test=0 >>"$LOG" 2>&1 || warn "مثبّت Python أرجع تحذيرًا (نتحقق بعده)"
wine "$PY_EXE" --version >>"$LOG" 2>&1 || die "Python لم يُثبَّت داخل Wine. راجع $LOG"
wine "$PY_EXE" -m pip install --no-warn-script-location MetaTrader5 rpyc >>"$LOG" 2>&1 \
  || die "فشل تثبيت MetaTrader5/rpyc داخل Wine. راجع $LOG"
ok "Python + MetaTrader5 + rpyc داخل Wine"

say "تنزيل وتثبيت MetaTrader 5 (قد يأخذ عدة دقائق)"
wget -q -O /tmp/mt5setup.exe https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe
timeout 900 wine /tmp/mt5setup.exe /auto >>"$LOG" 2>&1 || warn "مثبّت MT5 أرجع تحذيرًا (ننتظر ظهور الملفات)"
for _ in $(seq 1 60); do [ -f "$MT5_DIR/terminal64.exe" ] && break; sleep 5; done
[ -f "$MT5_DIR/terminal64.exe" ] || die "لم يظهر terminal64.exe. ثبّت MT5 يدويًا ثم أعد التشغيل. راجع $LOG"
wineserver -k >/dev/null 2>&1 || true
ok "MetaTrader 5 مثبّت"

say "جسر mt5linux للروبوت (منفذ 8001 محلي فقط)"
render "$APP_DIR/deploy/templates/mt5-bridge.service.tpl" > /etc/systemd/system/mt5-bridge.service
systemctl daemon-reload
systemctl enable --now mt5-bridge
sleep 5
ss -ltn | grep -q '127.0.0.1:8001' && ok "الجسر يعمل على 127.0.0.1:8001" || warn "الجسر لم يفتح المنفذ. راجع: journalctl -u mt5-bridge -n 30"

cat <<DONE

✅ اكتملت طبقة MT5.
الخطوات المتبقية (يدوية):
  • شغّل ترمنال الروبوت وسجّل الدخول لحساب الروبوت (سطح مكتب بعيد أو x11vnc على :10).
  • ثم ركّب ترمنال المراقبة:  bash $APP_DIR/deploy/install-monitor.sh
سجل هذا التثبيت: $LOG
DONE
