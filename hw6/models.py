"""HW6: reads the client requests from the 3NF database and trains two models on them.

Model 1 predicts the country of a request from its client IP, model 2 predicts the income group.
Each model is evaluated on its own held-out test set (20 % of the rows), and its predictions on that
test set are written to gs://528-zz-hw2/hw6/ as a CSV file, followed by summary.txt, which run.sh
waits for. It runs on the VM that run.sh creates, as the service account hw6-modeler, which logs
in to MySQL with IAM database authentication and may only SELECT from the database hw6.
"""
import csv
import io
import ipaddress
from datetime import datetime, timezone

from google.cloud import storage
from google.cloud.sql.connector import Connector
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier

INSTANCE = "cs528-508221:us-central1:hw5-db"
DB = "hw6"
DB_USER = "hw6-modeler"             # IAM database user of the service account of the VM
BUCKET = "528-zz-hw2"
PREFIX = "hw6/"
SEED = 528                          # fixed, so that the split and the trees are reproducible

# the requests of the provided client (it always asks for pages/<n>.html), with their country
QUERY = """
SELECT r.client_ip, c.name AS country, r.age, r.gender, r.time_of_day, r.income
FROM requests AS r
JOIN client_ips AS i ON i.client_ip = r.client_ip
JOIN countries AS c ON c.country_id = i.country_id
WHERE r.requested_file REGEXP '^pages/[0-9]+[.]html$'
"""


def load_rows():
    """All client requests as dicts with the keys client_ip, country, age, gender, time_of_day, income."""
    with Connector() as connector:
        conn = connector.connect(INSTANCE, "pymysql", user=DB_USER, db=DB, enable_iam_auth=True)
        with conn.cursor() as cur:
            cur.execute(QUERY)
            names = [d[0] for d in cur.description]
            rows = [dict(zip(names, row)) for row in cur.fetchall()]
        conn.close()
    for row in rows:
        row["time_of_day"] = str(row["time_of_day"])     # MySQL TIME arrives as a timedelta
    return rows


def upload(name, text, content_type):
    storage.Client().bucket(BUCKET).blob(PREFIX + name).upload_from_string(text, content_type=content_type)
    return f"gs://{BUCKET}/{PREFIX}{name}"


def to_csv(header, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")      # quotes names like "Congo, Republic of the"
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue()


def percent(value):
    return f"{100 * value:.2f} %"


def model1(rows):
    """Client IP -> country: a decision tree on the IP address read as a 32-bit number.
    The client gives every country a few /24 networks (256 consecutive addresses each), so the
    tree only has to learn which interval of numbers belongs to which country."""
    X = [[int(ipaddress.ip_address(r["client_ip"]))] for r in rows]
    y = [r["country"] for r in rows]
    ips = [r["client_ip"] for r in rows]
    X_train, X_test, y_train, y_test, _, ips_test = train_test_split(
        X, y, ips, test_size=0.2, random_state=SEED, stratify=y)
    tree = DecisionTreeClassifier(random_state=SEED).fit(X_train, y_train)
    predicted = tree.predict(X_test)
    out = [(ip, actual, guess, int(actual == guess)) for ip, actual, guess in zip(ips_test, y_test, predicted)]
    return {"train": accuracy_score(y_train, tree.predict(X_train)), "test": accuracy_score(y_test, predicted),
            "n_train": len(y_train), "n_test": len(y_test), "correct": sum(row[3] for row in out),
            "leaves": tree.get_n_leaves(), "depth": tree.get_depth(),
            "csv": to_csv(["client_ip", "actual_country", "predicted_country", "correct"], out)}


AGES = ["0-16", "17-25", "26-35", "36-45", "46-55", "56-65", "66-75", "76+"]
INCOMES = ["0-10k", "10k-20k", "20k-40k", "40k-60k", "60k-100k", "100k-150k", "150k-250k", "250k+"]
ALL_FIELDS = ["age", "gender", "time_of_day", "country"]


def income_tree():
    """Decision tree on one-hot encoded categories; with only the age, it learns the most frequent
    income group of each age group in the training set."""
    return make_pipeline(OneHotEncoder(handle_unknown="ignore"), DecisionTreeClassifier(random_state=SEED))


def model2(rows):
    """Income group from the age group, compared with all fields and with no field at all."""
    def columns(part, names):
        return [[r[name] for name in names] for r in part]

    train, test = train_test_split(rows, test_size=0.2, random_state=SEED, stratify=[r["income"] for r in rows])
    y_train, y_test = [r["income"] for r in train], [r["income"] for r in test]
    model = income_tree().fit(columns(train, ["age"]), y_train)
    predicted = model.predict(columns(test, ["age"]))
    every_field = income_tree().fit(columns(train, ALL_FIELDS), y_train)
    no_field = DummyClassifier(strategy="most_frequent").fit(columns(train, ["age"]), y_train)

    seen = {}                                          # income groups seen with each age group in training
    for r in train:
        seen.setdefault(r["age"], set()).add(r["income"])
    out = [(r["age"], r["gender"], r["time_of_day"], r["country"], r["income"], guess, int(r["income"] == guess))
           for r, guess in zip(test, predicted)]
    return {"train": accuracy_score(y_train, model.predict(columns(train, ["age"]))),
            "test": accuracy_score(y_test, predicted), "n_train": len(train), "n_test": len(test),
            "correct": sum(row[6] for row in out),
            "every_field": accuracy_score(y_test, every_field.predict(columns(test, ALL_FIELDS))),
            "no_field": accuracy_score(y_test, no_field.predict(columns(test, ["age"]))),
            "within_seen": sum(r["income"] in seen.get(r["age"], ()) for r in test) / len(test),
            "rules": [(age, model.predict([[age]])[0], [i for i in INCOMES if i in seen[age]]) for age in AGES if age in seen],
            "csv": to_csv(["age", "gender", "time_of_day", "country", "actual_income", "predicted_income",
                           "correct"], out)}


def main():
    started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = load_rows()
    m1, m2 = model1(rows), model2(rows)
    url1 = upload("model1_ip_to_country.csv", m1["csv"], "text/csv")
    url2 = upload("model2_income.csv", m2["csv"], "text/csv")
    rules = "\n".join(f"    {age:>5} -> {guess:<9}  (seen in training: {', '.join(groups)})"
                      for age, guess, groups in m2["rules"])
    summary = f"""HW6 model results ({started})
Data: {len(rows):,} client requests read from the 3NF database hw6
      (requests JOIN client_ips JOIN countries); each model has its own test set,
      20 % of the rows chosen at random (seed {SEED}, stratified by the predicted field).

Model 1: client IP -> country
  method:   decision tree on the IP address as a 32-bit number ({m1['leaves']:,} leaves, depth {m1['depth']})
  train:    {m1['n_train']:,} rows, accuracy {percent(m1['train'])}
  test:     {m1['n_test']:,} rows, accuracy {percent(m1['test'])} ({m1['correct']:,} correct)
  output:   {url1}

Model 2: age group -> income group
  method:   decision tree on the one-hot encoded age group
  train:    {m2['n_train']:,} rows, accuracy {percent(m2['train'])}
  test:     {m2['n_test']:,} rows, accuracy {percent(m2['test'])} ({m2['correct']:,} correct)
  learned:  the most frequent income group of each age group
{rules}
  compared: decision tree on age, gender, time of day and country: {percent(m2['every_field'])} on the test set;
            always the most frequent income group (no field): {percent(m2['no_field'])}
  limit:    for {percent(m2['within_seen'])} of the test rows the actual income group is one of the 3 groups
            seen with that age group in training, and these 3 are about equally likely, so about
            33 % is the best accuracy any model can reach on this data
  output:   {url2}
"""
    print(summary, flush=True)
    upload("summary.txt", summary, "text/plain")       # written last: run.sh waits for this file


if __name__ == "__main__":
    main()
