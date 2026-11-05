-- Overview of the 3NF database hw6 (read only):  python db_sql.py show_schema.sql

-- 1. tables and views of hw6 with their number of rows
SELECT 'countries' AS name, 'table' AS kind, COUNT(*) AS row_count FROM hw6.countries
UNION ALL SELECT 'client_ips', 'table', COUNT(*) FROM hw6.client_ips
UNION ALL SELECT 'requests', 'table', COUNT(*) FROM hw6.requests
UNION ALL SELECT 'failed_requests', 'table', COUNT(*) FROM hw6.failed_requests
UNION ALL SELECT 'request_details', 'view', COUNT(*) FROM hw6.request_details
UNION ALL SELECT 'failed_request_details', 'view', COUNT(*) FROM hw6.failed_request_details;

-- 2. columns of the tables (key: PRI = primary key, UNI = unique, MUL = indexed foreign key)
SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name, COLUMN_TYPE AS column_type,
       IS_NULLABLE AS nullable, COLUMN_KEY AS column_key
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'hw6' AND TABLE_NAME IN ('countries', 'client_ips', 'requests', 'failed_requests')
ORDER BY FIELD(TABLE_NAME, 'countries', 'client_ips', 'requests', 'failed_requests'), ORDINAL_POSITION;

-- 3. foreign keys
SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name,
       REFERENCED_TABLE_NAME AS references_table, REFERENCED_COLUMN_NAME AS references_column
FROM information_schema.KEY_COLUMN_USAGE
WHERE TABLE_SCHEMA = 'hw6' AND REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY FIELD(TABLE_NAME, 'client_ips', 'requests', 'failed_requests');

-- 4. countries: the 9 banned countries and the first 3 others
(SELECT * FROM hw6.countries WHERE is_banned ORDER BY name)
UNION ALL
(SELECT * FROM hw6.countries WHERE NOT is_banned ORDER BY country_id LIMIT 3);

-- 5. client_ips: first 5 rows
SELECT * FROM hw6.client_ips ORDER BY client_ip LIMIT 5;

-- 6. requests: first 5 client requests
SELECT * FROM hw6.requests WHERE client_ip IS NOT NULL ORDER BY request_id LIMIT 5;

-- 7. failed_requests: first 5 rows
SELECT * FROM hw6.failed_requests ORDER BY request_id LIMIT 5;

-- 8. the same failed requests joined back by the views (request_details and failed_request_details)
SELECT d.request_id, d.received_at, d.client_ip, d.country, d.is_banned, d.gender, d.age, d.income,
       d.time_of_day, d.requested_file, f.error_code
FROM hw6.request_details AS d JOIN hw6.failed_requests AS f ON f.request_id = d.request_id
ORDER BY d.request_id LIMIT 5;

SELECT * FROM hw6.failed_request_details ORDER BY request_time LIMIT 5;
