[Unit]
Description=AW MT5 sync worker
After=network.target mt5-monitor-bridge.service
Wants=mt5-monitor-bridge.service
StartLimitIntervalSec=0

[Service]
User=__APP_USER__
WorkingDirectory=__APP_DIR__/backend
EnvironmentFile=__APP_DIR__/backend/.env
ExecStart=__APP_DIR__/backend/.venv/bin/python -u sync_worker.py
Restart=always
RestartSec=3
Nice=10

[Install]
WantedBy=multi-user.target
