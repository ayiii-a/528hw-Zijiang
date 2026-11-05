-- Data checks before the 3NF design and the models. Only the requests of the provided client
-- are used: it always asks for pages/<n>.html (other rows come from internet scanners).

-- 1. functional dependency client_ip -> country: does every IP come with exactly one country?
SELECT COUNT(*) AS distinct_ips, SUM(countries > 1) AS ips_with_several_countries,
       SUM(requests = 1) AS ips_seen_once
FROM (SELECT client_ip, COUNT(DISTINCT country) AS countries, COUNT(*) AS requests
      FROM requests WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY client_ip) AS t;

-- 2. does the /24 network (first three parts of the IP) already decide the country?
SELECT COUNT(*) AS networks, SUM(countries > 1) AS networks_with_several_countries,
       MIN(requests) AS fewest_requests_per_network
FROM (SELECT SUBSTRING_INDEX(client_ip, '.', 3) AS network, COUNT(DISTINCT country) AS countries,
             COUNT(*) AS requests
      FROM requests WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY network) AS t;

-- 3. functional dependency country -> is_banned: is a country always banned or never?
SELECT COUNT(*) AS countries, SUM(values_of_is_banned > 1) AS countries_with_both_values,
       SUM(banned) AS banned_countries
FROM (SELECT country, COUNT(DISTINCT is_banned) AS values_of_is_banned, MAX(is_banned) AS banned
      FROM requests WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY country) AS t;

-- 4. age group x income group: number of requests (rows: age, columns: income)
SELECT age,
       SUM(income = '0-10k') AS `0-10k`, SUM(income = '10k-20k') AS `10k-20k`,
       SUM(income = '20k-40k') AS `20k-40k`, SUM(income = '40k-60k') AS `40k-60k`,
       SUM(income = '60k-100k') AS `60k-100k`, SUM(income = '100k-150k') AS `100k-150k`,
       SUM(income = '150k-250k') AS `150k-250k`, SUM(income = '250k+') AS `250k+`, COUNT(*) AS total
FROM requests WHERE requested_file REGEXP '^pages/[0-9]+[.]html$'
GROUP BY age ORDER BY FIELD(age, '0-16', '17-25', '26-35', '36-45', '46-55', '56-65', '66-75', '76+');

-- 5. best possible accuracy when income is predicted from one other field alone
-- (always answering the most frequent income for each value of that field, on all the data)
SELECT 'age' AS field, ROUND(100 * SUM(top) / SUM(n), 2) AS best_accuracy_percent
FROM (SELECT MAX(c) AS top, SUM(c) AS n FROM (SELECT age AS v, income, COUNT(*) AS c FROM requests
      WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY v, income) AS x GROUP BY v) AS y
UNION ALL
SELECT 'gender', ROUND(100 * SUM(top) / SUM(n), 2)
FROM (SELECT MAX(c) AS top, SUM(c) AS n FROM (SELECT gender AS v, income, COUNT(*) AS c FROM requests
      WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY v, income) AS x GROUP BY v) AS y
UNION ALL
SELECT 'time_of_day', ROUND(100 * SUM(top) / SUM(n), 2)
FROM (SELECT MAX(c) AS top, SUM(c) AS n FROM (SELECT time_of_day AS v, income, COUNT(*) AS c FROM requests
      WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY v, income) AS x GROUP BY v) AS y
UNION ALL
SELECT 'country', ROUND(100 * SUM(top) / SUM(n), 2)
FROM (SELECT MAX(c) AS top, SUM(c) AS n FROM (SELECT country AS v, income, COUNT(*) AS c FROM requests
      WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY v, income) AS x GROUP BY v) AS y
UNION ALL
SELECT 'none (most frequent income overall)', ROUND(100 * MAX(c) / SUM(c), 2)
FROM (SELECT income, COUNT(*) AS c FROM requests
      WHERE requested_file REGEXP '^pages/[0-9]+[.]html$' GROUP BY income) AS z;
