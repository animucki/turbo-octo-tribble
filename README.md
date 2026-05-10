# turbo-octo-tribble
Today's mission: track down one of GVB's bidirectional Siemens Combino trams

Initialize after cloning with:

```shell
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Systemd service `/etc/systemd/system/turbo-octo-tribble.service`:
```ini
[Unit]
Description=GVB 14G Tram Monitor
After=network.target

[Service]
Type=simple
User=bxa
WorkingDirectory=/home/bxa/turbo-octo-tribble
ExecStart=/home/bxa/turbo-octo-tribble/.venv/bin/python basicsubscriber.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Daily restart timer `/etc/systemd/system/turbo-octo-tribble-restart.timer`:
```ini
[Unit]
Description=Restart tram monitor daily at 6 AM

[Timer]
OnCalendar=*-*-* 06:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

Restart service `/etc/systemd/system/turbo-octo-tribble-restart.service`:
```ini
[Unit]
Description=Restart tram monitor service

[Service]
Type=oneshot
ExecStart=/bin/systemctl restart turbo-octo-tribble.service
```

Then, to activate:
```shell
sudo systemctl daemon-reload
sudo systemctl enable --now turbo-octo-tribble.service
sudo systemctl enable --now turbo-octo-tribble-restart.timer

# verify timer is scheduled
systemctl list-timers turbo-octo-tribble-restart.timer
```