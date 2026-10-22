import json
import os
import sys

import numpy as np

CLS = {"keepalive": "cold", "restore": "cold_restore", "prewarm": "cold", "combined": "cold_restore","psp":"cold_restore"}
NAMES = sys.argv[1:] or ["poisson_p09", "periodic_p09", "bursty_p03"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")

for t in NAMES:
    for cond, cls in CLS.items():
        path = os.path.join(OUT, f"{t}_{cond}.json")
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as f:
            r = json.load(f)["requests"]
        v = np.array([x["latency_ms"] for x in r if x["controller_req_class"] == cls])
        if len(v) == 0:
            print(f"{t:13} {cond:9} no {cls} requests")
            continue
        q = np.array_split(v, 4)
        print(f"{t:13} {cond:9} n={len(v):3d} median={np.median(v):6.1f} | quarters: "
              + " ".join(f"{np.median(a):6.1f}" for a in q))