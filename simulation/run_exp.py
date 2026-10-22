import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time

from criu_backend import make_snapshot

BASE = os.path.dirname(os.path.abspath(__file__))
TRACES = os.path.join(BASE, "..", "traffic_generators")
OUT = os.path.join(BASE, "results")
K = 2.0
PORT = 9000
RUNS = [
    ("poisson_p05", "p05.json"),
    ("periodic_p05", "periodic_p05.json"),
    ("bursty_p05", "bursty_p05.json"),
    ("bursty_p03", "bursty_p03.json"),
    ("periodic_p09", "periodic_p09.json"),
    ("poisson_p09", "p09.json"),
]
CONDITIONS = {
    "keepalive": [],
    "restore": ["--restore"],
    "prewarm": ["--prewarm"],
    "combined": ["--prewarm", "--restore"],
    "psp": ["--psp"],
}


def wait_for_port(port, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def run_one(name, trace_file, n, k, cond,extra=()):
    trace = os.path.join(TRACES, trace_file)
    T = json.load(open(trace, encoding="utf-8"))["metadata"]["t"]
    log = os.path.join(OUT, f"{name}_{cond}.json")
    events = os.path.join(OUT, f"{name}_{cond}_events.json")
    ctrl = subprocess.Popen(
        [sys.executable, os.path.join(BASE, "controller.py"), "--port", str(PORT),
         "-T", str(T), "-k", str(k), "--log", events, *CONDITIONS[cond],*extra],
        cwd=BASE)
    try:
        if not wait_for_port(PORT):
            raise RuntimeError("controller did not start")
        subprocess.run(
            [sys.executable, os.path.join(BASE, "replayer.py"), "--trace", trace,
             "--k", str(k), "--n", str(n), "--url", f"http://127.0.0.1:{PORT}",
             "--log", log],
            check=True, cwd=BASE)
    finally:
        ctrl.send_signal(signal.SIGINT)
        try:
            ctrl.wait(timeout=60)
        except subprocess.TimeoutExpired:
            ctrl.kill()
    errs = sum(1 for r in json.load(open(log, encoding="utf-8"))["requests"] if r["error"])
    if errs:
        raise SystemExit(f"{name}/{cond}: {errs} request errors, stopping the batch")
    print(f"=== {name} / {cond} done: {log} ===")
    if cond == "keepalive":            # check.py only knows the keep-alive classes
        out = subprocess.run(
            [sys.executable, os.path.join(BASE, "check.py"), trace, log, events],
            capture_output=True, text=True, cwd=BASE)
        with open(os.path.join(OUT, f"{name}_check.txt"), "w", encoding="utf-8") as f:
            f.write(out.stdout)
        print(out.stdout)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("names", nargs="*", help="trace names to run (default: all six)")
    ap.add_argument("--cond", choices=list(CONDITIONS), default="keepalive")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--psp-hi", type=float)
    ap.add_argument("--psp-lo", type=float)
    a = ap.parse_args()
    extra=[]
    if a.cond == "psp":
        if a.psp_hi is None or a.psp_lo is None:
            ap.error("--cond psp needs --psp-hi and --psp-lo")
        extra = ["--psp-hi", str(a.psp_hi), "--psp-lo", str(a.psp_lo)]
    os.makedirs(OUT, exist_ok=True)
    if a.cond in ("restore", "combined","psp"):
        make_snapshot()                # once per batch; keep port 8080 free

    if a.smoke:
        run_one("smoke", RUNS[0][1], 20, 10.0, a.cond,extra)
    else:
        runs = [r for r in RUNS if not a.names or r[0] in a.names]
        total = 0.0
        for name, fname in runs:
            tr = json.load(open(os.path.join(TRACES, fname), encoding="utf-8"))["trace"]
            total += tr[-1] / K
        print(f"estimated total: {total / 60:.0f} min")
        for name, fname in runs:
            run_one(name, fname, 100000, K, a.cond,extra)
            time.sleep(2)