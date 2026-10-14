"""Step 8: plots CPU, memory and network use of the web server during the stress test,
and prints the average and peak of each metric for every phase.

usage: python plot.py sar.csv phases.txt          -> writes stress.png next to sar.csv
  sar.csv    = output of  sadf -d /var/tmp/stress.sar -- -u -r -n DEV  on the server VM
  phases.txt = written by stress.sh on the client VM, one "<clients> <start> <end>" line per phase
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BLUE, ORANGE, INK, MUTED = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e"


def epoch(ts):
    """sadf -d prints '2026-10-13 20:00:01 UTC' (or epoch seconds with -U)."""
    if ts.isdigit():
        return int(ts)
    return int(datetime.strptime(ts.removesuffix(" UTC"), "%Y-%m-%d %H:%M:%S")
               .replace(tzinfo=timezone.utc).timestamp())


def read_sar(path):
    """Per-second series from sadf output, which has one '# hostname;...' header per activity."""
    s = {k: {} for k in ("cpu", "steal", "mem", "rx", "tx")}
    header = None
    for line in Path(path).read_text().splitlines():
        if line.startswith("#"):
            header = line.lstrip("# ").split(";")
        elif line.strip() and header:
            r = dict(zip(header, line.split(";")))
            t = epoch(r["timestamp"])
            if "%idle" in r and r.get("CPU") in ("-1", "all"):
                s["cpu"][t] = 100 - float(r["%idle"]) - float(r["%steal"])
                s["steal"][t] = float(r["%steal"])
            elif "%memused" in r:
                s["mem"][t] = float(r["%memused"])
            elif "IFACE" in r and r["IFACE"] != "lo":
                s["rx"][t] = s["rx"].get(t, 0) + float(r["rxkB/s"])
                s["tx"][t] = s["tx"].get(t, 0) + float(r["txkB/s"])
    return s


def main(sar_csv, phases_txt):
    s = read_sar(sar_csv)
    phases = [tuple(map(int, l.split())) for l in Path(phases_txt).read_text().splitlines() if l.strip()]
    t0, t1 = phases[0][1] - 60, phases[-1][2] + 30          # from the idle minute before phase 1

    fig, axes = plt.subplots(3, 1, sharex=True, figsize=(10, 7.5))
    panels = [("CPU (% of 2 vCPUs)", [("cpu", "busy", BLUE), ("steal", "steal (throttled)", ORANGE)]),
              ("memory used (%)", [("mem", None, BLUE)]),
              ("network (kB/s)", [("tx", "sent", BLUE), ("rx", "received", ORANGE)])]
    for ax, (ylabel, lines) in zip(axes, panels):
        for key, label, color in lines:
            ts = sorted(t for t in s[key] if t0 <= t <= t1)
            ax.plot([(t - t0) / 60 for t in ts], [s[key][t] for t in ts], color=color, lw=1.2, label=label)
        for n, a, b in phases:
            ax.axvspan((a - t0) / 60, (b - t0) / 60, color=MUTED, alpha=0.05 + 0.03 * n, lw=0)
        ax.set_ylabel(ylabel, color=INK)
        ax.set_ylim(bottom=0)
        ax.grid(axis="y", color=MUTED, alpha=0.2)
        ax.tick_params(colors=MUTED)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        if len(lines) > 1:
            ax.legend(loc="upper left", frameon=False, labelcolor=INK)
    for n, a, b in phases:
        axes[0].text(((a + b) / 2 - t0) / 60, 1.03, f"{n} client{'s' if n > 1 else ''}", color=INK,
                     ha="center", transform=axes[0].get_xaxis_transform())
    axes[-1].set_xlabel("minutes since start of test", color=INK)
    out = Path(sar_csv).with_name("stress.png")
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"wrote {out}\n")

    def stats(key, a, b):
        v = [x for t, x in s[key].items() if a <= t <= b] or [0]
        return f"{sum(v) / len(v):7.1f} / {max(v):7.1f}"
    print("clients | CPU busy % avg/peak | steal % avg/peak | memory % avg/peak | sent kB/s avg/peak | received kB/s avg/peak")
    for n, a, b in phases:
        print(f"{n:7} | {stats('cpu', a, b)} | {stats('steal', a, b)} | {stats('mem', a, b)} | "
              f"{stats('tx', a, b)} | {stats('rx', a, b)}")


if __name__ == "__main__":
    main(*sys.argv[1:3])
