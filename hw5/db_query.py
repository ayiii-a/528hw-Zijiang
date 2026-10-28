"""Shows the HW5 tables (step 4), prints the request statistics (step 7), or empties the tables.

Run it in Cloud Shell with the root password in the environment variable DB_ROOT_PASSWORD:
    python db_query.py          # row counts and the latest rows of both tables
    python db_query.py stats    # the statistics of step 7
    python db_query.py reset    # delete all rows, e.g. right before the load test
"""
import os
import sys

from google.cloud.sql.connector import Connector

INSTANCE = "cs528-508221:us-central1:hw5-db"
DB = "hw5"

SHOW = [
    ("row counts", "SELECT (SELECT COUNT(*) FROM requests) AS requests,"
                   " (SELECT COUNT(*) FROM failed_requests) AS failed_requests"),
    ("requests, latest 5 rows", "SELECT * FROM requests ORDER BY id DESC LIMIT 5"),
    ("failed_requests, latest 5 rows", "SELECT * FROM failed_requests ORDER BY id DESC LIMIT 5"),
]
# The server is public, so internet scanners also send requests (e.g. GET /admin/config.php).
# The statistics count only the requests of the provided client, which always asks for pages/<n>.html.
CLIENT = "requested_file REGEXP '^pages/[0-9]+[.]html$'"
STATS = [
    ("0. test period and throughput (client requests)",
     "SELECT MIN(received_at) AS first_request, MAX(received_at) AS last_request,"
     " TIMESTAMPDIFF(SECOND, MIN(received_at), MAX(received_at)) AS seconds,"
     " ROUND(COUNT(*) / TIMESTAMPDIFF(SECOND, MIN(received_at), MAX(received_at)), 1) AS requests_per_second"
     f" FROM requests WHERE {CLIENT}"),
    ("   rows left out: other traffic, e.g. internet scanners",
     f"SELECT (SELECT COUNT(*) FROM requests WHERE NOT {CLIENT}) AS requests,"
     f" (SELECT COUNT(*) FROM failed_requests WHERE NOT {CLIENT}) AS failed_requests"),
    ("1. successful vs failed requests",
     f"SELECT COUNT(*) AS total, COUNT(*) - (SELECT COUNT(*) FROM failed_requests WHERE {CLIENT}) AS successful,"
     f" (SELECT COUNT(*) FROM failed_requests WHERE {CLIENT}) AS failed FROM requests WHERE {CLIENT}"),
    ("   failed requests by error code",
     f"SELECT error_code, COUNT(*) AS requests FROM failed_requests WHERE {CLIENT}"
     " GROUP BY error_code ORDER BY error_code"),
    ("2. requests from banned countries",
     f"SELECT COUNT(*) AS requests FROM requests WHERE {CLIENT} AND is_banned"),
    ("3. requests by gender",
     f"SELECT gender, COUNT(*) AS requests FROM requests WHERE {CLIENT} GROUP BY gender ORDER BY requests DESC"),
    ("4. top 5 countries",
     f"SELECT country, COUNT(*) AS requests FROM requests WHERE {CLIENT} GROUP BY country"
     " ORDER BY requests DESC, country LIMIT 5"),
    ("5. requests by age group (most first)",
     f"SELECT age, COUNT(*) AS requests FROM requests WHERE {CLIENT} GROUP BY age ORDER BY requests DESC"),
    ("6. requests by income group (most first)",
     f"SELECT income, COUNT(*) AS requests FROM requests WHERE {CLIENT} GROUP BY income ORDER BY requests DESC"),
]
RESET = ["TRUNCATE TABLE failed_requests", "TRUNCATE TABLE requests"]


def print_table(cur, title, sql):
    cur.execute(sql)
    names = [d[0] for d in cur.description]
    rows = [["NULL" if v is None else str(v) for v in row] for row in cur.fetchall()]
    widths = [max(map(len, column)) for column in zip(names, *rows)]
    print(f"\n{title}")
    for row in [names, *rows]:
        print("  " + "  ".join(value.ljust(width) for value, width in zip(row, widths)))


def main(command):
    with Connector() as connector:
        conn = connector.connect(INSTANCE, "pymysql", user="root",
                                 password=os.environ["DB_ROOT_PASSWORD"], db=DB)
        with conn.cursor() as cur:
            if command == "reset":
                for sql in RESET:
                    cur.execute(sql)
                conn.commit()
            for title, sql in STATS if command == "stats" else SHOW:
                print_table(cur, title, sql)
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "show")
