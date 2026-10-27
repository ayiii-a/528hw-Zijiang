"""Local check of server.py with fake Cloud Storage, Logging, Pub/Sub and database.
Run: python test_server.py   (needs the packages in requirements.txt)"""
import http.client
import threading
from datetime import time
from http.server import ThreadingHTTPServer

from google.api_core.exceptions import NotFound

import server

PAGES = {"pages/1.html": b"<html>page 1</html>"}
rows, events, logged, lines = [], [], [], []


class Blob:
    def __init__(self, name):
        self.name = name

    def download_as_bytes(self):
        if self.name not in PAGES:
            raise NotFound(self.name)
        return PAGES[self.name]


class Conn:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, statement, params):
        if server.engine.broken:
            raise RuntimeError("database is down")
        if server.engine.dead_connections:
            server.engine.dead_connections -= 1
            raise server.sqlalchemy.exc.OperationalError("INSERT", {}, Exception("gone"),
                                                         connection_invalidated=True)
        rows.append((statement.text.split()[2], params))


class Engine:
    broken = False
    dead_connections = 0

    def begin(self):
        return Conn()


class Fake:
    pass


server.bucket = Fake()
server.bucket.blob = Blob
server.cloud_log = Fake()
server.cloud_log.log_struct = lambda entry, severity: logged.append((severity, entry["status"]))
server.publisher = Fake()
server.publisher.publish = lambda topic, data: events.append(data) or Fake()
server.Fake = Fake
Fake.result = lambda self: None
server.engine = Engine()
server.log = lines.append
server.Handler.log_message = lambda *args: None

httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()


def request(method, path, body=None, **headers):
    rows.clear(); events.clear(); logged.clear(); lines.clear()
    conn = http.client.HTTPConnection("127.0.0.1", httpd.server_address[1])
    conn.request(method, path, body, {k.replace("_", "-"): v for k, v in headers.items()})
    res = conn.getresponse()
    data = res.read()
    conn.close()
    return res.status, data


client = {"X_country": "Canada", "X_client_IP": "1.2.3.4", "X_gender": "Female",
          "X_age": "26-35", "X_income": "40k-60k", "X_time": "2026-10-27 13:00:00"}

# 200 by GET, with the path the provided client sends (no leading slash)
assert request("GET", "528-zz-hw2/pages/1.html", **client) == (200, PAGES["pages/1.html"])
(table, r), = rows
assert table == "requests" and r["country"] == "Canada" and r["client_ip"] == "1.2.3.4"
assert (r["gender"], r["age"], r["income"]) == ("Female", "26-35", "40k-60k")
assert r["time_of_day"] == time(13) and r["is_banned"] is False and r["requested_file"] == "pages/1.html"
timing = dict(f.split("=") for f in lines[-1].split()[1:])
assert lines[-1].startswith("TIMING") and timing["status"] == "200" and timing["gcs_ns"] != "-"
assert all(int(timing[k]) > 0 for k in ("extract_ns", "gcs_ns", "send_ns", "db_ns", "total_ns"))

# 200 by POST, JSON and form
assert request("POST", "/", '{"file": "pages/1.html"}', Content_Type="application/json")[0] == 200
assert rows[0][1]["requested_file"] == "pages/1.html" and rows[0][1]["country"] is None
assert request("POST", "/", "file=pages/1.html", Content_Type="application/x-www-form-urlencoded")[0] == 200

# 404: row in requests and in failed_requests, WARNING log
assert request("GET", "/pages/99999.html", **client) == (404, b"404 Not Found\n")
assert [t for t, _ in rows] == ["requests", "failed_requests"] and logged == [("WARNING", 404)]
assert rows[1][1] == {"request_time": rows[0][1]["received_at"], "requested_file": "pages/99999.html",
                      "error_code": 404}

# 400: forbidden country, exact name only
assert request("GET", "/pages/1.html", **{**client, "X_country": "Iran"})[0] == 400
assert rows[0][1]["is_banned"] is True and rows[1][1]["error_code"] == 400
assert logged == [("CRITICAL", 400)] and b'"country": "Iran"' in events[0]
assert dict(f.split("=") for f in lines[-1].split()[1:])["gcs_ns"] == "-"
assert request("GET", "/pages/1.html", **{**client, "X_country": "South Sudan"})[0] == 200

# 501 for every other method; HEAD has no body
for method in ("PUT", "DELETE", "CONNECT", "OPTIONS", "TRACE", "PATCH"):
    assert request(method, "/pages/1.html") == (501, b"501 Not Implemented\n"), method
    assert rows[1][1]["error_code"] == 501 and logged == [("ERROR", 501)]
assert request("HEAD", "/pages/1.html") == (501, b"")

# headers longer than their columns are cut; malformed X-time becomes NULL
request("GET", "/pages/1.html", X_country="x" * 100, X_time="soon")
assert len(rows[0][1]["country"]) == 64 and rows[0][1]["time_of_day"] is None

# a database failure does not break the response
server.engine.broken = True
assert request("GET", "/pages/1.html")[0] == 200
assert any(l.startswith("DB ERROR") for l in lines) and lines[-1].startswith("TIMING")
server.engine.broken = False

# a dead pooled connection (database restarted) is retried once on a new connection
server.engine.dead_connections = 1
assert request("GET", "/pages/1.html")[0] == 200
assert len(rows) == 1 and not any(l.startswith("DB ERROR") for l in lines)

httpd.shutdown()
print("all server checks passed")
