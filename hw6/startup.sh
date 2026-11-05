#!/bin/bash
# Startup script of the HW6 model VM, which run.sh creates. Compute Engine runs it as root at every
# boot; it does its work on the first boot only. It installs the code and runs models.py, which
# writes its results to gs://528-zz-hw2/hw6/. If any step fails, the log is copied there as
# error.log instead, so that run.sh stops waiting and shows it.
set -uo pipefail

if [ -f /var/log/startup_already_done ]; then
    echo "Startup script already ran once. Skipping."
    exit 0
fi

LOG=/var/log/hw6-models.log
if ! (apt-get update -q &&
      apt-get install -y -q git python3-venv &&
      { [ -d /opt/hw/.git ] || git clone -q https://github.com/ayiii-a/528hw-Zijiang.git /opt/hw; } &&
      python3 -m venv /opt/hw/venv &&
      /opt/hw/venv/bin/pip install -q -r /opt/hw/hw6/requirements.txt &&
      /opt/hw/venv/bin/python -u /opt/hw/hw6/models.py) > "$LOG" 2>&1; then
    gcloud storage cp "$LOG" gs://528-zz-hw2/hw6/error.log
fi
touch /var/log/startup_already_done
