"""Runs SQL on the Cloud SQL database (instance hw5-db, database hw5) as root and prints the results.

    python db_sql.py checks.sql               # every statement of a file
    python db_sql.py "SELECT COUNT(*) FROM requests"
In a file, statements end with ";" and a "-- " comment line right before a statement is its title.
Needs the root password in the environment variable DB_ROOT_PASSWORD.
"""
import os
import sys
from pathlib import Path

from google.cloud.sql.connector import Connector

INSTANCE = "cs528-508221:us-central1:hw5-db"
DB = "hw5"


def statements(text):
    """(title, sql) pairs of a SQL text."""
    pairs, title, lines = [], "", []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped and not lines:      # a blank line ends a comment block
            title = ""
        if stripped.startswith("--"):
            if not lines and not title:      # the first comment line before a statement
                title = stripped.lstrip("- ")
            continue
        if stripped:
            lines.append(line)
        if stripped.endswith(";"):
            pairs.append((title, "\n".join(lines).rstrip().rstrip(";")))
            title, lines = "", []
    if lines:
        pairs.append((title, "\n".join(lines)))
    return pairs


def print_result(cur, title):
    print(f"\n{title}" if title else "")
    if cur.description is None:              # INSERT, CREATE, GRANT, ...
        print(f"  ok, {cur.rowcount} rows affected")
        return
    names = [d[0] for d in cur.description]
    rows = [["NULL" if v is None else str(v) for v in row] for row in cur.fetchall()]
    widths = [max(map(len, column)) for column in zip(names, *rows)]
    for row in [names, *rows]:
        print("  " + "  ".join(value.ljust(width) for value, width in zip(row, widths)))


def main(arg):
    text = Path(arg).read_text() if Path(arg).is_file() else arg
    with Connector() as connector:
        conn = connector.connect(INSTANCE, "pymysql", user="root",
                                 password=os.environ["DB_ROOT_PASSWORD"], db=DB)
        with conn.cursor() as cur:
            for title, sql in statements(text):
                cur.execute(sql)
                print_result(cur, title)
        conn.commit()
        conn.close()


if __name__ == "__main__":
    main(sys.argv[1])
