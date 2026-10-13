"""HW4 service 1: a web server on a VM that serves the files of the HW2 bucket.

GET  /pages/12.html                      -> 200 + file   (file in the path)
POST {"file": "pages/12.html"} or file=… -> 200 + file   (file in the payload)
missing file                             -> 404, Cloud Logging severity WARNING
PUT/DELETE/HEAD/CONNECT/OPTIONS/TRACE/PATCH -> 501, severity ERROR
X-country is an export-restricted country -> 400, severity CRITICAL + Pub/Sub message to service 2
"""
import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from google.api_core.exceptions import NotFound
from google.cloud import logging as cloud_logging
from google.cloud import pubsub_v1, storage

PROJECT = "cs528-508221"
BUCKET = "528-zz-hw2"
TOPIC = "forbidden-requests"
PORT = int(os.environ.get("PORT", 80))
FORBIDDEN = {"north korea", "iran", "cuba", "myanmar", "iraq", "libya", "sudan", "zimbabwe", "syria"}

# Google Cloud clients, created in main(); they authenticate as the service account of the VM
bucket = cloud_log = publisher = topic_path = None


def object_name(raw):
    """'/528-zz-hw2/pages/1.html', '/pages/1.html' and '528-zz-hw2/pages/1.html'
    (the provided client sends no leading slash) all become 'pages/1.html'."""
    name = unquote(urlsplit(raw or "").path).strip("/")
    if name.startswith(BUCKET + "/"):
        name = name[len(BUCKET) + 1:]
    return name


class Handler(BaseHTTPRequestHandler):
    server_version = "hw4-file-server"

    def reply(self, status, body, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":                 # a HEAD response never has a body
            self.wfile.write(body)

    def log_cloud(self, severity, status, message, **fields):
        """Structured entry in Cloud Logging (log name hw4-file-server), also printed to the journal."""
        entry = {"message": message, "status": status, "method": self.command,
                 "path": self.path, "client": self.client_address[0], **fields}
        print(severity, json.dumps(entry), flush=True)
        cloud_log.log_struct(entry, severity=severity)

    def requested_file(self):
        if self.command == "GET":
            return object_name(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode("utf-8", "replace")
        if "json" in (self.headers.get("Content-Type") or ""):       # {"file": "pages/1.html"}
            try:
                payload = json.loads(body)
            except ValueError:
                payload = None
            name = payload.get("file") if isinstance(payload, dict) else None
        else:                                                          # file=pages/1.html
            name = parse_qs(body).get("file", [None])[0]
        return object_name(name)

    def serve(self):
        name = self.requested_file()

        country = (self.headers.get("X-country") or "").strip()
        if country.lower() in FORBIDDEN:           # exact name: "South Sudan" is not "Sudan"
            self.log_cloud("CRITICAL", 400, f"forbidden request from {country}", country=country, file=name)
            event = {"country": country, "file": name, "method": self.command,
                     "client_ip": self.headers.get("X-client-IP"),
                     "time": datetime.now(timezone.utc).isoformat()}
            publisher.publish(topic_path, json.dumps(event).encode()).result()
            return self.reply(400, b"400 Permission Denied\n")

        try:
            data = bucket.blob(name).download_as_bytes() if name else None
        except NotFound:
            data = None
        if data is None:
            self.log_cloud("WARNING", 404, f"file not found: {name!r}", file=name)
            return self.reply(404, b"404 Not Found\n")
        self.reply(200, data, "text/html; charset=utf-8")

    def not_implemented(self):
        self.log_cloud("ERROR", 501, f"method not implemented: {self.command}")
        self.reply(501, b"501 Not Implemented\n")

    do_GET = do_POST = serve
    do_PUT = do_DELETE = do_HEAD = do_CONNECT = do_OPTIONS = do_TRACE = do_PATCH = not_implemented


def main():
    global bucket, cloud_log, publisher, topic_path
    bucket = storage.Client(project=PROJECT).bucket(BUCKET)
    cloud_log = cloud_logging.Client(project=PROJECT).logger("hw4-file-server")
    publisher = pubsub_v1.PublisherClient()
    topic_path = publisher.topic_path(PROJECT, TOPIC)
    server = ThreadingHTTPServer(("", PORT), Handler)    # one thread per request
    print(f"serving gs://{BUCKET} on port {PORT}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
