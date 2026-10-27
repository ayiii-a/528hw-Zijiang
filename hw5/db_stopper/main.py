"""HW5 step 8: Cloud Function (2nd gen, HTTP) that stops the Cloud SQL instance if it is running.
Cloud Scheduler calls it at the start of every hour. The function runs as the service account
hw5-db-stopper, whose custom role allows only cloudsql.instances.get and cloudsql.instances.update."""
import functions_framework
from googleapiclient import discovery

PROJECT = "cs528-508221"
INSTANCE = "hw5-db"


@functions_framework.http
def stop_db(request):
    sql = discovery.build("sqladmin", "v1beta4", cache_discovery=False)
    instance = sql.instances().get(project=PROJECT, instance=INSTANCE).execute()
    policy = instance["settings"]["activationPolicy"]
    if policy == "ALWAYS":                   # running, or starting up
        sql.instances().patch(project=PROJECT, instance=INSTANCE,
                              body={"settings": {"activationPolicy": "NEVER"}}).execute()
        message = f"{INSTANCE} was running (state {instance['state']}); stopping it"
    else:
        message = f"{INSTANCE} is not running (activation policy {policy}); nothing to do"
    print(message)
    return message
