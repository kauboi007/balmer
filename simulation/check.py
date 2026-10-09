import json
import sys
import numpy as np

trace_path, log_path = sys.argv[1], sys.argv[2]
events_path = sys.argv[3] if len(sys.argv) > 3 else None

d = json.load(open(trace_path, encoding="utf-8"))
log = json.load(open(log_path, encoding="utf-8"))
reqs = log["requests"]
meta = log["metadata"]
T = d["metadata"]["t"]
k = meta["k"]
n = len(reqs)
gaps = np.diff(d["trace"][:n], prepend=-1e9)

problems = 0
counts = {}
pred_cold = 0
prev = None
for i, r in enumerate(reqs):
    act = r["controller_req_class"] or "error"
    counts[act] = counts.get(act, 0) + 1
    pred = "cold" if gaps[i] > T else "warm"
    pred_cold += pred == "cold"
    boundary = abs(gaps[i] - T) / k < 0.01
    ok = act == pred or boundary or (act == "cold_wait" and prev in ("cold", "cold_wait"))
    if not ok:
        problems += 1
        print("MISMATCH", i, "gap", round(float(gaps[i]), 3), "pred", pred, "got", act)
    prev = act

errs = sum(r["error"] is not None for r in reqs)
if errs:
    problems += 1
lags = [r["lag_ms"] for r in reqs]
if max(lags) > 50:
    problems += 1
    print("LAG TOO HIGH, run not valid")

print(f"n={n} errors={errs} classes={counts}")
cold_frac = (counts.get("cold", 0) + counts.get("cold_wait", 0)) / n
print(f"cold fraction (cold + cold_wait) = {cold_frac:.3f} | predicted from trace = {pred_cold / n:.3f}")
print(f"lag ms: mean={np.mean(lags):.2f} max={max(lags):.2f}")
for c in counts:
    v = [r["latency_ms"] for r in reqs if (r["controller_req_class"] or "error") == c and r["error"] is None]
    if v:
        print(f"latency {c}: median={np.median(v):.1f} ms p95={np.percentile(v, 95):.1f} ms n={len(v)}")

if events_path:
    ev = json.load(open(events_path, encoding="utf-8"))
    cfg = [e for e in ev if e.get("event") == "config"]
    boots = sum(1 for e in ev if e.get("event") == "boot_ready")
    flags = sum(1 for r in reqs if r["cold_flag"] is True)
    print(f"t_prime controller={cfg[0]['t_prime'] if cfg else None} replayer={meta['t_prime']}")
    if not cfg or abs(cfg[0]["t_prime"] - meta["t_prime"]) > 1e-9:
        problems += 1
        print("T' MISMATCH between controller and replayer")
    print(f"containers booted={boots} function cold flags={flags}")
    if boots != flags:
        problems += 1
        print("COLD FLAG COUNT MISMATCH")

print("PASS" if problems == 0 else f"PROBLEMS: {problems}")