import csv
import socket
import subprocess
import time
import numpy as np
import requests

IMAGE_NAME = "serverless-sim:latest"
NAME_PREFIX = "serverless-sim-run"   
WARMUP_RUNS = 2                     
MEASURED_RUNS = 30                  
WARM_SAMPLES = 5                     
READY_DEADLINE_S = 30.0             
POLL_TIMEOUT_S = 0.5                 
REQUEST_TIMEOUT_S = 5.0              
OUT_CSV = "benchmark_results.csv"

FIELDS = [
    "run_id", "is_warmup", "phase", "req_idx",
    "latency_ms",        
    "cold_flag",        
    "flag_ok", 
    "t_created_ms",      
    "app_ready_ms", 
    "first_request_ms", 
    "init_duration_ms", 
    "memory_rss_mb", 
]


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def check_image():
    r = subprocess.run(["docker", "image", "inspect", IMAGE_NAME], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"Image {IMAGE_NAME} not found. Build or pull it first, "
                         "so the benchmark never times a download.")


def cleanup_leftovers():
    r = subprocess.run(["docker", "ps", "-aq", "--filter", f"name={NAME_PREFIX}"],
                       capture_output=True, text=True)
    ids = r.stdout.split()
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True)


def timed_get(endpoint: str, timeout: float):
    t_start = time.perf_counter()
    res = requests.get(endpoint, timeout=timeout)
    t_end = time.perf_counter()
    return res, (t_end - t_start) * 1000.0


def run_single_benchmark(run_id: int, is_warmup: bool) -> list:
    name = f"{NAME_PREFIX}{run_id}"
    port = get_free_port()
    endpoint = f"http://127.0.0.1:{port}/"

    try:
        t0 = time.perf_counter()
        started = subprocess.run(
            ["docker", "run", "-d", "--rm", "--name", name,
             "-p", f"{port}:8080", IMAGE_NAME],
            capture_output=True, text=True,
        )
        t_created = time.perf_counter()
        if started.returncode != 0:
            raise RuntimeError(f"docker run failed: {started.stderr.strip()}")
        deadline = t0 + READY_DEADLINE_S
        while True:
            if time.perf_counter() > deadline:
                raise TimeoutError(f"run {run_id}: no 200 OK within {READY_DEADLINE_S}s")
            try:
                res, first_request_ms = timed_get(endpoint, POLL_TIMEOUT_S)
                if res.status_code == 200:
                    t_ready = time.perf_counter()
                    break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                pass
            time.sleep(0.002)

        cold_body = res.json()
        cold_flag = cold_body["cold"] 
        telemetry = cold_body["metrics"]

        warm = []
        for i in range(WARM_SAMPLES):
            res, ms = timed_get(endpoint, REQUEST_TIMEOUT_S)
            res.raise_for_status()
            warm.append((ms, res.json()["cold"]))
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)

    flag_ok = (cold_flag is True) and all(f is False for _, f in warm)

    rows = [{
        "run_id": run_id, "is_warmup": is_warmup, "phase": "cold", "req_idx": 0,
        "latency_ms": (t_ready - t0) * 1000.0,
        "cold_flag": cold_flag, "flag_ok": flag_ok,
        "t_created_ms": (t_created - t0) * 1000.0,
        "app_ready_ms": (t_ready - t_created) * 1000.0,
        "first_request_ms": first_request_ms,
        "init_duration_ms": telemetry["init_duration_ms"],
        "memory_rss_mb": telemetry["memory_rss_mb"],
    }]
    for i, (ms, flag) in enumerate(warm, start=1):
        rows.append({
            "run_id": run_id, "is_warmup": is_warmup, "phase": "warm", "req_idx": i,
            "latency_ms": ms, "cold_flag": flag, "flag_ok": flag_ok,
        })
    return rows


def summarize(rows: list):
    for phase in ("cold", "warm"):
        vals = [r["latency_ms"] for r in rows if r["phase"] == phase and not r["is_warmup"]]
        if not vals:
            continue
        print(f"{phase:>4}: n={len(vals):3d}  median={np.median(vals):8.2f} ms  "
              f"p95={np.percentile(vals, 95):8.2f} ms  "
              f"min={min(vals):8.2f}  max={max(vals):8.2f}")
    bad = sum(1 for r in rows if r["phase"] == "cold" and not r["flag_ok"])
    print(f"flag check failures: {bad} run(s)")


if __name__ == "__main__":
    check_image()
    cleanup_leftovers()
    total = WARMUP_RUNS + MEASURED_RUNS
    print(f"[+] {total} runs: first {WARMUP_RUNS} are warm-up (saved, not counted).")

    all_rows = []

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS, restval="")
        writer.writeheader()
        for run_id in range(1, total + 1):
            is_warmup = run_id <= WARMUP_RUNS
            rows = run_single_benchmark(run_id, is_warmup)
            writer.writerows(rows)
            f.flush() 
            all_rows.extend(rows)
            cold = rows[0]
            print(f"Run {run_id:02d}/{total:02d}{' (warm-up)' if is_warmup else ''} | "
                  f"cold {cold['latency_ms']:.1f} ms | "
                  f"flag {'OK' if cold['flag_ok'] else 'FAILED'}")

    print()
    summarize(all_rows)
    print(f"[+] Raw rows saved to {OUT_CSV}")