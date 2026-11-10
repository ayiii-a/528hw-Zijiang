# CS528 HW7 – Link and Trigram Statistics with Apache Beam and Cloud Dataflow

## Overview

One Apache Beam pipeline reads the 12,000 HTML pages of HW2 once and finds

- the 5 files with the most **incoming** links,
- the 5 files with the most **outgoing** links,
- the 5 most frequent **word trigrams** (three consecutive words).

The same code runs on the laptop and on Cloud Dataflow; both gave identical results.

| Item | Value |
|---|---|
| GCP project / region | `cs528-508221` / `us-central1` |
| Input (from HW2) | `gs://528-zz-hw2/pages/0.html` … `11999.html` |
| Results | `gs://528-zz-hw2/hw7/output/<runner>/top_incoming.txt`, `top_outgoing.txt`, `top_trigrams.txt` |
| Dataflow staging / temp | `gs://528-zz-hw2/hw7/staging`, `gs://528-zz-hw2/hw7/tmp` |
| Dataflow workers | service account `hw7-dataflow`, `e2-standard-2`, at most 4 |
| Apache Beam | 2.77.0 (Python) |

| File | Purpose |
|---|---|
| `pipeline.py` | the Beam pipeline; prints the results and the run time when it has finished |
| `setup_dataflow.sh` | once: enables the APIs and creates the worker service account |
| `run_dataflow.sh` | installs Beam in Cloud Shell and runs the pipeline on Dataflow |
| `test_pipeline.py` | local check: compares the pipeline's results with a plain Python computation |

## Results

Top 5 files with the most incoming links (4 files share the 5th count, 207):

| Rank | File | Incoming links |
|---|---|---|
| 1 | `5984.html` | 233 |
| 2 | `6710.html` | 210 |
| 3 | `9835.html` | 209 |
| 4 | `1912.html` | 208 |
| 5 | `4183.html` | 207 |

Top 5 files with the most outgoing links (34 files share the maximum, 323; the first 5 by page number are shown):

| Rank | File | Outgoing links |
|---|---|---|
| 1 | `93.html` | 323 |
| 2 | `130.html` | 323 |
| 3 | `944.html` | 323 |
| 4 | `978.html` | 323 |
| 5 | `1698.html` | 323 |

Top 5 most frequent word trigrams (71 trigrams share the maximum, 1,946,934; the first 5 alphabetically are shown):

| Rank | Trigram | Occurrences |
|---|---|---|
| 1 | `ad minim veniam` | 1,946,934 |
| 2 | `adipiscing elit sed` | 1,946,934 |
| 3 | `aliqua ut enim` | 1,946,934 |
| 4 | `aliquip ex ea` | 1,946,934 |
| 5 | `amet consectetur adipiscing` | 1,946,934 |

**Why 71 trigrams tie.** HW2's generator builds every page from the same *Lorem ipsum* paragraph,
repeated once per link, each copy followed by `<a HREF="N.html"> This is a link </a>`. Without the
tags, a page with *k* links is the same 73-word unit (*paragraph + "this is a link"*) repeated *k* times,
and no trigram occurs twice within the unit. So each of the unit's 71 inner trigrams occurs exactly once
per link, and its total is the total number of links in the dataset, 1,946,934. The two trigrams that
span two units (`a link lorem`, `link lorem ipsum`) do not follow the last unit of a page, so they occur
once fewer per page. The data has no single most frequent trigram, and the output reports the tie
instead of hiding it.

| Run | Time from start to results (printed by `pipeline.py`) |
|---|---|
| Laptop, `FnApiRunner`, 8 threads | 1757.4 s (29.3 min) |
| Cloud Dataflow, up to 4 × `e2-standard-2` | 752.0 s (12.5 min) |

See [section 4](#4-run-times) for the comparison.

## 1. Run on Cloud Dataflow (Cloud Shell)

```bash
gcloud config set project cs528-508221
git clone https://github.com/ayiii-a/528hw-Zijiang.git    # or: git -C ~/528hw-Zijiang pull
bash ~/528hw-Zijiang/hw7/setup_dataflow.sh                  # once
bash ~/528hw-Zijiang/hw7/run_dataflow.sh
```

`setup_dataflow.sh` enables the Dataflow, Compute Engine, Cloud Storage and Logging APIs and creates the
worker service account `hw7-dataflow` with only these roles (every step is skipped if already done):

| Role | On | Why |
|---|---|---|
| `roles/dataflow.worker` | project | run Dataflow work items, write worker logs |
| `roles/storage.objectViewer` | bucket `528-zz-hw2` | read the pages and the staged pipeline files |
| `roles/storage.objectAdmin`, only for objects under `hw7/` (IAM condition) | bucket `528-zz-hw2` | write staging files, temporary files and results; it cannot change the HW2 pages |

The bucket already has conditional bindings from earlier homework, so the unconditional bindings need
`--condition=None`.

`run_dataflow.sh` installs `apache-beam[gcp]==2.77.0` in the virtualenv `~/beam-venv` and submits the job:

| Option | Value | Why |
|---|---|---|
| `--runner` | `DataflowRunner` | run on Cloud Dataflow |
| `--region` | `us-central1` | the bucket's region, so the pages are read without cross-region traffic |
| `--staging_location`, `--temp_location` | `gs://528-zz-hw2/hw7/staging`, `gs://528-zz-hw2/hw7/tmp` | packaged code and temporary files |
| `--service_account_email` | `hw7-dataflow@cs528-508221.iam.gserviceaccount.com` | workers run as the dedicated account, not the default compute account (Editor) |
| `--machine_type`, `--max_num_workers` | `e2-standard-2`, `4` | small workers, at most 4 of them, to limit the cost |

The script waits for the job, then prints the three results and the run time. The job, its graph and
its worker count are under **Dataflow → Jobs** in the console.

## 2. Run on the laptop (Windows PowerShell)

The local run reads the pages directly from the bucket over the internet and writes its results to
`gs://528-zz-hw2/hw7/output/FnApiRunner/`.

```powershell
python -m venv $HOME\b7                                   # short path: Beam exceeds the 260-character path limit otherwise
& "$HOME\b7\Scripts\python" -m pip install "apache-beam[gcp]==2.77.0"
gcloud auth application-default login                     # credentials for reading and writing the bucket
cd 528hw-Zijiang
& "$HOME\b7\Scripts\python" hw7\pipeline.py --runner=FnApiRunner --project=cs528-508221 --direct_num_workers=8 --direct_running_mode=multi_threading
gcloud auth application-default revoke                    # afterwards
```

**Why `FnApiRunner` and not `DirectRunner`.** In Beam 2.77, `--runner=DirectRunner` hands the pipeline to
the Prism runner. Prism ignores `--direct_num_workers`, and its status connection to Python has the
300 s deadline of `--job_server_timeout`, so the full run failed after five minutes with
`DEADLINE_EXCEEDED`. `FnApiRunner` is Beam's in-process Python runner (what `DirectRunner` used before
Prism): it has no such deadline and runs 8 threads with the options above. `DirectRunner` is fine for
short runs such as `test_pipeline.py`.

## 3. How the code works (`pipeline.py`)

```
MatchFiles(gs://528-zz-hw2/pages/*.html) ─► Spread (Reshuffle) ─► ReadMatches ─► ReadPages: (file name, HTML)
                                                                                     │
       ┌──────────────────────────────────────┬──────────────────────────────────────┴──────┐
       ▼                                      ▼                                             ▼
 Links: every link target            CountOutgoing:                               TrigramsPerPage:
 CountIncoming: Count.PerElement     (file, number of links)                      per-page counts
       │                                      │                                   SumTrigrams: CombinePerKey(sum)
       ▼                                      ▼                                             ▼
 Top + Tied ─► top_incoming.txt       Top + Tied ─► top_outgoing.txt               Top + Tied ─► top_trigrams.txt
```

- **Reading.** `fileio.MatchFiles` lists the 12,000 pages, `ReadMatches` opens them and `ReadPages` reads
  each one into `(file name, HTML text)`. Whole files, not lines, are read so that every link stays with
  the page it comes from. `Spread` (`beam.Reshuffle`) distributes the file list over the workers;
  without it Dataflow fuses listing and reading and reads every file on one worker. If the pattern
  matches nothing, the pipeline fails (`EmptyMatchTreatment.DISALLOW`) instead of printing empty results.
- **Links** are found with HW2's regular expression `href="([^"]+)"` (case-insensitive). As in HW2, every
  link counts, including the rare duplicates within a page.
- **Outgoing links** (the easy one): each page maps to `(file, number of links)`. Every count depends on
  one file only, so nothing is exchanged between workers.
- **Incoming links**: every link becomes its target's file name, and `Count.PerElement` counts each name
  over all pages. This needs a shuffle, because the links to one file come from thousands of pages read
  on different workers.
- **Trigrams**: tags are removed, the text is lower-cased and split into words of letters and digits
  (`[a-z0-9]+`), and every three consecutive words form a trigram. There are about 142 million trigram
  occurrences, so each page first counts its own trigrams with a `Counter` and emits only a few dozen
  `(trigram, count)` pairs; `CombinePerKey(sum)` adds them over all pages. Combining early keeps the
  shuffle small and makes the local run feasible.
- **Top 5 and ties**: `Top.Of(5)` keeps the largest counts. Equal counts are ordered by page number
  (`12.html` before `100.html`) or alphabetically, so every run gives the same answer. `Tied` and
  `CountTied` count the entries that share the 5th count, and the output reports them.
- **Output**: each result is written as one text file (`WriteToText` with `shard_name_template=""`). On
  Dataflow, `print` inside the pipeline only reaches the workers' logs, so the program waits for the
  pipeline, reads the three files back with `FileSystems.open` and prints them with the run time.
- `save_main_session=True` sends the module's imports and helper functions to the Dataflow workers.

## 4. Run times

| | Laptop (`FnApiRunner`, 8 threads) | Cloud Dataflow (`us-central1`, up to 4 × `e2-standard-2`) |
|---|---|---|
| Time from start to results | 1757.4 s (29.3 min) | 752.0 s (12.5 min) |
| Reads the pages | over the home internet connection | inside Google Cloud, same region as the bucket |

Dataflow was 2.3 times faster, although its 752 s include several minutes of fixed overhead: packaging
and staging the code, starting the worker VMs, installing Beam on them and shutting them down. The job
is dominated by reading 12,000 separate objects from Cloud Storage: in the Dataflow job graph,
`ReadPages`, where each file is actually downloaded, took 42 min 18 s of worker time summed over all
threads, against 3 min 10 s for counting the trigrams. Dataflow ran these reads on several workers with
many threads each, next to the bucket. The laptop had 8 threads and fetched every file over the
internet, with a much higher latency per request; its threads also share one Python interpreter (GIL).
Dataflow's overhead stays roughly constant while the work scales with the number of workers, so the gap
would grow with more data.

## 5. Local test

```powershell
& "$HOME\b7\Scripts\python" hw7\test_pipeline.py C:\path\to\some\pages
```

Runs the pipeline on a folder of HTML pages and recomputes all three results in plain Python; it prints
`all checks passed on N pages`. Passed on a sample of 40 pages from the bucket.

## 6. Cleanup

After both runs, the staging and temporary files are no longer needed; the results stay in the bucket:

```bash
gcloud storage rm -r gs://528-zz-hw2/hw7/tmp gs://528-zz-hw2/hw7/staging
```

## Notes

- **Local paths on Windows** must use backslashes (`C:\pages\*.html`); with forward slashes the match is
  empty and the pipeline stops with `Empty match`.
- **Soft-delete warning** at submission: the bucket keeps deleted objects for a while (7 days by
  default), so the deleted temporary files are billed for that time. They are small, so the policy
  was left on.
- **The bucket is world-readable** (from HW2), so the results under `hw7/output/` are public as well.
