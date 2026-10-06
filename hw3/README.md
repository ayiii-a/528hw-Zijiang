# CS528 HW3 – File Server Microservices

## Overview

| Item | Value |
|---|---|
| GCP project | `cs528-508221` |
| Region | `us-central1` |
| Bucket (from HW2) | `gs://528-zz-hw2`, files `pages/0.html` … `pages/11999.html` |
| Service 1 | Cloud Run function (2nd gen) `hw3-file-server`, Python 3.12, HTTP trigger |
| Service 1 URL | `https://hw3-file-server-czndac72aq-uc.a.run.app` |
| Service account (both services) | `hw3-file-server@cs528-508221.iam.gserviceaccount.com` |
| Pub/Sub | topic `forbidden-requests`, pull subscription `forbidden-requests-sub` |
| Forbidden-request log | `gs://528-zz-hw2/forbidden/forbidden_requests.log` |

```
 http-client / curl / browser
            │  GET /pages/12.html   or   POST {"file": "pages/12.html"}
            ▼
 ┌───────────────────────────┐   read file    ┌──────────────────────────┐
 │ Service 1  (Cloud Run fn) │ ─────────────► │ bucket 528-zz-hw2/pages/ │
 │ runs as hw3-file-server   │                └──────────────────────────┘
 └───────────────────────────┘
            │  forbidden X-country → 400 + publish
            ▼
   topic forbidden-requests ──► subscription forbidden-requests-sub
                                          │  streaming pull
                                          ▼
                        ┌──────────────────────────────────┐   append   ┌──────────────────────────────┐
                        │ Service 2  (laptop)              │ ─────────► │ bucket 528-zz-hw2/forbidden/ │
                        │ impersonates hw3-file-server     │            │   forbidden_requests.log     │
                        └──────────────────────────────────┘            └──────────────────────────────┘
```

| Path | Content |
|---|---|
| `service1/main.py` | Service 1: serves files, returns 200 / 400 / 404 / 501, logs errors, publishes forbidden requests |
| `service1/requirements.txt` | `functions-framework`, `google-cloud-storage`, `google-cloud-pubsub` |
| `service2/subscriber.py` | Service 2: prints forbidden requests and appends them to the log in the bucket |
| `service2/requirements.txt` | `google-cloud-pubsub`, `google-cloud-storage` |

## 1. Cloud setup (run in Cloud Shell)

### 1.1 Project and APIs

```bash
gcloud config set project cs528-508221
gcloud services enable cloudfunctions.googleapis.com run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com pubsub.googleapis.com logging.googleapis.com iamcredentials.googleapis.com
```

### 1.2 Service account

```bash
gcloud iam service-accounts create hw3-file-server --display-name="HW3 file server"
SA=hw3-file-server@cs528-508221.iam.gserviceaccount.com
```

### 1.3 Pub/Sub topic and subscription

Create the subscription **before** any forbidden request is sent: Pub/Sub only keeps messages for
subscriptions that exist when a message is published. It is a pull subscription because service 2
runs on a laptop with no public endpoint.

```bash
gcloud pubsub topics create forbidden-requests
gcloud pubsub subscriptions create forbidden-requests-sub --topic=forbidden-requests
```

### 1.4 Permissions (least privilege)

| Who | Role | On | Used by |
|---|---|---|---|
| service account | `roles/storage.objectViewer` | bucket | service 1 reads files |
| service account | `roles/pubsub.publisher` | topic | service 1 publishes forbidden requests |
| service account | `roles/pubsub.subscriber` | subscription | service 2 receives messages |
| service account | `roles/storage.objectUser`, only for objects under `forbidden/` | bucket | service 2 reads and rewrites the log |
| my user account | `roles/iam.serviceAccountTokenCreator` | service account | lets service 2 on the laptop impersonate the service account |

```bash
gcloud storage buckets add-iam-policy-binding gs://528-zz-hw2 --member=serviceAccount:$SA \
    --role=roles/storage.objectViewer --condition=None
gcloud pubsub topics add-iam-policy-binding forbidden-requests --member=serviceAccount:$SA \
    --role=roles/pubsub.publisher
gcloud pubsub subscriptions add-iam-policy-binding forbidden-requests-sub --member=serviceAccount:$SA \
    --role=roles/pubsub.subscriber
gcloud storage buckets add-iam-policy-binding gs://528-zz-hw2 --member=serviceAccount:$SA \
    --role=roles/storage.objectUser \
    --condition='expression=resource.name.startsWith("projects/_/buckets/528-zz-hw2/objects/forbidden/"),title=forbidden-folder-only'
gcloud iam service-accounts add-iam-policy-binding $SA \
    --member="user:$(gcloud config get-value account)" --role=roles/iam.serviceAccountTokenCreator
```

The IAM condition requires uniform bucket-level access on the bucket
(`gcloud storage buckets describe gs://528-zz-hw2 --format="value(uniform_bucket_level_access)"` → `True`).
`objectUser` rather than `objectCreator` is needed because "appending" overwrites the log object, which
requires delete permission.

## 2. Deploy service 1 (Cloud Shell)

```bash
git clone https://github.com/ayiii-a/528hw-Zijiang.git    # or: cd 528hw-Zijiang && git pull
cd 528hw-Zijiang/hw3/service1
gcloud functions deploy hw3-file-server --gen2 --runtime=python312 --region=us-central1 --source=. \
    --entry-point=serve_file --trigger-http --allow-unauthenticated --service-account=$SA
URL=$(gcloud functions describe hw3-file-server --gen2 --region=us-central1 --format="value(serviceConfig.uri)")
echo $URL
```

- `--service-account` makes the function run as the dedicated service account instead of the default
  compute service account (which has the broad Editor role).
- `--allow-unauthenticated` lets browsers, curl and the provided client call it without logging in.
- If the build fails with a Cloud Build permission error (new projects), grant
  `roles/cloudbuild.builds.builder` to `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com` and deploy again.

## 3. Run service 2 on the laptop

Service 2 uses the same service account as service 1 through **impersonation, without a key file**.
It asks gcloud for a one-hour access token of the service account
(`gcloud auth print-access-token --impersonate-service-account=...`) and refreshes it automatically.
`gcloud auth application-default login` is **not** used.

Windows PowerShell (the gcloud CLI must be installed):

```powershell
gcloud auth login                       # signs in the gcloud CLI only, not Application Default Credentials
gcloud config get-value account         # must be the account that got Token Creator in 1.4
(gcloud auth print-access-token --impersonate-service-account=hw3-file-server@cs528-508221.iam.gserviceaccount.com).Length
cd hw3\service2
python -m venv venv
.\venv\Scripts\python -m pip install -r requirements.txt
.\venv\Scripts\python subscriber.py     # Ctrl+C to stop
```

On macOS / Linux use `python3 -m venv venv && venv/bin/pip install -r requirements.txt && venv/bin/python subscriber.py`.

- The `.Length` check prints a number (a few hundred) without showing the token. `PERMISSION_DENIED` usually
  means the Token Creator binding has not propagated yet; wait a few minutes.
- If gcloud reports `Reauthentication required`, the gcloud session has expired: run `gcloud auth login` again
  and restart service 2.
- On start, service 2 first processes all messages queued in the subscription, then waits for new ones.

## 4. Using service 1

### Requests and responses

| Request | Response |
|---|---|
| `GET <URL>/pages/12.html` (a leading `/528-zz-hw2` is also accepted) | `200 OK` with the file |
| `POST <URL>` with `{"file": "pages/12.html"}` (JSON) or `file=pages/12.html` (form) | `200 OK` with the file |
| File does not exist | `404 Not Found`, logged |
| Method other than GET / POST | `501 Not Implemented`, logged |
| `X-country` is North Korea, Iran, Cuba, Myanmar, Iraq, Libya, Sudan, Zimbabwe or Syria (exact name, case-insensitive) | `400 Permission Denied`, logged and published to Pub/Sub |

Checks run in this order: method (501) → country (400) → file (200 / 404).
Errors are logged both as a plain `print` (`textPayload`) and as a structured JSON entry (`jsonPayload`, severity WARNING).

### curl

```bash
curl -si "$URL/pages/0.html" | head -12                                                       # 200
curl -si -X POST -H "Content-Type: application/json" -d '{"file": "pages/1.html"}' "$URL" | head -12   # 200
curl -si -X POST -d "file=pages/2.html" "$URL" | head -12                                     # 200
curl -si "$URL/pages/99999.html"                                                              # 404
curl -si -X PUT -d "" "$URL/pages/0.html"                                                     # 501
curl -sI "$URL/pages/0.html"                                                                  # 501 (HEAD)
curl -si -H "X-country: Iran" "$URL/pages/0.html"                                             # 400
```

### Browser

- GET 200 / 404: open `<URL>/pages/0.html` or `<URL>/pages/99999.html` in the address bar.
- POST, 501 and 400 need DevTools (F12 → Console), **on a page of the function itself** so the requests
  are same-origin (a cross-origin PUT or custom header triggers a CORS preflight `OPTIONS`, which gets 501):

```javascript
document.body.innerHTML = '<form method="post" action="/"><input name="file" value="pages/1.html"> <button>POST</button></form>'
fetch('/pages/0.html', {method: 'PUT'}).then(r => r.text().then(t => console.log(r.status, t)))
fetch('/pages/0.html', {headers: {'X-country': 'Iran'}}).then(r => r.text().then(t => console.log(r.status, t)))
```

### Provided HTTP client

```powershell
$H = "hw3-file-server-czndac72aq-uc.a.run.app"
.\http-client.exe -d $H -p 443 -s -b $H -w pages -i 11999 -n 100 -r 1 -v | Select-String -Pattern '^Requesting|^\d{3} '
```

`-b` is the function's **host name**, not the bucket name: the client sends request targets without a
leading slash (`<bucket>/<webdir>/<n>.html`), and Google's front end reads the first segment as a host
name. With `-b 528-zz-hw2` every request gets Google's own 404 and never reaches the function.
Without `-v` the client prints nothing for successful requests.

## 5. Checking the results

Cloud Logging (Logs Explorer):

```
resource.type="cloud_run_revision"
resource.labels.service_name="hw3-file-server"
(jsonPayload.status=400 OR jsonPayload.status=404 OR jsonPayload.status=501)
```

Peek at queued Pub/Sub messages (without `--auto-ack` they are redelivered later, so service 2 still gets them):

```bash
gcloud pubsub subscriptions pull forbidden-requests-sub --limit=10
```

Forbidden-request log written by service 2:

```bash
gcloud storage cat gs://528-zz-hw2/forbidden/forbidden_requests.log | tail -20
```

## Notes

- **CONNECT and TRACE** never reach the function: Google's front end answers TRACE with 405 and CONNECT with
  400. The function itself returns 501 for both (verified with the Functions Framework test client).
- **PUT without a body** over HTTP/1.1 gets `411 Length Required` from Google's front end; send an empty body
  (`curl -X PUT -d ""`) to get the function's 501.
- **The bucket is world-readable** (from HW2), so `forbidden/forbidden_requests.log` is public as well.
- **Appending to the log** rewrites the whole object (Cloud Storage objects are immutable). A lock in service 2
  serializes the parallel Pub/Sub callbacks so no line is lost; this is fine for a single service 2 process.
