import argparse
import time

from graph_function import build_graph, reverse, pagerank, best_closeness
from get_txt import local_source, gcs_source


def percentile(s, p):
    """s sorted, p in [0, 1]; linear interpolation between neighbors"""
    pos = p * (len(s) - 1)
    lo = int(pos)
    if lo + 1 == len(s):
        return s[lo]
    return s[lo] + (s[lo + 1] - s[lo]) * (pos - lo)


def get_stats(label, degrees):
    s = sorted(degrees)

    average = sum(s) / len(s)
    median = percentile(s, 0.5)
    min_val = s[0]
    max_val = s[-1]
    quintiles = [percentile(s, p) for p in (0.2, 0.4, 0.6, 0.8)]

    return average, median, min_val, max_val, quintiles


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Link statistics, PageRank and closeness of the HW2 pages.")
    parser.add_argument("--bucket", default="528-zz-hw2", help="public GCS bucket to read (default: %(default)s)")
    parser.add_argument("--prefix", default="pages/", help="folder inside the bucket (default: %(default)s)")
    parser.add_argument("--local", metavar="DIR", help="read .html files from a local directory instead of GCS")
    args = parser.parse_args()

    t0 = time.perf_counter()
    names, read = local_source(args.local) if args.local else gcs_source(args.bucket, args.prefix)
    outadj, unknown = build_graph(names, read)

    inadj = reverse(outadj)
    t1 = time.perf_counter()

    totalout = sum(len(targets) for targets in outadj)
    totalin = sum(len(sources) for sources in inadj)
    zero_out = sum(1 for targets in outadj if len(targets) == 0)
    out_stats = get_stats("out-degree", [len(targets) for targets in outadj])
    in_stats = get_stats("in-degree", [len(sources) for sources in inadj])
    t2 = time.perf_counter()

    pr = pagerank(outadj, inadj)
    t3 = time.perf_counter()

    best_page, score = best_closeness(outadj, progress=True)
    t4 = time.perf_counter()

    print("total nodes: ", len(outadj))
    print("total out: ", totalout)
    print("total in: ", totalin)
    print("total edges: ", totalout)
    print("unknown links: ", unknown)
    print("out-degree 0 nodes:", zero_out)
    for label, (average, median, min_val, max_val, quintiles) in (("out-degree", out_stats),
                                                                   ("in-degree", in_stats)):
        print(f"{label}: average={average}, median={median}, min={min_val}, max={max_val}, quintiles={quintiles}")

    # indices follow the string-sorted names (0.html, 1.html, 10.html, ...), so print names
    print("top 5 pagerank:")
    for i in sorted(range(len(pr)), key=pr.__getitem__, reverse=True)[:5]:
        print(f"  {names[i]}  {pr[i]:.6f}")
    print("best page by closeness: ", names[best_page], "closeness: ", score)

    print(f"time: download+parse={t1 - t0:.2f}s, stats={t2 - t1:.2f}s, "
          f"pagerank={t3 - t2:.2f}s, closeness={t4 - t3:.2f}s, total={t4 - t0:.2f}s")
