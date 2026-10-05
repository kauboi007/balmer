import os
import resource
import time

# Record exact process start timestamp
PROCESS_START_TIME = time.time()

# Initializaiton phase
t_init_start = time.perf_counter()

import numpy as np
import pandas as pd

# Allocate and precompute heavy memory state to test CRIU RAM snapshot integrity
PRECOMPUTED_DATA = np.ones((1000, 1000)) * 42.0
PRECOMPUTED_CHECKSUM = float(np.sum(PRECOMPUTED_DATA))

t_init_end = time.perf_counter()
INIT_DURATION_MS = (t_init_end - t_init_start) * 1000.0

from flask import Flask, jsonify

app = Flask(__name__)

IS_COLD = True

@app.route("/", methods=["GET"])
def invoke():
    global IS_COLD
    now = time.time()
    
    memory_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

    was_cold = IS_COLD
    IS_COLD = False  

    return jsonify({
        "status": "ok",
        "cold": was_cold,
        "pid": os.getpid(),
        "metrics": {
            "init_duration_ms": round(INIT_DURATION_MS, 2),
            "process_uptime_ms": round((now - PROCESS_START_TIME) * 1000.0, 2),
            "memory_rss_mb": round(memory_rss_mb, 2),
            "checksum": PRECOMPUTED_CHECKSUM
        }
    }), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)