import json
import math
import os
import random
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
T = 5.0
JITTER = 1.5
G_SHORT = 0.5
CAL_N = 100000
CAL_SEED = 99991
POISSON_DURATION = 1800
POISSON_CONFIGS = [(0.5, 7), (0.9, 8)]

BURST_LEAVE = {0.3: (0.2, 0.3), 0.5: (0.2, 0.0667)}
CONFIGS = [
    ("periodic", 0.5, 250, 101),
    ("periodic", 0.9, 250, 102),
    ("bursty", 0.3, 250, 105),
    ("bursty", 0.5, 250, 103),
]


def poisson_trace(lamda, duration, seed):
    reqs = []
    rng = random.Random(seed)
    s = 0
    while s < duration:
        u = rng.uniform(0, 1)
        if u == 0:
            continue
        t = -math.log(u) / lamda
        reqs.append(t + s)
        s += t
    return reqs[:-1]


def periodic_trace(period, n, seed):
    rng = random.Random(seed)
    return [i * period + rng.uniform(-JITTER, JITTER) for i in range(1, n + 1)]


def bursty_trace(G, leave_s, leave_l, n, seed):
    rng = random.Random(seed)
    in_burst = rng.random() < leave_l / (leave_s + leave_l)
    t = 0.0
    out = []
    while len(out) < n:
        t += rng.expovariate(1.0 / (G_SHORT if in_burst else G))
        out.append(t)
        if in_burst:
            if rng.random() < leave_s:
                in_burst = False
        elif rng.random() < leave_l:
            in_burst = True
    return out


def gap_stats(trace):
    gaps = np.diff(trace)
    p = float((gaps > T).mean())
    cv = float(gaps.std() / gaps.mean())
    ac1 = float(np.corrcoef(gaps[:-1], gaps[1:])[0, 1])
    return p, float(gaps.mean()), cv, ac1


def calibrate(make, lo, hi, target, iters=30):
    for _ in range(iters):
        mid = (lo + hi) / 2
        gaps = np.diff(make(mid, CAL_N, CAL_SEED))
        if (gaps > T).mean() < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def save(name, meta, trace):
    with open(os.path.join(HERE, name), "w", encoding="utf-8") as f:
        json.dump({"metadata": meta, "trace": trace}, f)


if __name__ == "__main__":
    for target, seed in POISSON_CONFIGS:
        lam = -math.log(target) / T
        trace = poisson_trace(lam, POISSON_DURATION, seed)
        name = f"p{round(target * 10):02d}.json"
        path = os.path.join(HERE, name)
        same = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                same = json.load(f)["trace"] == trace
        print(f"poisson  target={target} n={len(trace)} matches existing file: {same}")
        if same is False:
            print("  MISMATCH with the existing trace, not overwriting")
            continue
        meta = {"lamda": lam, "duration": POISSON_DURATION, "pval": target, "t": T,
                "seed": seed, "pattern": "poisson", "n": len(trace)}
        save(name, meta, trace)

    for pattern, target, n, seed in CONFIGS:
        if pattern == "periodic":
            make = lambda x, m, s: periodic_trace(x, m, s)
            param = calibrate(make, 2 * JITTER, 4 * T, target)
            params = {"period": param, "jitter": JITTER}
        else:
            ls, ll = BURST_LEAVE[target]
            make = lambda x, m, s, ls=ls, ll=ll: bursty_trace(x, ls, ll, m, s)
            param = calibrate(make, 1.0, 5000.0, target)
            params = {"G_long": param, "g_short": G_SHORT, "leave_burst": ls, "leave_long": ll}

        cal_p, cal_mean, cal_cv, cal_ac = gap_stats(make(param, CAL_N, CAL_SEED + 1))
        trace = make(param, n, seed)
        p, mean, cv, ac1 = gap_stats(trace)

        meta = {"pattern": pattern, "pval": target, "t": T, "seed": seed, "n": n,
                "duration": trace[-1], "params": params,
                "calibration_check_p": cal_p, "realized_p": p}
        save(f"{pattern}_p{round(target * 10):02d}.json", meta, trace)

        status = "ok" if abs(cal_p - target) < 0.01 else "CHECK"
        print(f"{pattern:8s} target={target} param={param:.3f} | long-trace p={cal_p:.4f} [{status}] "
              f"cv={cal_cv:.2f} lag1={cal_ac:+.2f} | saved n={n} realized p={p:.3f} "
              f"mean gap={mean:.2f}s span={trace[-1]:.0f}s")