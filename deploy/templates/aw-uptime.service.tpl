[Unit]
Description=AW uptime monitor (external health checks + Telegram alerts)
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=__APP_DIR__/backend/.env
Environment=AW_UPTIME_STATE=/var/lib/aw-uptime/state.json
ExecStart=/usr/bin/python3 __APP_DIR__/backend/uptime_monitor.py
TimeoutStartSec=60
