import csv
import math
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from sweep_keepalive import load, model
from traces import CONDS, TRACES

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")
COLORS = {"keepalive": "#888888", "restore": "#1f77b4", "prewarm": "#ff7f0e", "combined": "#2ca02c","psp": "#d62728"}
MARKERS = {"keepalive": "o", "restore": "s", "prewarm": "^", "combined": "D","psp": "P"}
SIZES = {"keepalive": 150, "restore": 60, "prewarm": 90, "combined": 90,"psp": 90}


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


def out_path(name, tag, force):
    p = os.path.join(OUT, f"{name}_{tag}.png")
    if os.path.exists(p) and not force:
        sys.exit(f"{p} already exists. Use a different tag (python plot_results.py mytag) "
                 f"or add --force to overwrite it.")
    return p


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--force" in sys.argv
    tag = args[0] if args else "all"
    p1 = out_path("equal_cost", tag, force)      # check both before drawing anything
    p2 = out_path("mean_latency", tag, force)

    rows = read_rows()
    traces = [t for t in TRACES if (t, "keepalive") in rows]
    n = len(traces)

    # Figure 1: equal-cost view, one panel per trace
    ncols = 3
    nrows = math.ceil(n / ncols)
    fig, axes = plt.subplots(nrows, ncols, figsize=(15, 4.4 * nrows), squeeze=False)
    flat = axes.flatten()
    for ax, t in zip(flat, traces):
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
        ax.set_title(f"{t} (n={len(arr)})")
        ax.set_xlabel("container up time (% of trace)")
        ax.set_ylabel("requests that had to start a container (%)")
        ax.set_xlim(0, 110)
        ax.set_ylim(0, 105)
        ax.grid(alpha=0.3)
    for ax in flat[n:]:
        ax.axis("off")
    flat[0].legend(loc="upper right", fontsize=8)
    fig.suptitle("Equal-cost view: a point below the gray curve beats a plain longer timeout "
                 "(keepalive and restore overlap)")
    fig.tight_layout()
    fig.savefig(p1, dpi=150)

    # Figure 2: mean latency, labelled with up time
    fig2, ax2 = plt.subplots(figsize=(max(9, 2.4 * n), 5))
    w = 0.16
    seen = set()
    for j, t in enumerate(traces):
        for i, cond in enumerate(CONDS):
            r = rows.get((t, cond))
            if not r:
                continue
            label = cond if cond not in seen else None
            seen.add(cond)
            xpos = j + (i - 2) * w
            h = float(r["mean_ms"])
            ax2.bar(xpos, h, w, color=COLORS[cond], label=label)
            ax2.text(xpos, h + 4, f"{100 * float(r['up_frac']):.0f}%", ha="center", fontsize=8)
    ax2.set_xticks(range(n))
    ax2.set_xticklabels(traces, rotation=15)
    ax2.set_ylabel("mean latency (ms)")
    ax2.set_title("Mean latency per condition (label = container up time)")
    ax2.legend()
    ax2.grid(axis="y", alpha=0.3)
    fig2.tight_layout()
    fig2.savefig(p2, dpi=150)

    print("wrote", p1)
    print("wrote", p2)


if __name__ == "__main__":
    main()