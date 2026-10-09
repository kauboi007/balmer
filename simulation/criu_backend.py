import subprocess
import sys
import time
import urllib.request

IMAGE = "serverless-sim:latest"
NAME = "serverless-snap"                    # must NOT start with "serverless-ctrl-"
CKPT = "snap1"
PORT = 8080                                 # host networking: the app binds 8080 itself
HEALTH = f"http://127.0.0.1:{PORT}/health"


def _docker(*args, check=True):
    return subprocess.run(["docker", *args], capture_output=True, text=True, check=check)


def wait_health(deadline_s=15.0, poll_s=0.002):
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        try:
            with urllib.request.urlopen(HEALTH, timeout=0.5) as r:
                if r.status == 200:
                    return time.monotonic()
        except Exception:
            pass
        time.sleep(poll_s)
    raise TimeoutError("function not ready")


def make_snapshot():
    """Run once before restore experiments. /health does not flip IS_COLD,
    so the snapshot is taken after init and before any real request."""
    _docker("rm", "-f", NAME, check=False)
    _docker("run", "-d", "--name", NAME, "--network", "host", IMAGE)
    wait_health()
    _docker("checkpoint", "create", NAME, CKPT)     # freezes AND kills the container
    print(f"[+] snapshot {CKPT} created for container {NAME}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "snapshot":
        make_snapshot()
    else:
        print("usage: python criu_backend.py snapshot")