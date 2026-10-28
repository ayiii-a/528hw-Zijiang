#!/bin/bash
# HW5 setup: creates (or starts) everything the homework needs. Run it in Cloud Shell:
#   bash hw5/setup.sh
# Every step first checks whether its resource already exists, so it is safe to run again.
set -euo pipefail

PROJECT=cs528-508221                   # hardcoded on purpose, see the assignment
REGION=us-central1
ZONE=us-central1-a
BUCKET=528-zz-hw2                      # HW2 bucket with pages/0.html ... pages/11999.html
TOPIC=forbidden-requests
SUBSCRIPTION=forbidden-requests-sub
INSTANCE=hw5-db                        # Cloud SQL for MySQL instance
DB=hw5
WEB_SA=hw5-web-server@$PROJECT.iam.gserviceaccount.com
REPORTER_SA=hw5-reporter@$PROJECT.iam.gserviceaccount.com
STOPPER_SA=hw5-db-stopper@$PROJECT.iam.gserviceaccount.com
HERE=$(cd "$(dirname "$0")" && pwd)
export CLOUDSDK_CORE_PROJECT=$PROJECT  # every gcloud command below uses this project

# IAM needs a few seconds before a new service account can be used in a policy
retry() { for _ in 1 2 3 4 5 6; do "$@" >/dev/null && return; sleep 10; done; return 1; }

echo "== APIs"
gcloud services enable compute.googleapis.com iam.googleapis.com sqladmin.googleapis.com \
    pubsub.googleapis.com logging.googleapis.com cloudfunctions.googleapis.com run.googleapis.com \
    cloudbuild.googleapis.com artifactregistry.googleapis.com cloudscheduler.googleapis.com

echo "== Pub/Sub"
gcloud pubsub topics describe "$TOPIC" >/dev/null 2>&1 || gcloud pubsub topics create "$TOPIC"
gcloud pubsub subscriptions describe "$SUBSCRIPTION" >/dev/null 2>&1 ||
    gcloud pubsub subscriptions create "$SUBSCRIPTION" --topic="$TOPIC"

echo "== service accounts and permissions"
for sa in "$WEB_SA" "$REPORTER_SA" "$STOPPER_SA"; do
    gcloud iam service-accounts describe "$sa" >/dev/null 2>&1 ||
        gcloud iam service-accounts create "${sa%%@*}"
done
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$WEB_SA" \
    --role=roles/storage.objectViewer --condition=None
for role in roles/logging.logWriter roles/cloudsql.client roles/cloudsql.instanceUser; do
    retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$WEB_SA" \
        --role="$role" --condition=None
done
retry gcloud pubsub topics add-iam-policy-binding "$TOPIC" --member="serviceAccount:$WEB_SA" \
    --role=roles/pubsub.publisher
retry gcloud pubsub subscriptions add-iam-policy-binding "$SUBSCRIPTION" --member="serviceAccount:$REPORTER_SA" \
    --role=roles/pubsub.subscriber

# Cloud SQL: start the instance if it exists, otherwise create it; create and fill the
# database only if it does not exist yet
# Waits until the instance is set to run (ALWAYS) and is RUNNABLE, for up to 30 minutes. The start
# request is sent without waiting (--async) and sent again while it has not taken effect, because
# Cloud SQL refuses it while another operation, such as the stop of cleanup.sh, is still running.
wait_until_running() {
    local status
    for _ in $(seq 90); do
        status=$(gcloud sql instances describe "$INSTANCE" --format="csv[no-heading](settings.activationPolicy,state)") || return 1
        [ "$status" = "ALWAYS,RUNNABLE" ] && return 0
        if [ "${status%%,*}" != ALWAYS ]; then
            gcloud sql instances patch "$INSTANCE" --activation-policy=ALWAYS --async --quiet >/dev/null 2>&1 || true
        fi
        echo "  $status, waiting"
        sleep 20
    done
    echo "instance $INSTANCE did not start within 30 minutes" >&2
    return 1
}

setup_cloud_sql() {
    if gcloud sql instances describe "$INSTANCE" >/dev/null 2>&1; then
        echo "instance $INSTANCE exists, starting it"
    else
        echo "creating instance $INSTANCE (takes 5-10 minutes)"
        gcloud sql instances create "$INSTANCE" --database-version=MYSQL_8_4 --edition=enterprise \
            --tier=db-f1-micro --region="$REGION" --storage-type=HDD --storage-size=10 --no-backup \
            --database-flags=cloudsql_iam_authentication=on ||
            echo "gcloud stopped waiting; checking the instance state"
    fi
    wait_until_running

    # the web server logs in with its service account (IAM database authentication), no password
    gcloud sql users list --instance="$INSTANCE" --format="value(name)" | grep -x "${WEB_SA%%@*}" >/dev/null ||
        gcloud sql users create "$WEB_SA" --instance="$INSTANCE" --type=cloud_iam_service_account

    if gcloud sql databases describe "$DB" --instance="$INSTANCE" >/dev/null 2>&1; then
        echo "database $DB exists, schema setup skipped"
        return
    fi
    gcloud sql databases create "$DB" --instance="$INSTANCE"
    # one-time root password for setup_schema.py; it is not stored anywhere
    local password venv=${TMPDIR:-/tmp}/hw5-setup-venv
    password=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))")
    gcloud sql users set-password root --host=% --instance="$INSTANCE" --password="$password"
    [ -x "$venv/bin/python" ] || python3 -m venv "$venv"
    "$venv/bin/pip" install -q -r "$HERE/requirements-setup.txt"
    if ! DB_ROOT_PASSWORD=$password "$venv/bin/python" "$HERE/setup_schema.py"; then
        # remove the half-made database so that the next run creates the schema again
        gcloud sql databases delete "$DB" --instance="$INSTANCE" --quiet
        echo "schema setup failed; database $DB removed, fix the error and run setup.sh again" >&2
        exit 1
    fi
}
echo "== Cloud SQL"
setup_cloud_sql

echo "== static IP and firewall"
gcloud compute addresses describe hw5-web-ip --region="$REGION" >/dev/null 2>&1 ||
    gcloud compute addresses create hw5-web-ip --region="$REGION"
WEB_IP=$(gcloud compute addresses describe hw5-web-ip --region="$REGION" --format="value(address)")
gcloud compute firewall-rules describe hw5-allow-http >/dev/null 2>&1 ||
    gcloud compute firewall-rules create hw5-allow-http --allow=tcp:80 --target-tags=hw5-web \
        --source-ranges=0.0.0.0/0

echo "== VMs (startup.sh installs and starts the services on the first boot)"
create_vm() {   # name, machine type, service account, role, extra flags
    local name=$1 type=$2 sa=$3 role=$4
    shift 4
    if gcloud compute instances describe "$name" --zone="$ZONE" >/dev/null 2>&1; then
        echo "$name already exists, skipped"
    else
        gcloud compute instances create "$name" --zone="$ZONE" --machine-type="$type" \
            --image-family=debian-12 --image-project=debian-cloud \
            --service-account="$sa" --scopes=cloud-platform \
            --metadata=role="$role" --metadata-from-file=startup-script="$HERE/startup.sh" "$@"
    fi
}
# e2-small: an e2-micro only gets 0.25 vCPU over time, too little for hours of requests with DB writes
create_vm hw5-web e2-small "$WEB_SA" web --address="$WEB_IP" --tags=hw5-web
create_vm hw5-reporter e2-micro "$REPORTER_SA" reporter

echo "== Cloud Function that stops the database, called every hour by Cloud Scheduler"
# custom role: read the instance and change its activation policy, nothing else
gcloud iam roles describe hw5DbStopper --project="$PROJECT" >/dev/null 2>&1 ||
    gcloud iam roles create hw5DbStopper --project="$PROJECT" --title="HW5 database stopper" \
        --permissions=cloudsql.instances.get,cloudsql.instances.update
retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$STOPPER_SA" \
    --role="projects/$PROJECT/roles/hw5DbStopper" --condition=None
gcloud functions deploy hw5-db-stopper --gen2 --runtime=python312 --region="$REGION" \
    --source="$HERE/db_stopper" --entry-point=stop_db --trigger-http --no-allow-unauthenticated \
    --service-account="$STOPPER_SA" --memory=256Mi --timeout=60s --quiet
# only the scheduler job (which calls with an OIDC token of the same account) may invoke it
retry gcloud functions add-invoker-policy-binding hw5-db-stopper --region="$REGION" \
    --member="serviceAccount:$STOPPER_SA"
STOPPER_URL=$(gcloud functions describe hw5-db-stopper --gen2 --region="$REGION" --format="value(serviceConfig.uri)")
gcloud scheduler jobs describe hw5-db-stopper-hourly --location="$REGION" >/dev/null 2>&1 ||
    gcloud scheduler jobs create http hw5-db-stopper-hourly --location="$REGION" \
        --schedule="0 * * * *" --time-zone=UTC --uri="$STOPPER_URL" --http-method=POST \
        --oidc-service-account-email="$STOPPER_SA" --oidc-token-audience="$STOPPER_URL"

echo
echo "Done. The services start 1-2 minutes after their VM is created."
echo "  web server: http://$WEB_IP/pages/0.html"
echo "The database is stopped at the start of every hour. While working with it, pause the job:"
echo "  gcloud scheduler jobs pause hw5-db-stopper-hourly --location=$REGION    (resume: ... resume ...)"
