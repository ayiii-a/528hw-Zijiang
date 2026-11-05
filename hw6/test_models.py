"""Local check of models.py on data generated the way the provided client generates it:
every country owns 1-9 random /24 networks, and the income group is one of the three groups next
to the age group (wrapping around). Run: python test_models.py"""
import random
import sys
import types

for name in ("google.cloud.sql.connector",):             # not needed without a database
    stub = types.ModuleType(name)
    stub.Connector = None
    sys.modules[name] = stub
import models

INCOMES = ["0-10k", "10k-20k", "20k-40k", "40k-60k", "60k-100k", "100k-150k", "150k-250k", "250k+"]
rnd = random.Random(1)
networks = {f"country {c}": [rnd.randrange(16_000_000) for _ in range(rnd.randrange(1, 10))] for c in range(197)}


def request():
    country = rnd.choice(list(networks))
    net = rnd.choice(networks[country])
    age = rnd.randrange(8)
    return {"client_ip": f"{net >> 16}.{(net >> 8) & 255}.{net & 255}.{rnd.randrange(256)}", "country": country,
            "age": models.AGES[age], "gender": rnd.choice(["Male", "Female"]),
            "time_of_day": f"{rnd.randrange(24):02d}:00:00", "income": INCOMES[(age + rnd.randrange(-1, 2)) % 8]}


uploads = {}
models.load_rows = lambda: [request() for _ in range(100_000)]
models.upload = lambda name, text, kind: uploads.setdefault(name, text) and f"gs://{models.BUCKET}/{models.PREFIX}{name}"
models.main()

assert list(uploads) == ["model1_ip_to_country.csv", "model2_income.csv", "summary.txt"]   # summary last
lines1, lines2 = uploads["model1_ip_to_country.csv"].splitlines(), uploads["model2_income.csv"].splitlines()
assert lines1[0] == "client_ip,actual_country,predicted_country,correct" and len(lines1) == 20_001
assert lines2[0].startswith("age,gender,time_of_day,country,actual_income") and len(lines2) == 20_001
m1, m2 = float(uploads["summary.txt"].split("test:")[1].split("accuracy ")[1].split(" %")[0]), \
         float(uploads["summary.txt"].split("test:")[2].split("accuracy ")[1].split(" %")[0])
assert m1 >= 99, m1
assert 31 < m2 < 36, m2
print(f"checks passed: model 1 {m1} %, model 2 {m2} %")
