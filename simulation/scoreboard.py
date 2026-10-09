import csv
import os

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results")
TRACES = ["poisson_p05", "periodic_p05", "bursty_p05"]
CONDS = ["keepalive", "restore", "prewarm", "combined"]


def counts(r):
    d = {k: int(v) for k, v in (kv.split("=") for kv in r["classes"].split())}
    cold = d.get("cold", 0) + d.get("cold_restore", 0)
    waited = d.get("cold_wait", 0) + d.get("late_prewarm", 0)
    warm = d.get("warm", 0) + d.get("prewarm_hit", 0)
    return cold, waited, warm


def main():
    rows = {}
    with open(os.path.join(OUT, "summary.csv"), encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["trace"]:
                rows[(r["trace"], r["cond"])] = r

    fields = ["trace", "method", "n", "cold", "waited", "warm", "up_s", "up_pct",
              "mean_ms", "p50_ms", "p95_ms", "p99_ms", "d_mean_pct", "d_cost_pct",
              "prewarm_starts", "prewarm_wasted"]
    out = []
    print(f"{'trace':13} {'method':10} {'cold':>5} {'wait':>5} {'warm':>5} {'up_s':>6} {'up%':>4} "
          f"{'mean':>6} {'p95':>6} {'p99':>6} {'dMean%':>7} {'dCost%':>7} {'prewarm start/wasted':>21}")
    for t in TRACES:
        base = rows[(t, "keepalive")]
        for c in CONDS:
            r = rows[(t, c)]
            cold, waited, warm = counts(r)
            d_mean = 100 * (float(r["mean_ms"]) / float(base["mean_ms"]) - 1)
            d_cost = 100 * (float(r["up_s"]) / float(base["up_s"]) - 1)
            ps, pw = int(r["pw_start"]), int(r["pw_wasted"])
            out.append({
                "trace": t, "method": c, "n": int(r["n"]), "cold": cold, "waited": waited,
                "warm": warm, "up_s": round(float(r["up_s"]), 1),
                "up_pct": round(100 * float(r["up_frac"]), 1),
                "mean_ms": round(float(r["mean_ms"]), 1), "p50_ms": round(float(r["p50_ms"]), 1),
                "p95_ms": round(float(r["p95_ms"]), 1), "p99_ms": round(float(r["p99_ms"]), 1),
                "d_mean_pct": round(d_mean, 1), "d_cost_pct": round(d_cost, 1),
                "prewarm_starts": ps, "prewarm_wasted": pw,
            })
            o = out[-1]
            pwtxt = f"{ps}/{pw}" if ps else "-"
            print(f"{t:13} {c:10} {cold:5d} {waited:5d} {warm:5d} {o['up_s']:6.0f} {o['up_pct']:4.0f} "
                  f"{o['mean_ms']:6.0f} {o['p95_ms']:6.0f} {o['p99_ms']:6.0f} "
                  f"{d_mean:+7.1f} {d_cost:+7.1f} {pwtxt:>21}")
        print()
    print("cold = requests that triggered a container start | wait = arrived during a start | "
          "warm = served instantly (incl. prewarm hits)")
    print("up_s = seconds a container existed | dMean%/dCost% = change vs keep-alive on that trace")

    path = os.path.join(OUT, "scoreboard.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    print("wrote", path)


if __name__ == "__main__":
    main()