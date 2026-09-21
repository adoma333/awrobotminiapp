[Unit]
Description=MT5 Linux Bridge Server (mt5linux) — ترمنال الروبوت
After=network.target aw-xvfb.service
Wants=aw-xvfb.service

[Service]
User=root
Environment=WINEPREFIX=/root/.wine
Environment=DISPLAY=:10.0
WorkingDirectory=/root
ExecStart=__APP_DIR__/backend/.venv/bin/python -m mt5linux "/root/.wine/drive_c/Program Files/Python310/python.exe" --host 127.0.0.1 -p 8001 -w wine -s /tmp/mt5linux_srv
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
