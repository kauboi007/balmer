import socket
import statistics
import subprocess
import time
import urllib.request

from criu_backend import NAME, CKPT, make_snapshot, wait_health

IMAGE = "serverless-sim:latest"


def sh(*a):
    return subprocess.run(["docker", *a], capture_output=True, text=True)


def boot_once():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    name = "serverless-bootcheck"
    t0 = time.monotonic()
    sh("run", "-d", "--rm", "--name", name, "-p", f"{port}:8080", IMAGE)
    while True:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.5)
            break
        except Exception:
            time.sleep(0.002)
    t = (time.monotonic() - t0) * 1000
    sh("rm", "-f", name)
    return t


def restore_once():
    sh("kill", NAME)
    time.sleep(0.5)
    t0 = time.monotonic()
    sh("start", "--checkpoint", CKPT, NAME)
    t1 = wait_health()
    return (t1 - t0) * 1000


def show(label, v):
    print(f"{label}: median={statistics.median(v):.0f} ms  min={min(v):.0f}  max={max(v):.0f}  n={len(v)}")


if __name__ == "__main__":
    boots = [boot_once() for _ in range(8)]
    show("cold boot ", boots)
    make_snapshot()
    restores = [restore_once() for _ in range(10)]
    sh("kill", NAME)
    show("restore   ", restores)