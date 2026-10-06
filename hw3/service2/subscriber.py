"""Service 2: prints forbidden requests published by service 1 and appends them to a log in the bucket.
Runs on the laptop as the same service account as service 1, via impersonation (no key file)."""
import json
import shutil
import subprocess
import threading
from datetime import datetime, timedelta, timezone

from google.api_core.exceptions import NotFound
from google.cloud import pubsub_v1, storage
from google.oauth2.credentials import Credentials

PROJECT = "cs528-508221"
BUCKET = "528-zz-hw2"
SUBSCRIPTION = "forbidden-requests-sub"
LOG_OBJECT = "forbidden/forbidden_requests.log"
SERVICE_ACCOUNT = "hw3-file-server@cs528-508221.iam.gserviceaccount.com"


def impersonated_token(request, scopes):
    """Refresh handler: gcloud (logged in as me) asks IAM for a 1-hour token of the service account."""
    token = subprocess.run(
        [shutil.which("gcloud"), "auth", "print-access-token",
         f"--impersonate-service-account={SERVICE_ACCOUNT}"],
        capture_output=True, text=True, check=True).stdout.strip()
    expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=55)   # google-auth wants naive UTC
    return token, expiry


credentials = Credentials(token=None, refresh_handler=impersonated_token)
log_blob = storage.Client(project=PROJECT, credentials=credentials).bucket(BUCKET).blob(LOG_OBJECT)
log_lock = threading.Lock()   # callbacks run in parallel threads; one read-modify-write at a time


def append_to_log(line):
    """GCS objects cannot be appended to, so read the log, add the line and write it back."""
    with log_lock:
        try:
            old = log_blob.download_as_text()
        except NotFound:
            old = ""
        log_blob.upload_from_string(old + line + "\n", content_type="text/plain")


def callback(message):
    event = json.loads(message.data)
    line = (f"{event['time']}  FORBIDDEN request from {event['country']} "
            f"(client IP {event['client_ip']}): {event['method']} {event['file']} -> 400 permission denied")
    print(line, flush=True)
    try:
        append_to_log(line)
        message.ack()               # only after the line is safely in the bucket
    except Exception as e:
        print(f"  could not write to gs://{BUCKET}/{LOG_OBJECT}: {e}", flush=True)
        message.nack()              # Pub/Sub will deliver it again


if __name__ == "__main__":
    subscriber = pubsub_v1.SubscriberClient(credentials=credentials)
    path = subscriber.subscription_path(PROJECT, SUBSCRIPTION)
    future = subscriber.subscribe(path, callback=callback)
    print(f"Listening on {path}\nAppending to gs://{BUCKET}/{LOG_OBJECT}  (Ctrl+C to stop)", flush=True)
    with subscriber:
        try:
            while True:
                try:
                    future.result(timeout=1)   # short waits so Ctrl+C also works on Windows
                    break
                except TimeoutError:
                    pass
        except KeyboardInterrupt:
            future.cancel()
            print("stopped")