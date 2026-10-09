import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sweep_keepalive import load, model

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")
TRACES = ["poisson_p05", "periodic_p05", "bursty_p05"]
CONDS = ["keepalive", "restore", "prewarm", "combined"]
COLORS = {"keepalive": "#888888", "restore": "#1f77b4", "prewarm": "#ff7f0e", "combined": "#2ca02c"}
MARKERS = {"keepalive": "o", "restore": "s", "prewarm": "^", "combined": "D"}
SIZES = {"keepalive": 150, "restore": 60, "prewarm": 90, "combined": 90}


def read_rows():
    rows = {}
    with open(os.path.join(OUT, "summary.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["trace"]:
                rows[(r["trace"], r["cond"])] = r
    return rows


def cold_share(r):
    d = dict(kv.split("=") for kv in r["classes"].split())
    started = int(d.get("cold", 0)) + int(d.get("cold_restore", 0))
    return started / int(r["n"])


def main():
    rows = read_rows()

    # Figure 1: equal-cost view
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, t in zip(axes, TRACES):
        arr = load(t)
        grid = np.arange(0.05, 12.0, 0.05)
        res = np.array([model(arr, g) for g in grid])
        ax.plot(100 * res[:, 1], 100 * res[:, 0], color="lightgray", lw=3,
                label="plain keep-alive (T' swept)", zorder=1)
        for cond in CONDS:
            r = rows.get((t, cond))
            if r:
                ax.scatter(100 * float(r["up_frac"]), 100 * cold_share(r),
                           s=SIZES[cond], marker=MARKERS[cond], color=COLORS[cond],
                           edgecolor="black", label=cond, zorder=3)
        ax.set_title(t)
        ax.set_xlabel("container up time (% of trace)")
        ax.set_ylabel("requests that had to start a container (%)")
        ax.set_xlim(0, 105)
        ax.set_ylim(0, 105)
        ax.grid(alpha=0.3)
    axes[0].legend(loc="upper right", fontsize=8)
    fig.suptitle("Equal-cost view: points below the gray curve beat a plain longer timeout "
                 "(keepalive and restore overlap)")
    fig.tight_layout()
    p1 = os.path.join(OUT, "equal_cost.png")
    fig.savefig(p1, dpi=150)

    # Figure 2: mean latency, labelled with up time
    fig2, ax2 = plt.subplots(figsize=(9, 4.8))
    w = 0.2
    x = np.arange(len(TRACES))
    for i, cond in enumerate(CONDS):
        vals = [float(rows[(t, cond)]["mean_ms"]) for t in TRACES]
        bars = ax2.bar(x + (i - 1.5) * w, vals, w, label=cond, color=COLORS[cond])
        for b, t in zip(bars, TRACES):
            up = 100 * float(rows[(t, cond)]["up_frac"])
            ax2.text(b.get_x() + b.get_width() / 2, b.get_height() + 4,
                     f"{up:.0f}%", ha="center", fontsize=8)
    ax2.set_xticks(x)
    ax2.set_xticklabels(TRACES)
    ax2.set_ylabel("mean latency (ms)")
    ax2.set_title("Mean latency per condition (label = container up time)")
    ax2.legend()
    ax2.grid(axis="y", alpha=0.3)
    fig2.tight_layout()
    p2 = os.path.join(OUT, "mean_latency.png")
    fig2.savefig(p2, dpi=150)

    print("wrote", p1)
    print("wrote", p2)


if __name__ == "__main__":
    main()