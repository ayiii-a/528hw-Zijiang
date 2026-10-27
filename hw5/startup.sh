#!/bin/bash
# Startup script of both HW5 VMs. Compute Engine runs it as root at every boot.
# The metadata key "role" tells what the VM runs: "web" (service 1) or "reporter" (service 2).
# All the work happens on the first boot only; the systemd service it installs starts by
# itself on every later boot.
set -euo pipefail

if [ -f /var/log/startup_already_done ]; then
    echo "Startup script already ran once. Skipping."
    exit 0
fi

ROLE=$(curl -sf -H "Metadata-Flavor: Google" \
    http://metadata.google.internal/computeMetadata/v1/instance/attributes/role)
case "$ROLE" in
    web)      SERVICE=hw5-web;      APP=service1/server.py
              CAPS="AmbientCapabilities=CAP_NET_BIND_SERVICE" ;;   # lets it bind port 80
    reporter) SERVICE=hw5-reporter; APP=service2/reporter.py; CAPS="" ;;
    *)        echo "unknown role: $ROLE" >&2; exit 1 ;;
esac

apt-get update -q
apt-get install -y -q git python3-venv
[ -d /opt/hw/.git ] || git clone -q https://github.com/ayiii-a/528hw-Zijiang.git /opt/hw
python3 -m venv /opt/hw/venv
/opt/hw/venv/bin/pip install -q -r "/opt/hw/hw5/$(dirname "$APP")/requirements.txt"

cat > "/etc/systemd/system/$SERVICE.service" <<UNIT
[Unit]
Description=HW5 $ROLE service
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/opt/hw/venv/bin/python -u /opt/hw/hw5/$APP
Restart=always
RestartSec=5
# run as an unprivileged throw-away user
DynamicUser=yes
$CAPS

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now "$SERVICE"
touch /var/log/startup_already_done
