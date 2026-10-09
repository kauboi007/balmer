import json
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
TRACES = os.path.join(BASE, "..", "traffic_generators")
K = 2.0
FILES = {
    "poisson_p05": "p05.json",
    "periodic_p05": "periodic_p05.json",
    "bursty_p05": "bursty_p05.json",
}


def load(name):
    with open(os.path.join(TRACES, FILES[name]), encoding="utf-8") as f:
        return np.array(json.load(f)["trace"], dtype=float) / K   # compressed seconds


def model(arr, t_prime):
    """Plain keep-alive, ignoring boot time.
    cold = requests that arrive after the container expired (the first one always does)
    up   = container-exists time / trace duration (each request keeps it up
           until the next request or T' later, whichever is sooner)"""
    gaps = np.diff(arr)
    cold = 1 + int(np.sum(gaps > t_prime))
    up = t_prime + float(np.sum(np.minimum(gaps, t_prime)))
    return cold / len(arr), up / arr[-1]


if __name__ == "__main__":
    name = sys.argv[1]
    arr = load(name)
    print(f"{name}: n={len(arr)}, duration={arr[-1]:.0f} s (compressed)")
    print("T' (s)   cold%   up%")
    for t in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0):
        c, u = model(arr, t)
        mark = "   <- your keep-alive baseline" if t == 2.5 else ""
        print(f"{t:6.1f}  {100 * c:6.1f}  {100 * u:4.0f}{mark}")
    if len(sys.argv) > 2:                       # optional: an up fraction, e.g. 0.95
        grid = np.arange(0.05, 20.0, 0.05)
        res = np.array([model(arr, t) for t in grid])
        up_target = float(sys.argv[2])
        cold_at = float(np.interp(up_target, res[:, 1], res[:, 0]))
        print(f"\nplain keep-alive at up% = {100 * up_target:.0f}: cold% = {100 * cold_at:.1f}")