# CS528 HW4 – File Server on Compute Engine VMs

HW3 rebuilt on virtual machines. Service 1 is a Python web server on a VM with a static IP. Service 2 runs
on a second VM and prints the forbidden requests it receives from service 1. Both start automatically when
their VM is created, and `deploy.sh` creates everything with one command.

## Overview

| Item | Value |
|---|---|
| GCP project | `cs528-508221` |
| Region / zone | `us-central1` / `us-central1-a` |
| Bucket (from HW2) | `gs://528-zz-hw2`, files `pages/0.html` … `pages/11999.html` |
| Service 1 | VM `hw4-web` (e2-micro, Debian 12), systemd service `hw4-web`, port 80 |
| Static IP | `hw4-web-ip` = `34.136.109.218`, firewall rule `hw4-allow-http` (tcp:80, network tag `hw4-web`) |
| Service 2 | VM `hw4-reporter` (e2-micro, Debian 12), systemd service `hw4-reporter` |
| Service accounts | `hw4-web-server` (service 1), `hw4-reporter` (service 2) |
| Pub/Sub | topic `forbidden-requests`, pull subscription `forbidden-requests-sub` |
| Cloud Logging | log `hw4-file-server` |
| Client VM (steps 4 and 8 only) | `hw4-client` (e2-small, Debian 13), no service account; not created by `deploy.sh` |

```
 http-client on VM hw4-client / curl / browser
            │  GET /pages/12.html   or   POST {"file": "pages/12.html"}
            ▼  http://34.136.109.218 (static IP hw4-web-ip, port 80)
 ┌────────────────────────────┐   read file    ┌──────────────────────────┐
 │ Service 1  VM hw4-web      │ ─────────────► │ bucket 528-zz-hw2/pages/ │
 │ runs as hw4-web-server     │                └──────────────────────────┘
 └────────────────────────────┘
            │  404 WARNING, 501 ERROR, 400 CRITICAL
            ├──────────────────────────► Cloud Logging, log hw4-file-server
            │  forbidden X-country: publish
            ▼
   topic forbidden-requests ──► subscription forbidden-requests-sub
                                          │  streaming pull
                                          ▼
                        ┌──────────────────────────────────┐
                        │ Service 2  VM hw4-reporter       │ ──► standard output
                        │ runs as hw4-reporter             │     (journalctl -u hw4-reporter)
                        └──────────────────────────────────┘
```

| Path | Content |
|---|---|
| `deploy.sh` | Step 9: creates the service accounts, permissions, Pub/Sub, static IP, firewall rule and both VMs |
| `service1/server.py` | Service 1: serves files over GET and POST, returns 200 / 400 / 404 / 501, logs errors, publishes forbidden requests |
| `service1/requirements.txt` | `google-cloud-storage`, `google-cloud-logging`, `google-cloud-pubsub` |
| `service1/startup.sh` | Startup script of `hw4-web`: installs the code and runs service 1 as a systemd service |
| `service2/reporter.py` | Service 2: prints each forbidden request to standard output |
| `service2/requirements.txt` | `google-cloud-pubsub` |
| `service2/startup.sh` | Startup script of `hw4-reporter`: installs the code and runs service 2 as a systemd service |
| `stress/stress.sh` | Step 8: runs 1, 2, 3 and 4 concurrent clients on the client VM and counts the responses |
| `stress/plot.py` | Step 8: plots the CPU, memory and network use of the server recorded with `sar` |
| `http-client` | The provided HTTP client (Linux build) |

## 1. Deploy with one command (`deploy.sh`)

### 1.1 Prerequisites

- A Google Cloud project with billing enabled.
- The HW2 bucket `528-zz-hw2` with `pages/0.html` … `pages/11999.html`.
- The gcloud CLI, logged in as a user with the **Owner** role on the project. Cloud Shell already has the
  gcloud CLI and is logged in. Owner rights are needed because the script enables APIs, creates service
  accounts, grants IAM roles on the project, bucket, topic and subscription, and creates VMs, an IP address
  and a firewall rule.
- The VMs clone this repository from GitHub (`https://github.com/ayiii-a/528hw-Zijiang`), so code changes
  must be pushed before deploying.

### 1.2 Project ID and other settings

All settings are at the top of `deploy.sh`:

```bash
PROJECT=cs528-508221
REGION=us-central1
ZONE=us-central1-a
BUCKET=528-zz-hw2                      # the HW2 bucket with pages/0.html ... pages/11999.html
TOPIC=forbidden-requests
SUBSCRIPTION=forbidden-requests-sub
```

The script exports `CLOUDSDK_CORE_PROJECT=$PROJECT`, so every gcloud command in it uses this project,
whatever the default project of the gcloud CLI is, and the gcloud configuration is not changed.

To deploy into another project or with another bucket, change these values **and** the matching constants
at the top of `service1/server.py` (`PROJECT`, `BUCKET`, `TOPIC`) and `service2/reporter.py`
(`PROJECT`, `SUBSCRIPTION`). If the code is in a fork, also change the repository URL in both `startup.sh` files.

### 1.3 Run it (Cloud Shell)

```bash
git clone https://github.com/ayiii-a/528hw-Zijiang.git    # or: git -C 528hw-Zijiang pull
bash 528hw-Zijiang/hw4/deploy.sh
```

The script ends by printing the URL of the web server and the command that shows the output of service 2.
The two services are running 1–2 minutes after the script finishes, once the startup scripts of the VMs are done.

### 1.4 What the script creates

| # | Resource | Details |
|---|---|---|
| 1 | APIs | Compute Engine, IAM, Pub/Sub, Cloud Logging |
| 2 | Pub/Sub | topic `forbidden-requests` and pull subscription `forbidden-requests-sub` |
| 3 | Service accounts | `hw4-web-server` and `hw4-reporter`, one per VM |
| 4 | Permissions | see 1.5 |
| 5 | Network | static IP `hw4-web-ip` and firewall rule `hw4-allow-http` (tcp:80, only VMs tagged `hw4-web`) |
| 6 | VM `hw4-web` | e2-micro, Debian 12, runs as `hw4-web-server`, static IP, tag `hw4-web`, startup script `service1/startup.sh` |
| 7 | VM `hw4-reporter` | e2-micro, Debian 12, runs as `hw4-reporter`, startup script `service2/startup.sh` |

The script is safe to run again. Each create step first checks whether the resource exists
(`describe … || create …`), granting a role that is already granted changes nothing, and an existing VM is
skipped. A new service account can take a few seconds before IAM accepts it in a policy, so every role
binding is retried every 10 seconds, up to 6 times.

### 1.5 Service accounts and permissions (least privilege)

| Service account | Role | Granted on | Why |
|---|---|---|---|
| `hw4-web-server` | `roles/storage.objectViewer` | bucket `528-zz-hw2` only | service 1 reads the pages; it cannot change or delete them |
| `hw4-web-server` | `roles/logging.logWriter` | project | service 1 writes the 404 / 501 / 400 log entries; it cannot read logs |
| `hw4-web-server` | `roles/pubsub.publisher` | topic `forbidden-requests` only | service 1 reports forbidden requests |
| `hw4-reporter` | `roles/pubsub.subscriber` | subscription `forbidden-requests-sub` only | service 2 receives the reports; it has no other access |

- No service account key is created. On the VMs, the client libraries get short-lived tokens from the
  metadata server.
- The VMs use the access scope `cloud-platform`, so the IAM roles above are the only limit on what they can do.
  Access scopes are a legacy mechanism.
- The bucket already has a conditional IAM binding from HW3, so the bucket binding needs `--condition=None`.
  Without it, gcloud asks for a condition interactively.
- The client VM `hw4-client` only sends HTTP requests, so it is created with no service account at all
  (`--no-service-account --no-scopes`).

### 1.6 How the services start automatically

Compute Engine runs the startup script of a VM as root on every boot. Both `startup.sh` files:

1. install `git` and `python3-venv`;
2. clone the repository into `/opt/hw` (or `git pull` if it is already there);
3. create a virtualenv in `/opt/hw/venv` and install the `requirements.txt` of their service;
4. write a systemd unit (`hw4-web.service` or `hw4-reporter.service`), then enable and start it.

| Unit setting | Effect |
|---|---|
| `WantedBy=multi-user.target` + `systemctl enable` | starts on every boot |
| `Restart=always` | restarts the service if it crashes (service 2 also waits 5 s, `RestartSec=5`) |
| `DynamicUser=yes` | runs as a temporary unprivileged user instead of root |
| `AmbientCapabilities=CAP_NET_BIND_SERVICE` | (service 1 only) lets that unprivileged user bind port 80 |

Standard output and standard error of both services go to the systemd journal.

### 1.7 Check that the services are running

```bash
gcloud compute instances get-serial-port-output hw4-web --zone=us-central1-a | grep startup-script | tail -n 5
gcloud compute ssh hw4-web --zone=us-central1-a --command="sudo systemctl status hw4-web --no-pager"
gcloud compute ssh hw4-reporter --zone=us-central1-a --command="sudo systemctl status hw4-reporter --no-pager"
```

The serial output ends with `Finished running startup scripts`, and both services are `active (running)`.

### 1.8 Updating the code

Push the change, then run the startup script again on the VM. It pulls the code, reinstalls the
requirements and restarts the service:

```bash
gcloud compute ssh hw4-web --zone=us-central1-a --command="sudo google_metadata_script_runner startup"
gcloud compute ssh hw4-reporter --zone=us-central1-a --command="sudo google_metadata_script_runner startup"
```

## 2. Using service 1

### Requests and responses

| Request | Response |
|---|---|
| `GET /pages/12.html` (`/528-zz-hw2/pages/12.html` and `528-zz-hw2/pages/12.html` also work) | `200 OK` with the file |
| `POST /` with `{"file": "pages/12.html"}` (JSON) or `file=pages/12.html` (form) | `200 OK` with the file |
| File does not exist, or no file named | `404 Not Found` |
| PUT, DELETE, HEAD, CONNECT, OPTIONS, TRACE, PATCH | `501 Not Implemented` |
| `X-country` is North Korea, Iran, Cuba, Myanmar, Iraq, Libya, Sudan, Zimbabwe or Syria (full name, case-insensitive) | `400` with the body `400 Permission Denied`, and a message to service 2 |

- Checks run in this order: method (501) → country (400) → file (200 / 404).
- The country must match the **full name**: the provided client also sends "South Sudan", which is not "Sudan".
- The provided client sends request targets without a leading slash (`528-zz-hw2/pages/12.html`). The server
  removes slashes and the bucket name from the path, so all forms above map to the object `pages/12.html`.
- The status line of a 400 response says `Bad Request` (the standard reason phrase used by Python), and the
  body says `400 Permission Denied`.
- A response to HEAD has headers only (`501`, `Content-Length: 20`) and no body, as HTTP requires.

### Logging

Every error is written to Cloud Logging as a structured entry (`log_struct`) in the log `hw4-file-server`.
It is also printed to the journal of the service.

| Status | Severity | Fields in `jsonPayload` |
|---|---|---|
| 404 | WARNING | `message`, `status`, `method`, `path`, `client`, `file` |
| 501 | ERROR | `message`, `status`, `method`, `path`, `client` |
| 400 (forbidden country) | CRITICAL | `message`, `status`, `method`, `path`, `client`, `country`, `file` |

Logs Explorer query for all three:

```
logName="projects/cs528-508221/logs/hw4-file-server"
severity>=WARNING
```

### curl

```bash
IP=34.136.109.218
curl -si http://$IP/pages/12.html | head -n 5                                                     # 200
curl -si -H "Content-Type: application/json" -d '{"file": "pages/12.html"}' http://$IP/ | head -n 5 # 200 (POST, JSON)
curl -si -d "file=pages/12.html" http://$IP/ | head -n 5                                          # 200 (POST, form)
curl -si http://$IP/pages/99999.html                                                              # 404
curl -si -d "file=pages/99999.html" http://$IP/                                                   # 404 (POST)
curl -si -X PUT http://$IP/pages/12.html                                                          # 501
curl -sI http://$IP/pages/12.html                                                                 # 501 (HEAD)
curl -si -H "X-country: North Korea" http://$IP/pages/12.html                                     # 400
curl -s -o /dev/null -w "%{http_code}\n" -H "X-country: South Sudan" http://$IP/pages/12.html     # 200
for m in PUT DELETE HEAD CONNECT OPTIONS TRACE PATCH; do curl -s -m 5 -o /dev/null -w "$m -> %{http_code}\n" -X $m http://$IP/pages/12.html; done
```

### Browser

- 200 and 404: open `http://34.136.109.218/pages/12.html` or `http://34.136.109.218/pages/99999.html`.
- 501 and 400 cannot be sent from the address bar. Open a page of the server first, then send them from
  DevTools (F12 → Console). The requests go to the same origin as the page, so no CORS rules apply:

```javascript
fetch("/pages/12.html", {method: "PUT"}).then(async r => console.log(r.status, await r.text()))
fetch("/pages/12.html", {headers: {"X-country": "Iran"}}).then(async r => console.log(r.status, await r.text()))
```

### Provided HTTP client (on a separate VM)

The client must run on a VM other than the server. The provided client is built against glibc 2.38, and
Debian 12 only has 2.36 (`GLIBC_2.38 not found`), so the client VM uses Debian 13.

```bash
gcloud compute instances create hw4-client --zone=us-central1-a --machine-type=e2-small \
    --image-family=debian-13 --image-project=debian-cloud --no-service-account --no-scopes
gcloud compute ssh hw4-client --zone=us-central1-a
```

On `hw4-client`:

```bash
curl -LO https://raw.githubusercontent.com/ayiii-a/528hw-Zijiang/main/hw4/http-client
chmod +x http-client
./http-client -d 34.136.109.218 -p 80 -b 528-zz-hw2 -w pages -i 11999 -n 100 -r 1 -v > client_output.txt
grep -E '^Requesting|^[0-9]{3} ' client_output.txt | head -n 10      # first requests and their status lines
grep -E '^[0-9]{3} ' client_output.txt | sort | uniq -c                # responses per status code
```

- `-d` / `-p`: the static IP and port 80 of the server; no `-s`, because the server uses plain HTTP.
- `-b 528-zz-hw2 -w pages -i 11999`: request `528-zz-hw2/pages/<n>.html` with n from 0 to 11999.
- Each client instance sends one request at a time and waits for its response before sending the next.
- Without `-v` the client prints nothing for successful requests.

## 3. Service 2

Service 2 opens a streaming pull on `forbidden-requests-sub`. For each message, it prints one line to
standard output and acknowledges the message:

```
2026-10-14T00:40:12.345678+00:00  FORBIDDEN request from Iran (client IP 1.2.3.4): GET pages/12.html -> 400 permission denied
```

Follow its output (Ctrl+C to stop):

```bash
gcloud compute ssh hw4-reporter --zone=us-central1-a --command="sudo journalctl -u hw4-reporter -f"
```

- While service 2 is down, messages wait in the subscription (up to 7 days). It prints them when it starts again.
- If the connection to Pub/Sub fails, the program exits and systemd restarts it after 5 seconds.

## 4. Stress test (step 8)

The server (e2-micro) is measured with `sar` (sysstat), one sample per second. Cloud Monitoring was not
used: its built-in metrics have one point per minute, and memory metrics need the Ops Agent, which uses over
100 MB of RAM and some CPU on a 1 GB VM and would distort the measurement.

```bash
# 1. record CPU, memory and network on the server for 20 minutes (keeps running after SSH closes)
gcloud compute ssh hw4-web --zone=us-central1-a --command="sudo apt-get install -y -q sysstat && sudo systemd-run --unit=hw4-sar sar -o /var/tmp/stress.sar 1 1200"

# 2. right after that, on hw4-client (in the folder with http-client): phases of 1, 2, 3 and 4 clients,
#    3 minutes each, 1 idle minute before each phase; about 16 minutes in total
curl -LO https://raw.githubusercontent.com/ayiii-a/528hw-Zijiang/main/hw4/stress/stress.sh
nohup bash stress.sh 34.136.109.218 > stress.log 2>&1 &
tail -f stress.log

# 3. in Cloud Shell, after the last phase: collect the data
gcloud compute ssh hw4-web --zone=us-central1-a --command="LC_ALL=C sadf -d /var/tmp/stress.sar -- -u -r -n DEV" > ~/sar.csv
gcloud compute ssh hw4-client --zone=us-central1-a --command="cat phases.txt" > ~/phases.txt
cloudshell download ~/sar.csv
cloudshell download ~/phases.txt
```

Then plot on any machine with matplotlib. This writes `stress.png` next to `sar.csv` and prints the average
and peak of each metric for every phase:

```bash
python hw4/stress/plot.py sar.csv phases.txt
```

`stress.sh` finds the status line of each request (the first `NNN …` line after its `Requesting` line).
A request with no status line before the next `Requesting` counts as "no response", meaning a timeout or a
connection error.

Results (2026-10-14):

| Clients | Requests/s | CPU avg / peak (% of 2 vCPUs) | Memory peak | Network peak, each direction |
|---|---|---|---|---|
| 1 | 10.3 | 3.5 / 5.6 % | 290 MB (30 %) | 1.6 MB/s |
| 2 | 23.2 | 7.0 / 10.3 % | 294 MB (30 %) | 2.6 MB/s |
| 3 | 39.5 | 11.1 / 16.8 % | 294 MB (30 %) | 4.3 MB/s |
| 4 | 55.5 | 15.7 / 22.8 % | 294 MB (30 %) | 6.3 MB/s |

The server answered every request in every phase, with no timeouts, no connection errors and no 5xx. CPU and
bandwidth grow in proportion to the request rate: about 6 ms of CPU and 78 KB (one page, received from
Cloud Storage and sent to the client) per request. Memory stays flat. The full analysis is in the report.

## 5. Cleanup

The static IP is billed by the hour even when no VM uses it. When finished:

```bash
gcloud compute instances delete hw4-web hw4-reporter hw4-client --zone=us-central1-a --quiet
gcloud compute addresses delete hw4-web-ip --region=us-central1 --quiet
gcloud compute firewall-rules delete hw4-allow-http --quiet
```

## Notes

- **One e2-micro is free per month** in us-central1. The second e2-micro and the e2-small client are billed
  by the hour, a few cents for this homework.
- **`BrokenPipeError` in the journal of `hw4-web`** at the end of each stress-test phase is expected:
  `timeout` stops the clients in the middle of a download, and the server cannot finish writing the response.
- **The server is public on port 80**, so the journal occasionally shows requests and connection resets from
  internet scanners.
- **The bucket is world-readable** (from HW2), but service 1 still reads it as `hw4-web-server` with
  `storage.objectViewer`, so it does not depend on public access.
