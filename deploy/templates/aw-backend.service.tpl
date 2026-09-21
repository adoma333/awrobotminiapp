[Unit]
Description=AW Mini App backend
After=network.target
StartLimitIntervalSec=0

[Service]
User=__APP_USER__
WorkingDirectory=__APP_DIR__/backend
EnvironmentFile=__APP_DIR__/backend/.env
ExecStart=__APP_DIR__/backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
