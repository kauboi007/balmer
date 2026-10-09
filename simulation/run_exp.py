import json
import os
import signal
import socket
import subprocess
import sys
import time

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

def wait_for_port(port, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        with socket.socket() as s:
            s.settimeout(0.2)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return False


def run_one(name, trace_file, n, k):
    trace = os.path.join(TRACES, trace_file)
    T = json.load(open(trace, encoding="utf-8"))["metadata"]["t"]
    log = os.path.join(OUT, f"{name}_keepalive.json")
    events = os.path.join(OUT, f"{name}_events.json")
    ctrl = subprocess.Popen(
        [sys.executable, os.path.join(BASE, "controller.py"), "--port", str(PORT),
         "-T", str(T), "-k", str(k), "--log", events], cwd=BASE)
    try:
        if not wait_for_port(PORT):
            raise RuntimeError("controller did not start")
        subprocess.run(
            [sys.executable, os.path.join(BASE, "replayer.py"), "--trace", trace,
             "--k", str(k), "--n", str(n), "--url", f"http://127.0.0.1:{PORT}",
             "--log", log], check=True, cwd=BASE)
    finally:
        ctrl.send_signal(signal.SIGINT)
        try:
            ctrl.wait(timeout=60)
        except subprocess.TimeoutExpired:
            ctrl.kill()
    out = subprocess.run(
        [sys.executable, os.path.join(BASE, "check.py"), trace, log, events],
        capture_output=True, text=True, cwd=BASE)
    with open(os.path.join(OUT, f"{name}_check.txt"), "w", encoding="utf-8") as f:
        f.write(out.stdout)
    print(f"=== {name} ===")
    print(out.stdout)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if "--smoke" in sys.argv:
        run_one("smoke", RUNS[0][1], 20, 10.0)
    else:
        wanted = [a for a in sys.argv[1:] if not a.startswith("--")]
        runs = [r for r in RUNS if not wanted or r[0] in wanted]
        total = 0.0
        for name, fname in runs:
            tr = json.load(open(os.path.join(TRACES, fname), encoding="utf-8"))["trace"]
            total += tr[-1] / K
        print(f"estimated total: {total / 60:.0f} min")
        for name, fname in runs:
            run_one(name, fname, 100000, K)
            time.sleep(2)