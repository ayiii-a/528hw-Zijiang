#!/bin/bash
# HW6 in one command: starts the database, creates a VM that runs the two models (models.py), waits
# for their results in the bucket, then stops the database, deletes the VM and prints the results.
# Run it in Cloud Shell:   bash hw6/run.sh
# Prerequisite, once: the HW5 data migrated into the 3NF database hw6 (migration.sql, see README.md).
set -euo pipefail

PROJECT=cs528-508221                   # hardcoded on purpose
REGION=us-central1
ZONE=us-central1-a
INSTANCE=hw5-db                        # Cloud SQL instance of HW5; the 3NF data is in its database hw6
BUCKET=528-zz-hw2
OUT=gs://$BUCKET/hw6
VM=hw6-models
SA=hw6-modeler@$PROJECT.iam.gserviceaccount.com
STOPPER_JOB=hw5-db-stopper-hourly      # HW5 scheduler job that stops the database every hour
HERE=$(cd "$(dirname "$0")" && pwd)
export CLOUDSDK_CORE_PROJECT=$PROJECT  # every gcloud command below uses this project

# IAM needs a few seconds before a new service account can be used in a policy
retry() { for _ in 1 2 3 4 5 6; do "$@" >/dev/null && return; sleep 10; done; return 1; }

# Waits until the instance is set to run (ALWAYS) and is RUNNABLE, for up to 30 minutes. A start
# after a long stop includes pending maintenance and can take much longer than gcloud waits, so
# the request is sent with --async, and sent again while Cloud SQL refuses it (another operation).
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

# runs at the end, and also when the script fails, so that the database never keeps running
finish() {
    echo "== stopping the database and deleting the VM"
    gcloud compute instances delete "$VM" --zone="$ZONE" --quiet 2>/dev/null || true
    gcloud sql instances patch "$INSTANCE" --activation-policy=NEVER --async --quiet >/dev/null 2>&1 || true
    gcloud scheduler jobs resume "$STOPPER_JOB" --location="$REGION" >/dev/null 2>&1 || true
    echo "database $INSTANCE: stop requested; VM $VM: deleted"
}

echo "== service account $SA"
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "${SA%%@*}" --display-name="HW6 model program"
for role in roles/cloudsql.client roles/cloudsql.instanceUser; do
    retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
        --role="$role" --condition=None
done
# it may only create objects under hw6/ in the bucket
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
    --role=roles/storage.objectCreator \
    --condition="expression=resource.name.startsWith(\"projects/_/buckets/$BUCKET/objects/hw6/\"),title=hw6-outputs-only"

echo "== starting the database $INSTANCE"
trap finish EXIT
# the hourly stopper of HW5 must not stop the database while the models run
gcloud scheduler jobs pause "$STOPPER_JOB" --location="$REGION" >/dev/null 2>&1 || true
wait_until_running
echo "database $INSTANCE is running"
# the model program logs in as the IAM database user of its service account (SELECT on hw6 only)
gcloud sql users list --instance="$INSTANCE" --format="value(name)" | grep -x "${SA%%@*}" >/dev/null ||
    gcloud sql users create "$SA" --instance="$INSTANCE" --type=cloud_iam_service_account

echo "== removing the results of an earlier run from $OUT/"
gcloud storage rm "$OUT/**" --quiet >/dev/null 2>&1 || true

echo "== creating the VM $VM (startup.sh installs the code and runs models.py)"
gcloud compute instances create "$VM" --zone="$ZONE" --machine-type=e2-small \
    --image-family=debian-12 --image-project=debian-cloud \
    --service-account="$SA" --scopes=cloud-platform \
    --metadata-from-file=startup-script="$HERE/startup.sh"

echo "== waiting for the results (installing and training take about 5 minutes)"
for _ in $(seq 120); do                # up to 30 minutes
    if gcloud storage ls "$OUT/error.log" >/dev/null 2>&1; then
        echo "the model program failed; its log:" >&2
        gcloud storage cat "$OUT/error.log" >&2
        exit 1
    fi
    gcloud storage ls "$OUT/summary.txt" >/dev/null 2>&1 && break
    sleep 15
done
gcloud storage ls "$OUT/summary.txt" >/dev/null 2>&1 || { echo "no results after 30 minutes" >&2; exit 1; }

finish
trap - EXIT

echo
echo "== results in $OUT/"
gcloud storage ls -l "$OUT/"
tmp=$(mktemp -d)
gcloud storage cp "$OUT/*" "$tmp/" >/dev/null 2>&1
echo
cat "$tmp/summary.txt"
for f in model1_ip_to_country.csv model2_income.csv; do
    echo "== $OUT/$f: first 10 of $(( $(wc -l < "$tmp/$f") - 1 )) test rows"
    head -n 11 "$tmp/$f"
    echo
done
rm -rf "$tmp"
