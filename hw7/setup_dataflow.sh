#!/bin/bash
# HW7, once: prepares the project for running pipeline.py on Cloud Dataflow. Run it in Cloud Shell:
#   bash hw7/setup_dataflow.sh
# Enables the APIs and creates the worker service account hw7-dataflow with only what it needs:
# running Dataflow work items, reading the bucket, and writing under gs://528-zz-hw2/hw7/ (staging
# files, temporary files and results). Every step is skipped if already done.
set -euo pipefail

PROJECT=cs528-508221                   # hardcoded on purpose
BUCKET=528-zz-hw2
SA=hw7-dataflow@$PROJECT.iam.gserviceaccount.com
export CLOUDSDK_CORE_PROJECT=$PROJECT

# IAM needs a few seconds before a new service account can be used in a policy
retry() { for _ in 1 2 3 4 5 6; do "$@" >/dev/null && return; sleep 10; done; return 1; }

gcloud services enable dataflow.googleapis.com compute.googleapis.com storage.googleapis.com logging.googleapis.com
gcloud iam service-accounts describe "$SA" >/dev/null 2>&1 ||
    gcloud iam service-accounts create "${SA%%@*}" --display-name="HW7 Dataflow workers"
retry gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" \
    --role=roles/dataflow.worker --condition=None
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
    --role=roles/storage.objectViewer --condition=None
retry gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" --member="serviceAccount:$SA" \
    --role=roles/storage.objectAdmin \
    --condition="expression=resource.name.startsWith(\"projects/_/buckets/$BUCKET/objects/hw7/\"),title=hw7-only"
echo "Done: service account $SA is ready for Dataflow."
