-- HW6: move the HW5 data (database hw5) into a schema in third normal form (database hw6).
-- Run as root:  python db_sql.py migration.sql   (it rebuilds hw6 from hw5 and can be run again)
-- The HW5 tables are left unchanged, so the HW5 server keeps working and old and new can be compared.

-- 0. pre-check: (received_at, requested_file) identifies a request, so failed_requests can be matched
SELECT COUNT(*) - COUNT(DISTINCT received_at, requested_file) AS requests_sharing_time_and_file
FROM hw5.requests;

DROP DATABASE IF EXISTS hw6;

CREATE DATABASE hw6;

-- country -> is_banned
CREATE TABLE hw6.countries (
    country_id SMALLINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(64) NOT NULL UNIQUE,
    is_banned  BOOLEAN     NOT NULL
);

-- client_ip -> country
CREATE TABLE hw6.client_ips (
    client_ip  VARCHAR(45)       PRIMARY KEY,
    country_id SMALLINT UNSIGNED NOT NULL,
    FOREIGN KEY (country_id) REFERENCES hw6.countries (country_id)
);

-- one row per request; client_ip is NULL for requests without the client headers (internet scanners)
CREATE TABLE hw6.requests (
    request_id     BIGINT UNSIGNED PRIMARY KEY,     -- the id of the request in hw5.requests
    received_at    DATETIME(6)  NOT NULL,
    client_ip      VARCHAR(45),
    gender         VARCHAR(16),
    age            VARCHAR(16),
    income         VARCHAR(16),
    time_of_day    TIME,
    requested_file VARCHAR(255) NOT NULL,
    FOREIGN KEY (client_ip) REFERENCES hw6.client_ips (client_ip)
);

-- the requests that did not get 200
CREATE TABLE hw6.failed_requests (
    request_id BIGINT UNSIGNED PRIMARY KEY,
    error_code SMALLINT NOT NULL,
    FOREIGN KEY (request_id) REFERENCES hw6.requests (request_id)
);

-- 1. countries
INSERT INTO hw6.countries (name, is_banned)
SELECT country, MAX(is_banned) FROM hw5.requests WHERE country IS NOT NULL GROUP BY country;

-- 2. client IPs
INSERT INTO hw6.client_ips (client_ip, country_id)
SELECT r.client_ip, c.country_id
FROM (SELECT DISTINCT client_ip, country FROM hw5.requests WHERE client_ip IS NOT NULL) AS r
JOIN hw6.countries AS c ON c.name = r.country;

-- 3. requests
INSERT INTO hw6.requests (request_id, received_at, client_ip, gender, age, income, time_of_day, requested_file)
SELECT id, received_at, client_ip, gender, age, income, time_of_day, requested_file FROM hw5.requests;

-- 4. failed requests: the HW5 server wrote both rows of a failed request with the same time and file
INSERT INTO hw6.failed_requests (request_id, error_code)
SELECT MIN(r.id), f.error_code
FROM hw5.failed_requests AS f
JOIN hw5.requests AS r ON r.received_at = f.request_time AND r.requested_file = f.requested_file
GROUP BY f.id, f.error_code;

-- the old view of the data, rebuilt from the normalized tables
CREATE VIEW hw6.request_details AS
SELECT r.request_id, r.received_at, r.client_ip, c.name AS country, c.is_banned,
       r.gender, r.age, r.income, r.time_of_day, r.requested_file
FROM hw6.requests AS r
LEFT JOIN hw6.client_ips AS i ON i.client_ip = r.client_ip
LEFT JOIN hw6.countries AS c ON c.country_id = i.country_id;

CREATE VIEW hw6.failed_request_details AS
SELECT r.received_at AS request_time, r.requested_file, f.error_code
FROM hw6.failed_requests AS f JOIN hw6.requests AS r ON r.request_id = f.request_id;

-- the model program (service account hw6-modeler, IAM database user) may only read hw6
GRANT SELECT ON hw6.* TO 'hw6-modeler'@'%';

-- 5. check: row counts
SELECT (SELECT COUNT(*) FROM hw5.requests) AS old_requests,
       (SELECT COUNT(*) FROM hw6.requests) AS new_requests,
       (SELECT COUNT(*) FROM hw5.failed_requests) AS old_failed,
       (SELECT COUNT(*) FROM hw6.failed_requests) AS new_failed,
       (SELECT COUNT(*) FROM hw6.client_ips) AS client_ips,
       (SELECT COUNT(*) FROM hw6.countries) AS countries;

-- 6. check: every old request row is rebuilt exactly by the view
SELECT COUNT(*) AS rows_compared,
       SUM(NOT (o.received_at <=> d.received_at AND o.country <=> d.country
                AND o.client_ip <=> d.client_ip AND o.gender <=> d.gender AND o.age <=> d.age
                AND o.income <=> d.income AND o.time_of_day <=> d.time_of_day
                AND o.requested_file <=> d.requested_file
                AND o.is_banned <=> COALESCE(d.is_banned, 0))) AS rows_that_differ
FROM hw5.requests AS o JOIN hw6.request_details AS d ON d.request_id = o.id;

-- 7. check: every old failed request is found in the new tables
SELECT COUNT(*) AS old_failed_rows_found
FROM hw5.failed_requests AS f
JOIN hw6.failed_request_details AS d
  ON d.request_time = f.request_time AND d.requested_file = f.requested_file AND d.error_code = f.error_code;

-- 8. the new tables
SHOW FULL TABLES FROM hw6;
