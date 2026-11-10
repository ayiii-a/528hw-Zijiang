#!/bin/bash
# HW7: runs pipeline.py on Cloud Dataflow. Run it in Cloud Shell after setup_dataflow.sh:
#   bash hw7/run_dataflow.sh
# The job reads gs://528-zz-hw2/pages/*.html and writes its results to
# gs://528-zz-hw2/hw7/output/DataflowRunner/; staging and temporary files go to gs://528-zz-hw2/hw7/.
set -euo pipefail

PROJECT=cs528-508221
REGION=us-central1
VENV=$HOME/beam-venv
HERE=$(cd "$(dirname "$0")" && pwd)

# Apache Beam with the Google Cloud extras, in a virtualenv of its own (once)
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q "apache-beam[gcp]==2.77.0"

"$VENV/bin/python" "$HERE/pipeline.py" \
    --runner=DataflowRunner \
    --project="$PROJECT" --region="$REGION" \
    --temp_location=gs://528-zz-hw2/hw7/tmp --staging_location=gs://528-zz-hw2/hw7/staging \
    --service_account_email="hw7-dataflow@$PROJECT.iam.gserviceaccount.com" \
    --machine_type=e2-standard-2 --max_num_workers=4
