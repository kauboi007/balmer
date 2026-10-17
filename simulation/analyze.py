import csv
import json
import os
import sys

import numpy as np
from traces import TRACES

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")
CONDS = ["keepalive", "restore", "prewarm", "combined"]
FAST = ("warm", "prewarm_hit")      # requests that did not wait for any container


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def events_path(name, cond):
    p = os.path.join(OUT, f"{name}_{cond}_events.json")
    if os.path.exists(p):
        return p
    old = os.path.join(OUT, f"{name}_events.json")   # first keep-alive run used this name
    if cond == "keepalive" and os.path.exists(old):
        return old
    return None


def pct(a, q):
    return float(np.percentile(a, q)) if len(a) else float("nan")


def cost_from_events(events):
    """Single-instance model, so start/ready/expiry events pair up in order.
    up_s    = start -> expiry   (container exists, including boot/restore time)
    ready_s = ready -> expiry   (container able to serve)
    A container still alive at shutdown is closed at the last logged event."""
    up = ready = 0.0
    t_start = t_ready = last_t = None
    counts = {"prewarm_start": 0, "prewarm_wasted": 0, "prewarm_hold": 0,
              "boot_start": 0, "restore_start": 0}
    for e in events:
        ev, t = e.get("event"), e.get("monotonic")
        if t is None:                        # the config event has no clock
            continue
        last_t = t
        if ev in counts:
            counts[ev] += 1
        if ev in ("boot_start", "restore_start"):
            t_start = t
        elif ev == "boot_ready":
            t_ready = t
        elif ev in ("reaper_expired", "container_expired"):
            if t_start is not None:
                up += t - t_start
            if t_ready is not None:
                ready += t - t_ready
            t_start = t_ready = None
    if last_t is not None:
        if t_start is not None:
            up += last_t - t_start
        if t_ready is not None:
            ready += last_t - t_ready
    return up, ready, counts


def analyze(name, cond):
    rp = os.path.join(OUT, f"{name}_{cond}.json")
    if not os.path.exists(rp):
        return None
    reqs = load(rp)["requests"]
    ok = [r for r in reqs if not r["error"]]
    n = len(ok)
    lat = np.array([r["latency_ms"] for r in ok])
    classes = {}
    for r in ok:
        c = r["controller_req_class"]
        classes[c] = classes.get(c, 0) + 1
    slow = sum(v for c, v in classes.items() if c not in FAST)
    duration = max(r["scheduled_rel_sec"] for r in reqs)
    flags = sum(1 for r in ok if r["cold_flag"])
    nan = float("nan")
    row = {
        "trace": name, "cond": cond, "n": n, "errors": len(reqs) - n,
        "slow_frac": slow / n if n else nan,
        "mean_ms": float(lat.mean()) if n else nan,
        "p50_ms": pct(lat, 50), "p95_ms": pct(lat, 95), "p99_ms": pct(lat, 99),
        "up_s": nan, "ready_s": nan, "up_frac": nan,
        "pw_start": 0, "pw_hit": classes.get("prewarm_hit", 0),
        "pw_late": classes.get("late_prewarm", 0), "pw_wasted": 0, "pw_hold": 0,
        "starts": nan, "flags": flags, "dflags": nan,
        "classes": " ".join(f"{k}={v}" for k, v in sorted(classes.items())),
    }
    ep = events_path(name, cond)
    if ep:
        up, ready, c = cost_from_events(load(ep))
        starts = c["boot_start"] + c["restore_start"]
        row.update(up_s=up, ready_s=ready, up_frac=up / duration,
                   pw_start=c["prewarm_start"], pw_wasted=c["prewarm_wasted"],
                   pw_hold=c["prewarm_hold"], starts=starts,
                   dflags=flags - (starts - c["prewarm_wasted"]))
    return row


def show(rows):
    print(f"{'trace':14} {'cond':10} {'n':>6} {'slow%':>6} {'mean':>7} {'p50':>7} "
          f"{'p95':>7} {'p99':>7} {'up_s':>7} {'up%':>4} {'pw s/h/l/w/hold':>16} {'dflags':>6}")
    for r in rows:
        pw = f"{r['pw_start']}/{r['pw_hit']}/{r['pw_late']}/{r['pw_wasted']}/{r['pw_hold']}"
        print(f"{r['trace']:14} {r['cond']:10} {r['n']:6d} {100 * r['slow_frac']:6.1f} "
              f"{r['mean_ms']:7.1f} {r['p50_ms']:7.1f} {r['p95_ms']:7.1f} {r['p99_ms']:7.1f} "
              f"{r['up_s']:7.1f} {100 * r['up_frac']:4.0f} {pw:>16} {r['dflags']:6.0f}")
    print("\nslow% = share of requests that were not warm or prewarm_hit; latencies in ms;")
    print("up% = container-exists time / trace duration; pw = starts/hits/late/wasted/holds")


if __name__ == "__main__":
    names = sys.argv[1:] or TRACES
    rows = [r for name in names for cond in CONDS if (r := analyze(name, cond))]
    if not rows:
        sys.exit("no results found in " + OUT)
    show(rows)
    path = os.path.join(OUT, "summary.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {path}")