#!/bin/bash
# HW5 cleanup: deletes what setup.sh created that costs money while idle, and stops
# (does not delete) the Cloud SQL instance. Run it in Cloud Shell:
#   bash hw5/cleanup.sh
set -uo pipefail                       # no -e: keep going when a resource is already gone

PROJECT=cs528-508221
REGION=us-central1
ZONE=us-central1-a
export CLOUDSDK_CORE_PROJECT=$PROJECT

echo "== VMs"
vms=()
for vm in hw5-web hw5-reporter hw5-client; do
    gcloud compute instances describe "$vm" --zone="$ZONE" >/dev/null 2>&1 && vms+=("$vm")
done
[ ${#vms[@]} -eq 0 ] || gcloud compute instances delete "${vms[@]}" --zone="$ZONE" --quiet

echo "== static IP and firewall"
gcloud compute addresses describe hw5-web-ip --region="$REGION" >/dev/null 2>&1 &&
    gcloud compute addresses delete hw5-web-ip --region="$REGION" --quiet
gcloud compute firewall-rules describe hw5-allow-http >/dev/null 2>&1 &&
    gcloud compute firewall-rules delete hw5-allow-http --quiet

echo "== Cloud SQL (stopped, not deleted)"
gcloud sql instances describe hw5-db >/dev/null 2>&1 &&
    gcloud sql instances patch hw5-db --activation-policy=NEVER --quiet

echo "Done."
