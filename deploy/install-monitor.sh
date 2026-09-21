#!/bin/bash
# ترمنال المراقبة المنفصل + جسره (منفذ 8002 محلي). لا يمسّ ترمنال الروبوت ولا mt5-bridge.
# يتطلب أن يكون MT5 مثبّتًا وأن تكون خدمة mt5-bridge موجودة (تُشتقّ منها خدمة المراقبة).
# آمن للتكرار.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
. "$HERE/lib.sh"
need_root

SRC="/root/.wine/drive_c/Program Files/MetaTrader 5"
DST="/root/.wine/drive_c/Program Files/MT5-Monitor"
PORT=8002
BRIDGE_UNIT=/etc/systemd/system/mt5-bridge.service
MON_UNIT="/etc/systemd/system/$MON_SERVICE.service"

[ -d "$SRC" ] || die "لم أجد MT5 في: $SRC (ثبّته أولًا: deploy/install-mt5.sh)"
[ -f "$BRIDGE_UNIT" ] || die "لم أجد خدمة mt5-bridge لأشتق منها خدمة المراقبة"

say "فحص الذاكرة"
MEM_MB=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
echo "  الذاكرة الكلية: ${MEM_MB}MB"
if [ "$MEM_MB" -lt 2500 ] && [ -z "$(swapon --show --noheadings)" ] && [ "${SKIP_SWAP:-0}" != 1 ]; then
  echo "  لا يوجد Swap والذاكرة قليلة: أنشئ ملف 2GB"
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

say "ترمنال المراقبة (نظيف: بلا روبوتات)"
if [ ! -f "$DST/terminal64.exe" ]; then
  mkdir -p "$DST/Config"
  # ملفات البرنامج فقط: لا MQL5 ولا Profiles، فلا يُنسخ أي روبوت أبدًا
  find "$SRC" -maxdepth 1 -type f -exec cp -a {} "$DST"/ \;
  if [ -f "$SRC/Config/servers.dat" ]; then cp -a "$SRC/Config/servers.dat" "$DST/Config/"; fi
fi
mkdir -p "$DST/Config"
cat > "$DST/Config/common.ini" <<'INI'
[Experts]
Enabled=0
AllowLiveTrading=0
AllowDllImport=0
INI
ok "$DST"

say "خدمة جسر المراقبة"
sed -E \
  -e 's/^Description=.*/Description=MT5 Monitor Bridge (AW sync)/' \
  -e 's/--host [0-9.]+/--host 127.0.0.1/' \
  -e "s/ -p 8001/ -p $PORT/" \
  -e 's#/tmp/mt5linux_srv([^_a-zA-Z0-9]|$)#/tmp/mt5linux_srv_monitor\1#' \
  "$BRIDGE_UNIT" > "$MON_UNIT"
grep -q -- "-p $PORT" "$MON_UNIT"          || die "لم أستطع ضبط المنفذ. راجع ExecStart في $MON_UNIT"
grep -q "mt5linux_srv_monitor" "$MON_UNIT" || die "لم أستطع ضبط مجلد الجسر. راجع $MON_UNIT"
MAXMEM=$(( MEM_MB * 55 / 100 ))
# إن زاد الاستهلاك يُقتل ترمنال المراقبة أولًا لا الروبوت
sed -i "/^\[Service\]/a OOMScoreAdjust=800\nMemoryMax=${MAXMEM}M\nNice=5" "$MON_UNIT"
ok "$MON_UNIT (سقف ذاكرة ${MAXMEM}MB)"

install_units
install_sudoers
systemctl daemon-reload
systemctl enable "$MON_SERVICE" >/dev/null 2>&1 || true

cat <<DONE

✅ جاهز. الخدمة aw-sync تُشغّل جسر المراقبة عند الحاجة وتُطفئه وهو خامل.
جرّب حسابًا واحدًا بدون كتابة أي شيء:
  cd $APP_DIR/backend && sudo -u $APP_USER .venv/bin/python sync_worker.py --probe
وعندما ينجح:
  systemctl enable --now aw-sync && journalctl -u aw-sync -f
DONE
