"""Creates the HW5 tables in Cloud SQL (MySQL) and lets the web server write to them.

setup.sh calls it once, right after it creates the database, with a one-time root password:
    DB_ROOT_PASSWORD=... python setup_schema.py
It connects through the Cloud SQL Python Connector with the credentials of whoever runs setup.sh.
"""
import os

from google.cloud.sql.connector import Connector

INSTANCE = "cs528-508221:us-central1:hw5-db"
DB = "hw5"
WEB_USER = "hw5-web-server"    # IAM database user of the web server service account

STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS requests (
        id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        received_at    DATETIME(6)  NOT NULL COMMENT 'when the server received the request (UTC)',
        country        VARCHAR(64),
        client_ip      VARCHAR(45),
        gender         VARCHAR(16),
        age            VARCHAR(16)  COMMENT 'age group sent by the client, e.g. 26-35',
        income         VARCHAR(16)  COMMENT 'income group sent by the client, e.g. 40k-60k',
        is_banned      BOOLEAN      NOT NULL,
        time_of_day    TIME         COMMENT 'hour from the X-time header',
        requested_file VARCHAR(255) NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS failed_requests (
        id             BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
        request_time   DATETIME(6)  NOT NULL,
        requested_file VARCHAR(255) NOT NULL,
        error_code     SMALLINT     NOT NULL
    )""",
    # the web server only adds rows; it cannot read, change or delete them
    f"GRANT INSERT ON {DB}.* TO '{WEB_USER}'@'%'",
]


def main():
    with Connector() as connector:
        conn = connector.connect(INSTANCE, "pymysql", user="root",
                                 password=os.environ["DB_ROOT_PASSWORD"], db=DB)
        with conn.cursor() as cur:
            for statement in STATEMENTS:
                cur.execute(statement)
            conn.commit()
            for table in ("requests", "failed_requests"):
                cur.execute(f"SHOW CREATE TABLE {table}")
                print(cur.fetchone()[1], end=";\n\n")
            cur.execute(f"SHOW GRANTS FOR '{WEB_USER}'@'%'")
            print("\n".join(row[0] for row in cur.fetchall()))
        conn.close()


if __name__ == "__main__":
    main()
