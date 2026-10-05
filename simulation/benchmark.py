import socket
import subprocess
import time
import numpy as np
import requests

IMAGE_NAME = "serverless-sim:latest"
CONTAINER_NAME = "serverless-sim-runner"
NUM_RUNS = 12         # Total runs (N)
WARMUP_RUNS = 2       # Discard first 2 runs as system warm-up
WARM_SAMPLES = 5      # Number of warm requests per run

def get_free_port() -> int:
    """Requests an available ephemeral TCP port directly from the OS kernel."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

def cleanup_leftovers():
    """Removes any container left over from interrupted or failed runs."""
    subprocess.run(
        ["docker", "rm", "-f", CONTAINER_NAME],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

def run_single_benchmark(run_id: int) -> dict:
    port = get_free_port()
    endpoint = f"http://127.0.0.1:{port}/"

    # --- TIMED SECTION START ---
    t0 = time.perf_counter()

    # Launch container detached with auto-removal (--rm)
    proc = subprocess.Popen([
        "docker", "run", "--rm",
        "--name", CONTAINER_NAME,
        "-p", f"{port}:8080",
        IMAGE_NAME
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    t_created = time.perf_counter()

    # Poll endpoint until first 200 OK (Cold request)
    cold_response = None
    session = requests.Session()

    while True:
        try:
            res = session.get(endpoint, timeout=0.5)
            if res.status_code == 200:
                t_ready = time.perf_counter()
                cold_response = res.json()
                break
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            time.sleep(0.002)  # Low-overhead 2ms polling sleep

    # Record cold metric
    cold_latency_ms = (t_ready - t0) * 1000.0
    cold_flag = cold_response.get("cold", False)

    # Collect warm samples on same running container
    warm_latencies = []
    warm_flags = []

    for _ in range(WARM_SAMPLES):
        t_w_start = time.perf_counter()
        res = session.get(endpoint)
        t_w_end = time.perf_counter()

        warm_latencies.append((t_w_end - t_w_start) * 1000.0)
        warm_flags.append(res.json().get("cold", False))

    # Stop container and wait for process cleanup
    subprocess.run(["docker", "kill", CONTAINER_NAME], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    proc.wait()
    # --- TIMED SECTION END ---

    # Assert cold flag rule: Must be True on first request, False on all warm requests
    flag_check = (cold_flag is True) and all(f is False for f in warm_flags)

    return {
        "run_id": run_id,
        "t_created_ms": (t_created - t0) * 1000.0,
        "cold_latency_ms": cold_latency_ms,
        "cold_flag": cold_flag,
        "warm_latencies_ms": warm_latencies,
        "flag_check": flag_check,
        "telemetry": cold_response.get("metrics", {})
    }

if __name__ == "__main__":
    cleanup_leftovers()
    print(f"[+] Starting Benchmark: {NUM_RUNS} total runs ({WARMUP_RUNS} warm-up runs will be discarded)...")

    results = []
    for run_i in range(1, NUM_RUNS + 1):
        data = run_single_benchmark(run_i)
        results.append(data)

        # Print progress outside of the timed section
        status = "PASSED" if data["flag_check"] else "FAILED"
        print(f"Run {run_i:02d}/{NUM_RUNS:02d} | Cold Latency: {data['cold_latency_ms']:.2f} ms | Cold Flag Check: {status}")

    # Check rule assertion
    all_passed = all(r["flag_check"] for r in results)
    print(f"\n[+] Cold Flag Verification: {'ALL PASSED' if all_passed else 'FAILED'}")

    # Save raw results for Step 5 analysis
    np.save("raw_benchmark_results.npy", results)
    print("[+] Saved raw metrics to 'raw_benchmark_results.npy'. Ready for Step 5!")