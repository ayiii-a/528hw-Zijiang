"""HW4 service 2: prints the forbidden requests that service 1 publishes to Pub/Sub.
Runs on its own VM as a systemd service, so its standard output goes to the journal
(journalctl -u hw4-reporter)."""
import json

from google.cloud import pubsub_v1

PROJECT = "cs528-508221"
SUBSCRIPTION = "forbidden-requests-sub"


def describe(data):
    """One line of output for one message from service 1."""
    try:
        e = json.loads(data)
        return (f"{e['time']}  FORBIDDEN request from {e['country']} (client IP {e['client_ip']}): "
                f"{e['method']} {e['file']} -> 400 permission denied")
    except (ValueError, KeyError, TypeError):
        return f"FORBIDDEN request (unreadable message): {data!r}"


def callback(message):
    print(describe(message.data), flush=True)
    message.ack()


if __name__ == "__main__":
    subscriber = pubsub_v1.SubscriberClient()      # authenticates as the service account of the VM
    path = subscriber.subscription_path(PROJECT, SUBSCRIPTION)
    print(f"listening on {path}", flush=True)
    subscriber.subscribe(path, callback=callback).result()   # blocks; if the stream fails, systemd restarts it
