#!/bin/bash
# HW4 step 9: creates the web server VM (service 1) and the forbidden-request reporter VM (service 2),
# together with everything they need, in one command. Run it from the repository root in Cloud Shell,
# or on any machine with the gcloud CLI, logged in as an owner of the project:
#   bash hw4/deploy.sh
# Each step first checks whether its resource exists, so the script can safely be run again.
# The VMs clone the code from GitHub, so push code changes before running it.
# To use another project or bucket, change the values below and the matching constants
# at the top of service1/server.py and service2/reporter.py.
set -euo pipefail

PROJECT=cs528-508221
REGION=us-central1
ZONE=us-central1-a
BUCKET=528-zz-hw2                      # the HW2 bucket with pages/0.html ... pages/11999.html
TOPIC=forbidden-requests
SUBSCRIPTION=forbidden-requests-sub
WEB_SA=hw4-web-server@$PROJECT.iam.gserviceaccount.com
REPORTER_SA=hw4-reporter@$PROJECT.iam.gserviceaccount.com
HERE=$(cd "$(dirname "$0")" && pwd)
export CLOUDSDK_CORE_PROJECT=$PROJECT  # every gcloud command below uses this project

# IAM needs a few seconds before a new service account can be used in a policy
retry() { for _ in 1 2 3 4 5 6; do "$@" >/dev/null && return; sleep 10; done; return 1; }

gcloud services enable compute.googleapis.com iam.googleapis.com pubsub.googleapis.com logging.googleapis.com

# Pub/Sub topic and subscription that connect service 1 to service 2
gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"
gcloud pubsub subscriptions describe "$SUBSCRIPTION" >/dev/null 2>&1 ||
    gcloud pubsub subscriptions create "$SUBSCRIPTION" --topic="$TOPIC"

# one service account per VM, each with only the roles its service needs
for sa in "$WEB_SA" "$REPORTER_SA"; do
    gcloud iam service-accounts describe "$sa" >/dev/null 2>&1 ||
        gcloud iam service-accounts create "${sa%%@*}"
done
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$WEB_SA" \
    --role=roles/storage.objectViewer --condition=None
retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$WEB_SA" \
    --role=roles/logging.logWriter --condition=None
retry gcloud pubsub topics add-iam-policy-binding "$TOPIC" --member="serviceAccount:$WEB_SA" \
    --role=roles/pubsub.publisher
retry gcloud pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" --member="serviceAccount:$REPORTER_SA" \
    --role=roles/pubsub.subscriber

# static IP and firewall rule for the web server
gcloud compute addresses describe hw4-web-ip --region="$REGION" >/dev/null 2>&1 ||
    gcloud compute addresses create hw4-web-ip --region="$REGION"
gcloud compute firewall-rules describe hw4-allow-http >/dev/null 2>&1 ||
    gcloud compute firewall-rules create hw4-allow-http --allow=tcp:80 --target-tags=hw4-web --source-ranges=0.0.0.0/0

# the two VMs; their startup scripts install the services and start them with systemd
create_vm() {   # name, service account, startup script, extra flags
    local name=$1 sa=$2 script=$3
    shift 3
    if gcloud compute instances describe "$name" --zone="$ZONE" >/dev/null 2>&1; then
        echo "$name already exists, skipped"
    else
        gcloud compute instances create "$name" --zone="$ZONE" --machine-type=e2-micro \
            --image-family=debian-12 --image-project=debian-cloud \
            --service-account="$sa" --scopes=cloud-platform \
            --metadata-from-file=startup-script="$script" "$@"
    fi
}
create_vm hw4-web "$WEB_SA" "$HERE/service1/startup.sh" --address=hw4-web-ip --tags=hw4-web
create_vm hw4-reporter "$REPORTER_SA" "$HERE/service2/startup.sh"

IP=$(gcloud compute addresses describe hw4-web-ip --region="$REGION" --format="value(address)")
echo
echo "Done. The services start 1-2 minutes after the VMs are created."
echo "  web server:  http://$IP/pages/0.html"
echo "  service 2:   gcloud compute ssh hw4-reporter --zone=$ZONE --command=\"sudo journalctl -u hw4-reporter -f\""
