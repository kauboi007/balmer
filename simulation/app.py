import time


PROCESS_START_TIME = time.time()
_T_INIT_START = time.perf_counter()

import os
import threading

import numpy as np
import pandas as pd  
from flask import Flask, jsonify

PRECOMPUTED_DATA = np.ones((1000, 1000)) * 42.0
PRECOMPUTED_CHECKSUM = float(np.sum(PRECOMPUTED_DATA))

app = Flask(__name__)


INIT_DURATION_MS = (time.perf_counter() - _T_INIT_START) * 1000.0

_cold_lock = threading.Lock()
IS_COLD = True


def current_rss_mb() -> float:
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"): #virtual memeory resident set size
                return int(line.split()[1]) / 1024.0  #kB
    raise RuntimeError("VmRSS not found in /proc/self/status")

@app.route("/health")
def health():
    return "ok", 200

@app.route("/", methods=["GET"])
def invoke():
    global IS_COLD
    now = time.time()

  
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