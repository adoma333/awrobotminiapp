[Unit]
Description=Virtual display :10 for MT5 (Wine)
After=network.target

[Service]
ExecStart=/usr/bin/Xvfb :10 -screen 0 1280x800x24 -nolisten tcp
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
