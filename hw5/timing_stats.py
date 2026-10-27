"""Step 6: statistics of the per-request timings that service 1 prints to its journal.

    gcloud compute ssh hw5-web --zone=us-central1-a --command="sudo journalctl -u hw5-web
        --since '2026-10-27 06:59:00' -o cat --no-pager" > journal.txt
    python3 timing_stats.py journal.txt
Only the lines "TIMING status=… extract_ns=… gcs_ns=… send_ns=… db_ns=… total_ns=…" are used.
"""
import statistics
import sys

STAGES = [("extract_ns", "process request, extract headers"),
          ("gcs_ns", "read file from Cloud Storage"),
          ("send_ns", "send response to client"),
          ("db_ns", "insert into database"),
          ("total_ns", "whole request (incl. logging, Pub/Sub)")]


def summary(label, ms):
    if not ms:
        return f"  {label:42} {0:>8}"
    pct = statistics.quantiles(ms, n=100, method="inclusive") if len(ms) > 1 else [ms[0]] * 99
    return (f"  {label:42} {len(ms):>8} {statistics.fmean(ms):>9.3f} {statistics.median(ms):>9.3f}"
            f" {pct[94]:>9.3f} {pct[98]:>9.3f} {max(ms):>9.3f}")


def main(path):
    ms = {key: [] for key, _ in STAGES}
    total_by_status = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("TIMING "):
                continue
            fields = dict(item.split("=", 1) for item in line.split()[1:])
            for key, _ in STAGES:
                if fields.get(key, "-") != "-":          # gcs_ns is "-" when no file was read
                    ms[key].append(int(fields[key]) / 1e6)
            total_by_status.setdefault(fields["status"], []).append(int(fields["total_ns"]) / 1e6)

    print(f"{len(ms['total_ns'])} requests; times in milliseconds\n")
    print(f"  {'step':42} {'count':>8} {'mean':>9} {'median':>9} {'p95':>9} {'p99':>9} {'max':>9}")
    for key, label in STAGES:
        print(summary(label, ms[key]))
    print("\n  whole request by status")
    for status, values in sorted(total_by_status.items()):
        print(summary(f"status {status}", values))


if __name__ == "__main__":
    main(sys.argv[1])
