#!/bin/bash
# Startup script of the web-server VM. GCE runs it as root on every boot.
# It installs the code and registers service 1 as a systemd service, so the server
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
/opt/hw/venv/bin/pip install -q -r /opt/hw/hw4/service1/requirements.txt

cat > /etc/systemd/system/hw4-web.service <<UNIT
[Unit]
Description=HW4 service 1 (web server)
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/hw/venv/bin/python -u /opt/hw/hw4/service1/server.py
Restart=always
# run as an unprivileged throw-away user that may still bind port 80
DynamicUser=yes
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable hw4-web
systemctl restart hw4-web
