import time

# Process clock starts here: the first line that runs once the Python
# interpreter itself has booted. Interpreter boot time is NOT included.
#app.py
PROCESS_START_TIME = time.time()
_T_INIT_START = time.perf_counter()

import os
import threading

import numpy as np
import pandas as pd  # unused on purpose: adds realistic import cost to the cold start. Your call to keep or remove.
from flask import Flask, jsonify

# Heavy in-memory state, so a CRIU snapshot later has real RAM to preserve.
PRECOMPUTED_DATA = np.ones((1000, 1000)) * 42.0
PRECOMPUTED_CHECKSUM = float(np.sum(PRECOMPUTED_DATA))

app = Flask(__name__)

# INIT_DURATION_MS = first line of this file -> Flask app object built.
# It covers numpy, pandas and flask imports plus the precompute above.
INIT_DURATION_MS = (time.perf_counter() - _T_INIT_START) * 1000.0

_cold_lock = threading.Lock()
IS_COLD = True


def current_rss_mb() -> float:
    #Current (not peak) resident memory of this process, from /proc
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) / 1024.0  # value is in kB
    raise RuntimeError("VmRSS not found in /proc/self/status")

@app.route("/health")
def health():
    return "ok", 200

@app.route("/", methods=["GET"])
def invoke():
    global IS_COLD
    now = time.time()

    # Read-and-flip must be atomic, or two simultaneous first requests
    # could both see IS_COLD == True.
    with _cold_lock:
        was_cold = IS_COLD
        IS_COLD = False

    return jsonify({
        "status": "ok",
        "cold": was_cold,
        "pid": os.getpid(),
        "metrics": {
            "init_duration_ms": round(INIT_DURATION_MS, 2),
            "process_uptime_ms": round((now - PROCESS_START_TIME) * 1000.0, 2),
            "memory_rss_mb": round(current_rss_mb(), 2),
            "checksum": PRECOMPUTED_CHECKSUM,
        },
    }), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)