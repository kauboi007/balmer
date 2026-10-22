import json
import os
from collections import Counter

from traces import TRACES

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
for t in TRACES:
    p = os.path.join(OUT, f"{t}_psp_events.json")
    if not os.path.exists(p):
        continue
    ev = json.load(open(p, encoding="utf-8"))
    c = Counter(e["class"] for e in ev if e.get("event") == "psp_tier")
    print(f"{t:13} high={c['high']:4d} medium={c['medium']:4d} low={c['low']:4d}")