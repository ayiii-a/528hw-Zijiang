# CS528 HW5 – Recording Requests in Cloud SQL

The HW4 web server (service 1), extended to record every request it receives in a Cloud SQL for MySQL
database, with the time of each processing step measured. Service 2 is unchanged from HW4. A Cloud
Function stops the database every hour, and `setup.sh` / `cleanup.sh` create and tear down everything.

## Overview

| Item | Value |
|---|---|
| GCP project | `cs528-508221` (hardcoded in the scripts, as the assignment requires) |
| Region / zone | `us-central1` / `us-central1-a` |
| Bucket (from HW2) | `gs://528-zz-hw2`, files `pages/0.html` … `pages/11999.html` |
| Database | Cloud SQL for MySQL 8.4 instance `hw5-db` (Enterprise edition, `db-f1-micro`, 10 GB HDD, no backups), database `hw5` |
| Service 1 | VM `hw5-web` (e2-small, Debian 12), systemd service `hw5-web`, port 80, static IP `hw5-web-ip`, firewall rule `hw5-allow-http` |
| Service 2 | VM `hw5-reporter` (e2-micro, Debian 12), systemd service `hw5-reporter` |
| Database stopper | Cloud Function `hw5-db-stopper`, Cloud Scheduler job `hw5-db-stopper-hourly` (`0 * * * *` UTC) |
| Pub/Sub | topic `forbidden-requests`, pull subscription `forbidden-requests-sub` |
| Cloud Logging | log `hw5-file-server` (404 WARNING, 501 ERROR, 400 CRITICAL) |
| Load-test client | VM `hw5-client` (e2-small, Debian 13), created by hand for step 5, deleted by `cleanup.sh` |

```
 http-client (VM hw5-client) / curl / browser
            │  GET /pages/12.html   or   POST {"file": "pages/12.html"}
            ▼
 ┌────────────────────────────┐   read file    ┌──────────────────────────┐
 │ Service 1  VM hw5-web      │ ─────────────► │ bucket 528-zz-hw2/pages/ │
 │ runs as hw5-web-server     │                └──────────────────────────┘
 └────────────────────────────┘
       │            │  every request (after the response is sent)
       │            ▼
       │   ┌─────────────────────────────────────────────┐      ┌──────────────────────────┐
       │   │ Cloud SQL hw5-db, database hw5              │ ◄─── │ Cloud Function           │
       │   │ tables requests, failed_requests            │ stop │ hw5-db-stopper, hourly   │
       │   └─────────────────────────────────────────────┘      └──────────────────────────┘
       │  forbidden X-country: 400 + publish
       ▼
   topic forbidden-requests ──► subscription forbidden-requests-sub ──► Service 2, VM hw5-reporter
                                                                         (prints to standard output)
```

| Path | Content |
|---|---|
| `setup.sh` | creates or starts everything (see 1.3) |
| `cleanup.sh` | deletes the VMs, the static IP and the firewall rule; stops (does not delete) the database |
| `startup.sh` | startup script of both VMs; the metadata key `role` selects service 1 or 2; runs once |
| `setup_schema.py` | creates the tables and grants the web server `INSERT`; called by `setup.sh` |
| `requirements-setup.txt` | packages for `setup_schema.py` and `db_query.py` |
| `service1/server.py` | service 1: serves files, records every request in Cloud SQL, times each step |
| `service1/requirements.txt` | Cloud Storage, Logging, Pub/Sub, Cloud SQL Connector, PyMySQL (< 1.2), SQLAlchemy |
| `service1/test_server.py` | local test of the server with fake Cloud Storage, Logging, Pub/Sub and database |
| `service2/` | service 2, copied unchanged from HW4 |
| `db_stopper/main.py` | Cloud Function that stops the database if it is running |
| `db_query.py` | shows the tables (step 4), prints the statistics (step 7), empties the tables |
| `timing_stats.py` | summarizes the timing lines of the server journal (step 6) |
| `http-client` | the provided client (Linux build) |

## 1. Setup and cleanup (step 9)

### 1.1 Prerequisites

- **Cloud Shell**, logged in as a user with the **Owner** role on `cs528-508221`. The scripts enable APIs,
  create service accounts and a custom IAM role, grant roles, and create VMs, an IP address, a firewall rule,
  a Cloud SQL instance, a Cloud Function and a Cloud Scheduler job.
- The HW2 bucket `528-zz-hw2` with its pages.
- The VMs clone this repository from GitHub, so code changes must be pushed before running `setup.sh`.
- `setup_schema.py` runs only when the database is created. It connects with Application Default
  Credentials, which Cloud Shell provides automatically. On another machine, run
  `gcloud auth application-default login` first and `gcloud auth application-default revoke` afterwards.
  The scripts themselves never call `application-default login`.

### 1.2 Run

```bash
git clone https://github.com/ayiii-a/528hw-Zijiang.git    # or: git -C 528hw-Zijiang pull
bash 528hw-Zijiang/hw5/setup.sh
bash 528hw-Zijiang/hw5/cleanup.sh                         # when finished
```

The project ID is hardcoded (`PROJECT=cs528-508221`) and exported as `CLOUDSDK_CORE_PROJECT`, so the
scripts never depend on, or change, the default project of the gcloud CLI. Every step first checks whether
its resource exists, so `setup.sh` can be run again at any time. The services are running 1–2 minutes after
`setup.sh` finishes; it prints the URL of the web server at the end.

### 1.3 What `setup.sh` does

1. Enables the APIs: Compute Engine, IAM, Cloud SQL Admin, Pub/Sub, Logging, Cloud Functions, Cloud Run,
   Cloud Build, Artifact Registry, Cloud Scheduler.
2. Creates the Pub/Sub topic and subscription if they do not exist.
3. Creates the service accounts `hw5-web-server`, `hw5-reporter` and `hw5-db-stopper` and grants their
   roles (see 1.6). Role bindings are retried, because IAM needs a few seconds to accept a new account.
4. **Cloud SQL** (function `setup_cloud_sql`):
   - if the instance `hw5-db` exists, it is **started** (`--activation-policy=ALWAYS`); otherwise it is
     **created** (MySQL 8.4, Enterprise edition, `db-f1-micro`, 10 GB HDD, no backups, IAM database
     authentication on), and the script waits until it is `RUNNABLE`;
   - the service account `hw5-web-server` is added as an IAM database user if needed;
   - if the database `hw5` exists, schema setup is **skipped**. Otherwise the script creates the database,
     sets a random one-time `root` password (not stored anywhere), installs the Cloud SQL Connector in a
     temporary virtualenv and runs `setup_schema.py`. If that fails, the half-made database is deleted
     so that the next run tries again.
5. Allocates the static IP `hw5-web-ip` and **reads its address into `WEB_IP` with gcloud** (no address is
   hardcoded); creates the firewall rule `hw5-allow-http` (tcp:80, only VMs tagged `hw5-web`).
6. Creates the VMs, both with `startup.sh` as startup script: `hw5-web` (e2-small, `role=web`, static IP,
   tag `hw5-web`) and `hw5-reporter` (e2-micro, `role=reporter`). Existing VMs are skipped.
7. Creates the custom role `hw5DbStopper`, deploys the Cloud Function `hw5-db-stopper`, lets only
   `hw5-db-stopper` invoke it, and creates the Cloud Scheduler job `hw5-db-stopper-hourly`.

### 1.4 What `cleanup.sh` does

Deletes the VMs `hw5-web`, `hw5-reporter` and `hw5-client` (if they exist), **releases the static IP**,
deletes the firewall rule, and **stops** the Cloud SQL instance (`--activation-policy=NEVER`). The instance
and its data are kept, as the assignment requires. Service accounts, Pub/Sub, the Cloud Function and the
scheduler job cost nothing while idle and stay; the scheduler keeps the database stopped.

### 1.5 `startup.sh`

Compute Engine runs it as root at every boot. It exits at once if `/var/log/startup_already_done` exists.
On the first boot it reads the metadata key `role` (`web` or `reporter`), installs `git` and
`python3-venv`, clones the repository into `/opt/hw`, creates a virtualenv, installs the requirements of
the service, writes a systemd unit (`hw5-web` or `hw5-reporter`: `Restart=always`, `DynamicUser=yes`, plus
`CAP_NET_BIND_SERVICE` for the web server to bind port 80), enables and starts it, and finally creates the
lock file. On later boots systemd starts the enabled service by itself. No VM is configured with
`gcloud compute ssh`.

### 1.6 Service accounts and permissions (least privilege)

| Service account | Role | Granted on | Why |
|---|---|---|---|
| `hw5-web-server` | `roles/storage.objectViewer` | bucket `528-zz-hw2` | read the pages |
| `hw5-web-server` | `roles/logging.logWriter` | project | write the 404 / 501 / 400 log entries |
| `hw5-web-server` | `roles/pubsub.publisher` | topic `forbidden-requests` | report forbidden requests to service 2 |
| `hw5-web-server` | `roles/cloudsql.client` | project | connect through the Cloud SQL Connector |
| `hw5-web-server` | `roles/cloudsql.instanceUser` | project | log in to MySQL with IAM database authentication |
| `hw5-reporter` | `roles/pubsub.subscriber` | subscription `forbidden-requests-sub` | receive the reports |
| `hw5-db-stopper` | custom role `hw5DbStopper` (`cloudsql.instances.get`, `cloudsql.instances.update`) | project | read the instance and change its activation policy, nothing else |
| `hw5-db-stopper` | Cloud Run invoker | function `hw5-db-stopper` | lets the scheduler job (OIDC token of this account) call the function |

- Inside MySQL, the web server is the IAM user `hw5-web-server` with **`INSERT` on `hw5.*` only**. No
  database password exists on the VM or in the repository.
- No service account keys are created; the VMs and the function get short-lived tokens from the metadata server.
- The bucket binding needs `--condition=None` because the bucket already has a conditional binding (HW3).
- The client VM `hw5-client` has no service account at all (`--no-service-account --no-scopes`).

## 2. Database schema

```sql
CREATE TABLE requests (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    received_at    DATETIME(6)  NOT NULL,   -- when the server received the request (UTC)
    country        VARCHAR(64),             -- X-country
    client_ip      VARCHAR(45),             -- X-client-IP
    gender         VARCHAR(16),             -- X-gender: Male, Female
    age            VARCHAR(16),             -- X-age: age group, e.g. 26-35
    income         VARCHAR(16),             -- X-income: income group, e.g. 40k-60k
    is_banned      BOOLEAN      NOT NULL,   -- X-country is one of the 9 export-restricted countries
    time_of_day    TIME,                    -- hour of X-time, e.g. 13:00:00
    requested_file VARCHAR(255) NOT NULL    -- e.g. pages/123.html
);

CREATE TABLE failed_requests (
    id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    request_time   DATETIME(6)  NOT NULL,
    requested_file VARCHAR(255) NOT NULL,
    error_code     SMALLINT     NOT NULL
);
```

Every request becomes a row of `requests`. A request that does not get `200` is also written to
`failed_requests`, in the same transaction. Header values are cut to the size of their column; missing
headers (curl, browsers, scanners) become `NULL`.

## 3. Using the system

### Service 1

Same requests and responses as HW4: GET with the file in the path, POST with `{"file": …}` or `file=…`
→ `200`; missing file → `404`; PUT, DELETE, HEAD, CONNECT, OPTIONS, TRACE, PATCH → `501`; `X-country` one of
North Korea, Iran, Cuba, Myanmar, Iraq, Libya, Sudan, Zimbabwe, Syria (full name) → `400` and a message to
service 2.

```bash
IP=$(gcloud compute addresses describe hw5-web-ip --region=us-central1 --format="value(address)")
curl -si -H "X-country: Canada" -H "X-gender: Female" -H "X-age: 26-35" -H "X-income: 40k-60k" \
    -H "X-time: 2026-10-27 13:00:00" http://$IP/pages/1.html | head -n 5
```

### Viewing the tables and statistics

`db_query.py` connects as `root` through the Cloud SQL Connector. Set a root password once, and keep it
in an environment variable of the shell:

```bash
gcloud sql users set-password root --host=% --instance=hw5-db --prompt-for-password
read -rsp "root password: " DB_ROOT_PASSWORD && export DB_ROOT_PASSWORD && echo
python3 -m venv ~/hw5venv && ~/hw5venv/bin/pip install -q -r ~/528hw-Zijiang/hw5/requirements-setup.txt
~/hw5venv/bin/python ~/528hw-Zijiang/hw5/db_query.py          # row counts and latest rows
~/hw5venv/bin/python ~/528hw-Zijiang/hw5/db_query.py stats    # step 7
~/hw5venv/bin/python ~/528hw-Zijiang/hw5/db_query.py reset    # empty both tables
```

Port 80 is open to the internet, so scanners also send requests (e.g. `GET /admin/config.php`). The
statistics count only the requests of the provided client, which always asks for `pages/<n>.html`
(`requested_file REGEXP '^pages/[0-9]+[.]html$'`).

### Service 2

```bash
gcloud compute ssh hw5-reporter --zone=us-central1-a --command="sudo journalctl -u hw5-reporter -f"
```

## 4. Load test, timings and statistics (steps 5–7)

```bash
# Cloud Shell: empty the tables, pause the database stopper, create the client VM
~/hw5venv/bin/python ~/528hw-Zijiang/hw5/db_query.py reset
gcloud scheduler jobs pause hw5-db-stopper-hourly --location=us-central1
gcloud compute instances create hw5-client --zone=us-central1-a --machine-type=e2-small \
    --image-family=debian-13 --image-project=debian-cloud --no-service-account --no-scopes
gcloud compute ssh hw5-client --zone=us-central1-a

# on hw5-client: two clients, 50,000 requests each, same seed, to the internal IP of hw5-web
curl -LO https://raw.githubusercontent.com/ayiii-a/528hw-Zijiang/main/hw5/http-client && chmod +x http-client
for i in 1 2; do nohup ./http-client -d 10.128.0.9 -p 80 -b 528-zz-hw2 -w pages -i 11999 -n 50000 -r 1 > client$i.log 2>&1 & done; date -u

# Cloud Shell, when done: timings (step 6) and statistics (step 7), then resume the stopper
gcloud compute ssh hw5-web --zone=us-central1-a --command="sudo journalctl -u hw5-web --since '<start time>' -o cat --no-pager" > ~/journal.txt
python3 ~/528hw-Zijiang/hw5/timing_stats.py ~/journal.txt
~/hw5venv/bin/python ~/528hw-Zijiang/hw5/db_query.py stats
gcloud scheduler jobs resume hw5-db-stopper-hourly --location=us-central1
```

- The client VM runs Debian 13: the provided client needs glibc 2.38, Debian 12 has 2.36.
- The internal IP of `hw5-web` is shown by `gcloud compute instances list`. Internal traffic within the
  zone is free; the test moves about 8 GB.
- Without `-v` the client prints only timeouts and connection errors, so empty logs mean no failures.
- Each request prints `TIMING status=… extract_ns=… gcs_ns=… send_ns=… db_ns=… total_ns=…` to the journal,
  measured with `time.perf_counter_ns()` around the four functions `extract_request_info`, `read_file`,
  `send_response` and `insert_into_db`.

Results of the run on 2026-10-27 (details in the report):

| | |
|---|---|
| Duration, throughput | 2,814 s, 35.5 requests/s (about 17.8 per client) |
| Responses | 95,354 × 200, 4,646 × 400 (banned country); no timeouts, no connection errors, no database errors |
| Median time per step | extract 0.27 ms, Cloud Storage 36 ms, send 0.58 ms, database insert 146 ms |
| Statistics | Male 50,039 / Female 49,961; top countries Jamaica, Ethiopia, Senegal, Somalia, New Zealand; top age group 0-16; top income group 0-10k |

## 5. Database stopper (step 8)

`hw5-db-stopper` reads the instance through the Cloud SQL Admin API and, if its activation policy is
`ALWAYS` (running or starting), sets it to `NEVER`. Cloud Scheduler calls it at minute 0 of every hour with
an OIDC token of `hw5-db-stopper`; the function does not accept unauthenticated calls (`403`).

```bash
gcloud scheduler jobs run hw5-db-stopper-hourly --location=us-central1      # run it now
gcloud functions logs read hw5-db-stopper --gen2 --region=us-central1 --limit=5
gcloud sql instances describe hw5-db --format="value(settings.activationPolicy,state)"
gcloud scheduler jobs pause hw5-db-stopper-hourly --location=us-central1    # while working with the database
gcloud scheduler jobs resume hw5-db-stopper-hourly --location=us-central1   # when done
```

## Notes

- **PyMySQL is pinned below 1.2.** PyMySQL 1.2 starts its own TLS when the server supports it, which fails
  inside the Cloud SQL Connector's already encrypted connection (`'NoneType' object has no attribute
  'is_auth_switch_request'`).
- **Stopped database.** When the instance is stopped, open connections never answer again. The server sets a
  10 s read/write timeout on its database connections and retries an insert once on a new connection, so a
  restart of the database costs at most one slow insert instead of a hung request.
- **The same seed (`-r`)** only fixes the table of IP address ranges per country in the provided client; it then
  calls `random.seed(None)`, so the two clients send different, independent requests that use the same
  address ranges for each country.
- **Internet scanners** reach the public port 80; their requests are recorded but left out of the statistics.
- **Cost.** Cloud SQL is billed per running hour (plus storage), so the scheduler stops it every hour; the
  static IP is billed until `cleanup.sh` releases it.
