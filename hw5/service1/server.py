"""HW5 service 1: the HW4 web server, extended to record every request in Cloud SQL (MySQL).

GET  /pages/12.html                      -> 200 + file   (file in the path)
POST {"file": "pages/12.html"} or file=… -> 200 + file   (file in the payload)
missing file                             -> 404, Cloud Logging severity WARNING
PUT/DELETE/HEAD/CONNECT/OPTIONS/TRACE/PATCH -> 501, severity ERROR
X-country is an export-restricted country -> 400, severity CRITICAL + Pub/Sub message to service 2

Every request becomes a row of the table requests; a request that does not get 200 is also written
to failed_requests. The four steps of a request are separate functions, timed with
time.perf_counter_ns(); each request prints one line to the journal:
    TIMING status=200 extract_ns=… gcs_ns=… send_ns=… db_ns=… total_ns=…
(gcs_ns is "-" when the file is not read, i.e. for 400 and 501).
"""
import json
import os
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from time import perf_counter_ns
from urllib.parse import parse_qs, unquote, urlsplit

import sqlalchemy
from google.api_core.exceptions import NotFound
from google.cloud import logging as cloud_logging
from google.cloud import pubsub_v1, storage
from google.cloud.sql.connector import Connector

PROJECT = "cs528-508221"
BUCKET = "528-zz-hw2"
TOPIC = "forbidden-requests"
INSTANCE = "cs528-508221:us-central1:hw5-db"
DB = "hw5"
DB_USER = "hw5-web-server"       # IAM database user of the service account of this VM
PORT = int(os.environ.get("PORT", 80))
FORBIDDEN = {"north korea", "iran", "cuba", "myanmar", "iraq", "libya", "sudan", "zimbabwe", "syria"}

INSERT_REQUEST = sqlalchemy.text(
    "INSERT INTO requests (received_at, country, client_ip, gender, age, income, is_banned,"
    " time_of_day, requested_file) VALUES (:received_at, :country, :client_ip, :gender, :age,"
    " :income, :is_banned, :time_of_day, :requested_file)")
INSERT_FAILED = sqlalchemy.text(
    "INSERT INTO failed_requests (request_time, requested_file, error_code)"
    " VALUES (:request_time, :requested_file, :error_code)")

# Google Cloud clients and the database pool, created in main(); they use the VM service account
bucket = cloud_log = publisher = topic_path = engine = None
print_lock = threading.Lock()


def log(line):
    """One complete line per write, so that lines of concurrent threads never mix in the journal."""
    with print_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def object_name(raw):
    """'/528-zz-hw2/pages/1.html', '/pages/1.html' and '528-zz-hw2/pages/1.html'
    (the provided client sends no leading slash) all become 'pages/1.html'."""
    name = unquote(urlsplit(raw or "").path).strip("/")
    if name.startswith(BUCKET + "/"):
        name = name[len(BUCKET) + 1:]
    return name


def header(handler, name, size):
    """Header value cut to the size of its column, or None if the header is missing."""
    value = (handler.headers.get(name) or "").strip()
    return value[:size] or None


def time_of_day(x_time):
    """X-time '2026-10-27 13:00:00' -> time 13:00:00; None if missing or malformed."""
    try:
        return datetime.strptime(x_time.split()[-1], "%H:%M:%S").time()
    except (AttributeError, IndexError, ValueError):
        return None


def requested_file(handler):
    if handler.command != "POST":
        return object_name(handler.path)
    body = handler.rfile.read(int(handler.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
    if "json" in (handler.headers.get("Content-Type") or ""):        # {"file": "pages/1.html"}
        try:
            payload = json.loads(body)
        except ValueError:
            payload = None
        name = payload.get("file") if isinstance(payload, dict) else None
    else:                                                              # file=pages/1.html
        name = parse_qs(body).get("file", [None])[0]
    return object_name(name if isinstance(name, str) else None)


def extract_request_info(handler):
    """Step 1: the requested file and the client information carried in the headers."""
    country = header(handler, "X-country", 64)
    return {
        "received_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "country": country,
        "client_ip": header(handler, "X-client-IP", 45),
        "gender": header(handler, "X-gender", 16),
        "age": header(handler, "X-age", 16),
        "income": header(handler, "X-income", 16),
        "is_banned": (country or "").lower() in FORBIDDEN,   # full name: "South Sudan" is not "Sudan"
        "time_of_day": time_of_day(handler.headers.get("X-time")),
        "requested_file": requested_file(handler)[:255],
    }


def read_file(name):
    """Step 2: the file from Cloud Storage, or None if it does not exist."""
    try:
        return bucket.blob(name).download_as_bytes() if name else None
    except NotFound:
        return None


def send_response(handler, status, body, content_type):
    """Step 3: status line, headers and body to the client."""
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command != "HEAD":            # a HEAD response never has a body
        handler.wfile.write(body)


def insert_into_db(info, status):
    """Step 4: one row in requests, plus one in failed_requests if the status is not 200.
    If the pooled connection turns out to be dead (the database was stopped and started again),
    SQLAlchemy drops the pool and the insert is tried once more on a new connection."""
    for attempt in (1, 2):
        try:
            with engine.begin() as conn:     # one transaction, one commit
                conn.execute(INSERT_REQUEST, info)
                if status != 200:
                    conn.execute(INSERT_FAILED, {"request_time": info["received_at"],
                                                 "requested_file": info["requested_file"],
                                                 "error_code": status})
            return
        except sqlalchemy.exc.DBAPIError as e:
            if attempt == 2 or not e.connection_invalidated:
                raise


class Handler(BaseHTTPRequestHandler):
    server_version = "hw5-file-server"

    def log_message(self, format, *args):    # access log: same lock and stream as log()
        log(f"{self.address_string()} - - [{self.log_date_time_string()}] {format % args}")

    def parse_request(self):
        self.started = perf_counter_ns()    # the request line is read; parsing the headers starts
        return super().parse_request()

    def log_cloud(self, severity, status, message, **fields):
        """Structured entry in Cloud Logging (log name hw5-file-server), also printed to the journal."""
        entry = {"message": message, "status": status, "method": self.command,
                 "path": self.path, "client": self.client_address[0], **fields}
        log(f"{severity} {json.dumps(entry)}")
        cloud_log.log_struct(entry, severity=severity)

    def handle_any(self):
        info = extract_request_info(self)
        extract_ns = perf_counter_ns() - self.started
        gcs_ns = "-"
        content_type = "text/plain; charset=utf-8"
        if self.command not in ("GET", "POST"):
            self.log_cloud("ERROR", 501, f"method not implemented: {self.command}")
            status, body = 501, b"501 Not Implemented\n"
        elif info["is_banned"]:
            self.log_cloud("CRITICAL", 400, f"forbidden request from {info['country']}",
                           country=info["country"], file=info["requested_file"])
            event = {"country": info["country"], "file": info["requested_file"], "method": self.command,
                     "client_ip": info["client_ip"], "time": datetime.now(timezone.utc).isoformat()}
            publisher.publish(topic_path, json.dumps(event).encode()).result()
            status, body = 400, b"400 Permission Denied\n"
        else:
            t = perf_counter_ns()
            data = read_file(info["requested_file"])
            gcs_ns = perf_counter_ns() - t
            if data is None:
                self.log_cloud("WARNING", 404, f"file not found: {info['requested_file']!r}",
                               file=info["requested_file"])
                status, body = 404, b"404 Not Found\n"
            else:
                status, body, content_type = 200, data, "text/html; charset=utf-8"

        t = perf_counter_ns()
        send_response(self, status, body, content_type)
        send_ns = perf_counter_ns() - t

        t = perf_counter_ns()
        try:
            insert_into_db(info, status)
        except Exception as e:               # the client already has its answer; keep serving
            log(f"DB ERROR {type(e).__name__}: {e}")
        db_ns = perf_counter_ns() - t
        log(f"TIMING status={status} extract_ns={extract_ns} gcs_ns={gcs_ns} send_ns={send_ns} "
            f"db_ns={db_ns} total_ns={perf_counter_ns() - self.started}")

    do_GET = do_POST = handle_any
    do_PUT = do_DELETE = do_HEAD = do_CONNECT = do_OPTIONS = do_TRACE = do_PATCH = handle_any


def main():
    global bucket, cloud_log, publisher, topic_path, engine
    bucket = storage.Client(project=PROJECT).bucket(BUCKET)
    cloud_log = cloud_logging.Client(project=PROJECT).logger("hw5-file-server")
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT, TOPIC)
    connector = Connector()
    # pool of logged-in connections shared by the threads. When the instance is stopped, its old
    # connections never answer again, so reads and writes time out after 10 s instead of hanging
    # (an insert normally takes a few ms); insert_into_db then retries on a new connection.
    engine = sqlalchemy.create_engine(
        "mysql+pymysql://",
        creator=lambda: connector.connect(INSTANCE, "pymysql", user=DB_USER, db=DB, enable_iam_auth=True,
                                          read_timeout=10, write_timeout=10),
        pool_size=5, max_overflow=5, pool_recycle=1800)
    server = ThreadingHTTPServer(("", PORT), Handler)    # one thread per request
    log(f"serving gs://{BUCKET} on port {PORT}, recording requests in {INSTANCE}/{DB}")
    server.serve_forever()


if __name__ == "__main__":
    main()
