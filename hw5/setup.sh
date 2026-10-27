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
for sa in "$WEB_SA" "$REPORTER_SA"; do
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
setup_cloud_sql() {
    if gcloud sql instances describe "$INSTANCE" >/dev/null 2>&1; then
        echo "instance $INSTANCE exists, starting it"
        gcloud sql instances patch "$INSTANCE" --activation-policy=ALWAYS --quiet
    else
        echo "creating instance $INSTANCE (takes 5-10 minutes)"
        gcloud sql instances create "$INSTANCE" --database-version=MYSQL_8_4 --edition=enterprise \
            --tier=db-f1-micro --region="$REGION" --storage-type=HDD --storage-size=10 --no-backup \
            --database-flags=cloudsql_iam_authentication=on ||
            echo "gcloud stopped waiting; checking the instance state"
    fi
    local state
    while state=$(gcloud sql instances describe "$INSTANCE" --format="value(state)") && [ "$state" != RUNNABLE ]; do
        echo "  state $state, waiting"
        sleep 20
    done
    [ "$state" = RUNNABLE ]

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
