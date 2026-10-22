import math
import os
import sys

import numpy as np

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "..", "traffic_generators"))
import pattern_gen as pg
from policy import EwmaGapPredictor

SEEDS = range(201, 211)      # the six real traces use other seeds
MIN_GAPS = 5


def rel_errors(trace):
    p = EwmaGapPredictor(0.3)
    out = []
    for t in trace:
        p.observe(t)
        r, n = p.rel_error()
        if r is not None and n >= MIN_GAPS:
            out.append(r)
    return out


def make_sets():
    sets = {}
    for target in (0.5, 0.9):
        lam = -math.log(target) / pg.T
        sets[f"poisson_p{round(target * 10):02d}"] = [pg.poisson_trace(lam, 7200, s) for s in SEEDS]
        period = pg.calibrate(pg.periodic_trace, 2 * pg.JITTER, 4 * pg.T, target)
        sets[f"periodic_p{round(target * 10):02d}"] = [pg.periodic_trace(period, 250, s) for s in SEEDS]
    for target in (0.3, 0.5):
        ls, ll = pg.BURST_LEAVE[target]
        make = lambda x, m, s, ls=ls, ll=ll: pg.bursty_trace(x, ls, ll, m, s)
        g = pg.calibrate(make, 1.0, 5000.0, target)
        sets[f"bursty_p{round(target * 10):02d}"] = [make(g, 250, s) for s in SEEDS]
    return sets


if __name__ == "__main__":
    print("relative forecast error per arrival, pooled over seeds (lower = more predictable)")
    for name, traces in make_sets().items():
        v = np.concatenate([rel_errors(t) for t in traces])
        print(f"{name:13} n={len(v):5d}  p10={np.percentile(v, 10):.2f}  "
              f"p50={np.percentile(v, 50):.2f}  p90={np.percentile(v, 90):.2f}")