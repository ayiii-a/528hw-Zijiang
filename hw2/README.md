# CS528 HW2 – Link Statistics, PageRank and Closeness

## Project, data and code

| Item | Value |
|---|---|
| GCP project | `cs528-508221` |
| Bucket | `gs://528-zz-hw2` (region `us-central1`) |
| Data | 12,000 files `pages/0.html` … `pages/11999.html`, generated with `generate-content.py -n 12000 -m 325` |
| Code | https://github.com/ayiii-a/528hw-Zijiang (folder `hw2/`) |

The bucket is world-readable (`allUsers` has the *Storage Object Viewer* role), so the program
reads it with an anonymous client — no Google account or credentials are needed to run it.

## Requirements

- Python 3 (tested with 3.13 on a laptop, 3.12 on Cloud Shell, 3.11 on a Debian 12 VM)
- One third-party package, `google-cloud-storage` (in `requirements.txt`), used only to read the bucket
- No graph libraries: parsing, graph construction, statistics, PageRank and closeness are written in plain Python

## Setup

On a fresh Debian 12 VM, first install git and venv:

```bash
sudo apt update && sudo apt install -y git python3-venv
```

Then, on any machine:

```bash
git clone https://github.com/ayiii-a/528hw-Zijiang.git
cd 528hw-Zijiang/hw2
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python main.py > output.txt
```

With no arguments the program reads all files from `gs://528-zz-hw2/pages/`.
Results go to standard output (saved to `output.txt` above). Progress goes to standard error,
so it stays on the screen: `listing files...`, `found 12000 files, downloading...`, and progress
bars with elapsed time and ETA for the download and closeness phases.
The program is single-threaded; files are downloaded one at a time.

| Parameter | Default | Meaning |
|---|---|---|
| `--bucket BUCKET` | `528-zz-hw2` | Public GCS bucket to read |
| `--prefix PREFIX` | `pages/` | Folder inside the bucket that holds the `.html` files |
| `--local DIR` | – | Read `.html` files from a local directory instead of GCS (for debugging) |
| `-h`, `--help` | – | Show the usage message |

Examples:

```bash
python main.py --bucket another-bucket --prefix pages/
python main.py --local ./data
```

## Output

| Line | Meaning |
|---|---|
| `total nodes` | Number of pages (12,000) |
| `total out` / `total in` / `total edges` | Number of links (each link is one outgoing and one incoming link) |
| `unknown links` | Links to pages that are not in the bucket (0 for this data set) |
| `out-degree 0 nodes` | Pages with no outgoing links |
| `out-degree` / `in-degree` | Average, median, min, max and quintiles (20/40/60/80th percentiles, linear interpolation) of outgoing / incoming links per page |
| `top 5 pagerank` | The 5 pages with the highest PageRank, with their scores |
| `best page by closeness` | The page with the highest closeness centrality, with its score |
| `time` | Wall-clock time of each phase (download+parse, stats, PageRank, closeness) and the total, measured with `time.perf_counter()` |

A full run took about 39 minutes on a laptop and about 33 minutes on an e2-medium VM;
most of the time is spent downloading the files and computing closeness.

## Tests

```bash
pip install pytest
python -m pytest
```

`tests/test_graph.py` has 15 tests. Each builds a small hand-made graph whose correct answer
was computed by hand, so the tests do not depend on the randomly generated 12K-file data set:

- Link parsing and graph construction: unknown links, duplicate links, self-loops, pages without outgoing links
- PageRank: symmetric cycle, a hand-solved 4-page example, star, single page, self-loop, dangling pages, bound on the total PageRank
- Closeness: chain, complete graph, stars, a graph with unreachable nodes

## Code layout

| File | Content |
|---|---|
| `main.py` | Command-line entry point: reads the data, computes everything, prints results and timing |
| `get_txt.py` | Reads the file list and file contents from GCS (anonymous client) or a local directory |
| `graph_function.py` | Link parsing, graph construction, PageRank, closeness centrality |
| `tests/test_graph.py` | Unit tests |
| `conftest.py` | Empty file that lets pytest import the modules in `hw2/` |
