# CS528 HW6 – Normalized Database and Prediction Models

HW6 builds on the HW5 database (100,000 requests from the two provided clients, plus requests from
internet scanners). The data is moved into a schema in third normal form, and a program on a VM trains
two models on it: client IP → country (100.00 % test accuracy) and age group → income group
(33.05 %, the ceiling of this data). `run.sh` does the whole run in one command.

## Overview

| Item | Value |
|---|---|
| GCP project | `cs528-508221` (hardcoded in the scripts) |
| Database | Cloud SQL for MySQL instance `hw5-db` (from HW5); HW5 data in database `hw5`, 3NF data in database `hw6` |
| Model VM | `hw6-models` (e2-small, Debian 12), created and deleted by `run.sh` |
| Service account | `hw6-modeler`: runs the VM, logs in to MySQL as an IAM database user (`SELECT` on `hw6` only) |
| Model outputs | **`gs://528-zz-hw2/hw6/`**: `summary.txt`, `model1_ip_to_country.csv`, `model2_income.csv` (public bucket, e.g. https://storage.googleapis.com/528-zz-hw2/hw6/summary.txt) |

| File | Content |
|---|---|
| `checks.sql` | data checks: functional dependencies, age × income table, best accuracy per field |
| `migration.sql` | creates the 3NF schema in database `hw6`, transfers the data, checks the result |
| `show_schema.sql` | read-only overview of the new tables, columns, keys and sample rows |
| `db_sql.py` | runs a SQL file (or one statement) as root through the Cloud SQL Connector and prints tables |
| `models.py` | reads the data, trains and tests the two models, writes the results to the bucket |
| `requirements.txt` | packages of the model VM (Cloud SQL Connector, PyMySQL < 1.2, scikit-learn, Cloud Storage) |
| `startup.sh` | startup script of the model VM: installs the code and runs `models.py` once |
| `run.sh` | the one-command run (section 2) |
| `test_models.py` | local test of `models.py` on data generated the way the provided client generates it |

## 1. One-time preparation

Prerequisites: the HW5 instance `hw5-db` with the requests of the HW5 load test in database `hw5`;
Cloud Shell, logged in as a user with the Owner role on `cs528-508221`.

```bash
git clone https://github.com/ayiii-a/528hw-Zijiang.git    # or: git -C 528hw-Zijiang pull
gcloud config set project cs528-508221

# start the database; pause the HW5 hourly stopper while working with it
gcloud scheduler jobs pause hw5-db-stopper-hourly --location=us-central1
gcloud sql instances patch hw5-db --activation-policy=ALWAYS --async --quiet
gcloud sql instances describe hw5-db --format="value(settings.activationPolicy,state)"   # repeat until ALWAYS RUNNABLE

# service account of the model program and its IAM database user (needed by the GRANT in migration.sql)
gcloud iam service-accounts create hw6-modeler --display-name="HW6 model program"
gcloud sql users create hw6-modeler@cs528-508221.iam.gserviceaccount.com --instance=hw5-db --type=cloud_iam_service_account

# root access for the SQL scripts
gcloud sql users set-password root --host=% --instance=hw5-db --prompt-for-password
read -rsp "root password: " DB_ROOT_PASSWORD && export DB_ROOT_PASSWORD && echo
python3 -m venv ~/hw5venv && ~/hw5venv/bin/pip install -q -r 528hw-Zijiang/hw5/requirements-setup.txt

# data checks, migration to 3NF, overview of the new schema
~/hw5venv/bin/python 528hw-Zijiang/hw6/db_sql.py 528hw-Zijiang/hw6/checks.sql
~/hw5venv/bin/python 528hw-Zijiang/hw6/db_sql.py 528hw-Zijiang/hw6/migration.sql
~/hw5venv/bin/python 528hw-Zijiang/hw6/db_sql.py 528hw-Zijiang/hw6/show_schema.sql

# done with the database for now (run.sh starts it again by itself)
gcloud sql instances patch hw5-db --activation-policy=NEVER --async --quiet
gcloud scheduler jobs resume hw5-db-stopper-hourly --location=us-central1
```

`migration.sql` drops and rebuilds database `hw6` from `hw5` each time, so it can be run again. The
HW5 tables are never changed.

## 2. Run the models (`run.sh`)

```bash
bash 528hw-Zijiang/hw6/run.sh
```

| # | Step | Details |
|---|---|---|
| 1 | Service account | creates `hw6-modeler` if needed and grants `roles/cloudsql.client` and `roles/cloudsql.instanceUser` (project), and `roles/storage.objectCreator` on the bucket, **restricted by an IAM condition to objects under `hw6/`** |
| 2 | Start the database | pauses the HW5 hourly stopper, starts `hw5-db` with `--async` and polls every 20 s, for up to 30 minutes, until it is `ALWAYS` / `RUNNABLE` (a start after a long stop includes pending maintenance and can take over 15 minutes); adds the IAM database user if it is missing |
| 3 | Create the VM | deletes the results of an earlier run under `gs://528-zz-hw2/hw6/`; creates `hw6-models` with `startup.sh` as its startup script |
| 4 | Run the models | `startup.sh` (first boot only) installs Git and Python, clones the repository, installs `requirements.txt` and runs `models.py`; if a step fails it uploads its log as `hw6/error.log`. The VM is never configured with `gcloud compute ssh`. |
| 5 | Wait | polls the bucket every 15 s, for up to 30 minutes, until `summary.txt` (written last) or `error.log` appears |
| 6 | Clean up | **stops the database**, **deletes the VM** and resumes the hourly stopper; a `trap` runs this also when an earlier step fails, so neither is left running |
| 7 | Print | lists `gs://528-zz-hw2/hw6/`, prints `summary.txt` and the first 10 rows of both result files |

A run takes about 5 minutes plus the start of the database. The full result files have 20,000 rows each:

```bash
gcloud storage cat gs://528-zz-hw2/hw6/model1_ip_to_country.csv | head
gcloud storage cat gs://528-zz-hw2/hw6/model2_income.csv | head
```

## 3. Schema in third normal form

The HW5 table `requests` stored `country` and `is_banned` in every request, but the data has two
functional dependencies between non-key columns (checked in `checks.sql`): **`client_ip → country`**
(none of 76,898 IPs comes with two countries) and **`country → is_banned`** (none of 197 countries has
both values). These transitive dependencies on the key break 3NF. `failed_requests` also repeated the
time and file of its request. The new schema in database `hw6`:

```
countries       (country_id PK, name UNIQUE, is_banned)
client_ips      (client_ip PK, country_id FK -> countries)
requests        (request_id PK, received_at, client_ip FK -> client_ips (NULL for scanners),
                 gender, age, income, time_of_day, requested_file)
failed_requests (request_id PK FK -> requests, error_code)
```

In every table each non-key column depends only on the key. Two views rebuild the old shapes:
`request_details` (one row per request with country and `is_banned`) and `failed_request_details`
(time, file and error code, as HW5 required). The transfer is four `INSERT … SELECT` statements in
`migration.sql`; failed requests are matched to their request by the time and file the HW5 server wrote
into both tables (no two requests share both).

Result of the migration: `requests` 100,817 / 100,817 rows (old / new), `failed_requests` 5,463 /
5,463, 76,898 client IPs, 197 countries; every old row is rebuilt exactly by the views.

## 4. Models (`models.py`)

The program logs in as `hw6-modeler` (IAM database authentication, Cloud SQL Python Connector), reads
the 100,000 client requests from `requests` ⋈ `client_ips` ⋈ `countries`, and gives each model its own
random **20 % test set** (20,000 rows, `train_test_split`, seed 528, stratified by the predicted field).

| | Model 1: client IP → country | Model 2: → income group |
|---|---|---|
| Method | decision tree on the IP address as a 32-bit number | decision tree on the one-hot encoded age group |
| Why | the client gives each country a few /24 networks (blocks of 256 consecutive addresses), so the tree learns one interval per network (984 leaves); this also covers the many test IPs never seen in training | the client draws the income uniformly among the 3 groups next to the age group (wrapping around), so the tree learns the most frequent of the 3 for each age |
| Train accuracy | 100.00 % | 33.85 % |
| **Test accuracy** | **100.00 %** (20,000 of 20,000) | **33.05 %** (6,609 of 20,000) |
| Output | `gs://528-zz-hw2/hw6/model1_ip_to_country.csv` | `gs://528-zz-hw2/hw6/model2_income.csv` |

**Why model 2 stays below 35 %.** Given the age group, the three possible income groups are equally
likely, and no other field carries information about income (alone, gender, time of day and country
reach 12.8–14.8 %, the same as always guessing the most frequent group, 12.78 %). So the best any model
can do is 1/3 ≈ 33.3 %; the tree reaches it, and a tree on all fields is no better (33.07 %). With
20,000 test rows the measured accuracy varies by about ±0.33 %, so 35 % is out of reach for this data.

`summary.txt` contains these numbers, the learned age → income rules and the comparisons.

Local test without the cloud: `python test_models.py` (needs scikit-learn).

## Notes

- **Starting the database** after it was stopped for days can show the state `MAINTENANCE` for 15 minutes
  or more, and other operations (e.g. changing a password) are refused until it ends
  (`gcloud sql operations list --instance=hw5-db`). `run.sh` waits for it.
- **The HW5 hourly stopper** (`hw5-db-stopper-hourly`) stops the database at minute 0 of every hour. Pause
  it while working with the database by hand; `run.sh` pauses and resumes it itself.
- **PyMySQL is pinned below 1.2**: version 1.2 starts its own TLS inside the connector's encrypted
  connection and the login fails.
- **The bucket is public** (from HW2), so the result files are readable by anyone; the data is synthetic.
- **Scanner requests** (no client headers, e.g. `GET /admin/config.php`) are kept in `hw6.requests` with
  `client_ip = NULL` and are left out of the models, which use only requests for `pages/<n>.html`.
- `time_of_day` appears as `3:00:00` instead of `03:00:00` in `model2_income.csv`: MySQL `TIME` values
  arrive in Python as `timedelta`.
