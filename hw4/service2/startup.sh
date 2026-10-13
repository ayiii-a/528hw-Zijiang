#!/bin/bash
# Startup script of the service-2 VM. GCE runs it as root on every boot.
# It installs the code and registers service 2 as a systemd service, so the reporter
# starts right after the VM is created, restarts if it crashes, and comes back after a reboot.
set -euo pipefail

apt-get update -q
apt-get install -y -q git python3-venv

if [ -d /opt/hw/.git ]; then
    git -C /opt/hw pull -q
else
    git clone -q https://github.com/ayiii-a/528hw-Zijiang.git /opt/hw
fi
python3 -m venv /opt/hw/venv
/opt/hw/venv/bin/pip install -q -r /opt/hw/hw4/service2/requirements.txt

cat > /etc/systemd/system/hw4-reporter.service <<UNIT
[Unit]
Description=HW4 service 2 (forbidden request reporter)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/hw/venv/bin/python -u /opt/hw/hw4/service2/reporter.py
Restart=always
RestartSec=5
# run as an unprivileged throw-away user
DynamicUser=yes

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable hw4-reporter
systemctl restart hw4-reporter
