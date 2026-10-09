import argparse
import json
import numpy as np
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def load_trace(path, n):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    metadata = data.get("metadata", {})
    trace = data.get("trace", [])[:n]
    return metadata, trace


def send_one(i, sr, url, timeout=30.0):
    send_abs = time.monotonic()
    recv_abs = None
    t_recv_server = None
    cold_flag = None
    controller_req_class = None
    error = None

    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            g = resp.read()
        recv_abs = time.monotonic()
        data = json.loads(g.decode("utf-8"))

        t_recv_server = data.get("t_recv")
        cold_flag = data.get("cold")
        controller_req_class = data.get("controller_req_class")
    except Exception as e:
        if recv_abs is None:
            recv_abs = time.monotonic()
        error = str(e)

    return i, sr, send_abs, recv_abs, t_recv_server, cold_flag, controller_req_class, error


def run_schedule(arrivals, k, server_url="http://127.0.0.1:8080", delay=0.0, max_workers=64, timeout=30.0):
    t0_wall = time.time()
    t0 = time.monotonic()
    futures = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        for i, x in enumerate(arrivals):
            sr = x / k
            wait = t0 + sr - time.monotonic()
            if wait > 0:
                time.sleep(wait)

            separator = "&" if "?" in server_url else "?"
            url = f"{server_url}{separator}delay={delay}"
            futures.append(pool.submit(send_one, i, sr, url, timeout))

    rows = [f.result() for f in futures]
    return rows, t0, t0_wall


def save_log(path, metadata, rows, t0):
    request_rows = []
    for i, sr, send_abs, recv_abs, t_recv_server, cold_flag, controller_req_class, error in rows:
        send_rel = send_abs - t0
        lag_ms = (send_rel - sr) * 1000.0
        latency_ms = (recv_abs - send_abs) * 1000.0 if recv_abs else None
        server_delta_ms = (t_recv_server - send_abs) * 1000.0 if t_recv_server else None

        request_rows.append({
            "index": i,
            "scheduled_rel_sec": sr,
            "send_rel_sec": send_rel,
            "lag_ms": lag_ms,
            "latency_ms": latency_ms,
            "server_delta_ms": server_delta_ms,
            "cold_flag": cold_flag,
            "controller_req_class": controller_req_class,
            "error": error,
        })

    log_data = {
        "metadata": metadata,
        "requests": request_rows,
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)
    print(f"\nExecution log written to: {path}")


def report(rows, t0):
    lags = []
    latencies = []
    error_count = 0

    for i, sr, send_abs, recv_abs, t_recv_server, cold_flag, controller_req_class, error in rows:
        send_rel = send_abs - t0
        lags.append((send_rel - sr) * 1000.0)

        if error is not None:
            error_count += 1
        elif recv_abs is not None:
            latencies.append((recv_abs - send_abs) * 1000.0)

    print(f"Total requests: {len(rows)}")
    print(f"Errors: {error_count}")

    if lags:
        print("\n--- Schedule Lag (ms) ---")
        print(f"mean: {np.mean(lags):.3f}")
        print(f"95th percentile: {np.percentile(lags, 95):.3f}")
        print(f"max lag: {np.max(lags):.3f}")

    if latencies:
        print("\n--- Request Latency (ms) ---")
        print(f"mean: {np.mean(latencies):.3f}")
        print(f"95th percentile: {np.percentile(latencies, 95):.3f}")
        print(f"max latency: {np.max(latencies):.3f}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=str, required=True, help="Path to trace JSON")
    parser.add_argument("--k", type=float, default=1.0, help="Speedup multiplier")
    parser.add_argument("--T", type=float, default=None, help="Idle timeout T (default: auto from trace)")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (default: auto from trace)")
    parser.add_argument("--n", type=int, default=50, help="Max requests to read")
    parser.add_argument("--url", type=str, default="http://127.0.0.1:8080", help="Target server URL")
    parser.add_argument("--delay", type=float, default=0.0, help="Server delay parameter")
    parser.add_argument("--workers", "-p", type=int, default=64, help="Max worker threads (p)")
    parser.add_argument("--timeout", type=float, default=30.0, help="Request timeout in seconds")
    parser.add_argument("--log", type=str, default=None, help="Output JSON log path")
    args = parser.parse_args()

    file_metadata, arrivals = load_trace(args.trace, args.n)

    # Resolve T and seed from file metadata if not overridden
    resolved_T = args.T if args.T is not None else file_metadata["t"]
    resolved_seed = args.seed if args.seed is not None else file_metadata["seed"]

    rows, t0, t0_wall = run_schedule(
        arrivals=arrivals,
        k=args.k,
        server_url=args.url,
        delay=args.delay,
        max_workers=args.workers,
        timeout=args.timeout,
    )

    report(rows, t0)

    if args.log:
        out_metadata = {
            "trace": args.trace,
            "seed": resolved_seed,
            "k": args.k,
            "T": resolved_T,
            "t_prime": resolved_T / args.k,
            "p": args.workers,
            "start_time_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t0_wall)),
            "start_time_epoch": t0_wall,
            "n": args.n,
            "url": args.url,
            "delay": args.delay,
        }
        save_log(args.log, out_metadata, rows, t0)


if __name__ == "__main__":
    main()