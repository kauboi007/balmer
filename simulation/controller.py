import argparse
import atexit
import json
import socket
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from policy import EwmaGapPredictor, Prewarmer, psp_tier

from criu_backend import NAME as SNAP_NAME, CKPT as SNAP_CKPT
from policy import EwmaGapPredictor, Prewarmer

IMAGE_NAME = "serverless-sim:latest"
CONTAINER_PREFIX = "serverless-ctrl-"

SNAP_PORT = 8080
LEAD_BOOT = 0.72      # s, about p95 of measured cold boot
LEAD_RESTORE = 0.56   # s, about p95 of measured restore


def check_image(image_name: str = IMAGE_NAME):
    """Ensures the docker image is present prior to handling traffic."""
    r = subprocess.run(["docker", "image", "inspect", image_name], capture_output=True)
    if r.returncode != 0:
        raise SystemExit(f"Image {image_name} not found. Build or pull it first.")


def cleanup_leftovers(prefix: str = CONTAINER_PREFIX):
    """Synchronously removes leftover containers from prior interrupted runs."""
    r = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name={prefix}"],
        capture_output=True,
        text=True,
    )
    ids = r.stdout.split()
    if ids:
        subprocess.run(["docker", "rm", "-f", *ids], capture_output=True)


def get_free_port() -> int:
    """Finds an available ephemeral TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ContainerManager:
    def __init__(
        self,
        t_prime: float,
        image_name: str = IMAGE_NAME,
        log_file: str = "controller_events.json",
        use_reaper: bool = True,
        use_restore: bool = False,
        use_prewarm: bool = False,
        alpha: float = 0.3,
        grace: float = 0.5,
        margin: float = 0.1,
        use_psp: bool = False,
        psp_hi: float = None,
        psp_lo: float = None,
    ):  
        if use_psp:
            if psp_hi is None or psp_lo is None:
                raise SystemExit("--psp needs --psp-hi and --psp-lo (run calibrate_psp.py first)")
            use_restore = use_prewarm = True      # PSP always restores and always has a predictor
        self.use_psp = use_psp
        self.psp_hi = psp_hi
        self.psp_lo = psp_lo
        self.t_prime = t_prime
        self.image_name = image_name
        self.log_file = log_file
        self.use_reaper = use_reaper
        self.use_restore = use_restore
        self.grace = grace
        self.lock = threading.Lock()

        # Lifecycle state
        self.state = "NONE"  # NONE, BOOTING, READY
        self.last_arrival = 0.0
        self.hold_until = 0.0            # prewarm: do not expire before this time
        self.endpoint = None
        self.boot_event = threading.Event()
        self.current_container_name = None
        self.container_origin = None     # "request" or "prewarm"
        self.container_served = False    # has a request used this container yet?
        self.run_counter = 0

        # Restore mode: single snapshot container, serialised kill/restore
        self.docker_lock = threading.Lock()
        self.snap_alive = False
        self.restore_count = 0

        # Structured event log
        self.event_log = []

        check_image(self.image_name)
        cleanup_leftovers(CONTAINER_PREFIX)
        if use_restore:
            r = subprocess.run(["docker", "checkpoint", "ls", SNAP_NAME],
                               capture_output=True, text=True)
            if SNAP_CKPT not in r.stdout:
                raise SystemExit("No snapshot found: run `python criu_backend.py snapshot` first.")
            subprocess.run(["docker", "kill", SNAP_NAME], capture_output=True)

        atexit.register(self.shutdown)

        # Prewarm policy
        self.predictor = None
        if use_prewarm:
            self.predictor = EwmaGapPredictor(alpha)
            lead = LEAD_RESTORE if use_restore else LEAD_BOOT
            self.prewarmer = Prewarmer(self.predictor, self.prewarm, lead, margin)
            self.prewarmer.start()

        # Optional proactive background reaper thread
        if self.use_reaper:
            self.stop_reaper = threading.Event()
            self.reaper_thread = threading.Thread(target=self._reaper_loop, daemon=True)
            self.reaper_thread.start()

    def log_event(self, event_type: str, container_name: str = None, req_class: str = None):
        """Appends structured lifecycle events to memory."""
        c_name = container_name if container_name is not None else self.current_container_name
        self.event_log.append({
            "timestamp": time.time(),
            "monotonic": time.monotonic(),
            "container_name": c_name,
            "event": event_type,
            "class": req_class,
        })

    def shutdown(self):
        """Synchronously cleans up container state and flushes logs at exit."""
        if hasattr(self, "stop_reaper"):
            self.stop_reaper.set()
        if hasattr(self, "prewarmer"):
            self.prewarmer.stop_evt.set()

        with self.lock:
            active_container = self.current_container_name
            self.current_container_name = None

        if self.use_restore:
            subprocess.run(["docker", "kill", SNAP_NAME], capture_output=True)
        elif active_container:
            subprocess.run(["docker", "rm", "-f", active_container], capture_output=True)

        if self.log_file:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(self.event_log, f, indent=2)

    # ---------- helpers (the first three expect self.lock to be held) ----------

    def _expired(self, now):
        return self.state == "READY" and now > max(self.last_arrival + self.t_prime,
                                                   self.hold_until)

    def _note_expiry(self, name, how):
        self.log_event(how, container_name=name)
        if self.container_origin == "prewarm" and not self.container_served:
            self.log_event("prewarm_wasted", container_name=name)

    def _launch(self, origin):
        self.run_counter += 1
        if self.use_restore:
            name, port = SNAP_NAME, SNAP_PORT
        else:
            name = f"{CONTAINER_PREFIX}{self.run_counter}-{int(time.monotonic())}"
            port = get_free_port()
        self.current_container_name = name
        self.state = "BOOTING"
        self.endpoint = None
        self.boot_event.clear()
        self.hold_until = 0.0
        self.container_origin = origin
        self.container_served = (origin == "request")
        threading.Thread(target=self.start_container, args=(name, port), daemon=True).start()
    
    def _kill_snap(self, restores_at_expiry):
        """Reaper path in restore mode. Skips if a newer restore has already started."""
        with self.docker_lock:
            if self.restore_count != restores_at_expiry:
                return
            if self.snap_alive:
                subprocess.run(["docker", "kill", SNAP_NAME], capture_output=True)
                self.snap_alive = False

    def prewarm(self, t_pred):
        """Called by the Prewarmer thread shortly before the predicted arrival."""
        tier = "high"
        if self.use_psp:
            rel, n = self.predictor.rel_error()
            tier = psp_tier(rel, n, self.psp_hi, self.psp_lo)
        with self.lock:
            if self.use_psp:
                self.log_event("psp_tier", req_class=tier)
                if tier == "low":
                    return                       # not confident: spend nothing
            if self.state == "BOOTING":
                return
            hold = t_pred + self.grace
            if self.state == "READY":            # still up: keep it alive until the arrival
                if hold > self.hold_until:
                    self.hold_until = hold
                    self.log_event("prewarm_hold")
                return
            if tier != "high":                   # medium never starts a container speculatively
                return
            self._launch("prewarm")
            self.hold_until = hold
            self.log_event("prewarm_start")

    def _reaper_loop(self):
        """Background thread checking every 20 ms to reclaim expired containers eagerly."""
        while not self.stop_reaper.is_set():
            time.sleep(0.02)
            to_remove, n = None, None
            with self.lock:
                if self._expired(time.monotonic()):
                    to_remove = self.current_container_name
                    n = self.restore_count
                    self.state = "NONE"
                    self.endpoint = None
                    self.current_container_name = None
                    self._note_expiry(to_remove, "reaper_expired")

            if to_remove:
                if self.use_restore:
                    self._kill_snap(n)
                else:
                    subprocess.run(["docker", "rm", "-f", to_remove], capture_output=True)

    def start_container(self, container_name: str, port: int):
        """Boot (docker run) or restore (docker start --checkpoint), then poll /health."""
        self.log_event("restore_start" if self.use_restore else "boot_start",
                       container_name=container_name)
        ready_flag = False
        try:
            if self.use_restore:
                port = SNAP_PORT
                with self.docker_lock:
                    if self.snap_alive:                  # stale container still running
                        subprocess.run(["docker", "kill", SNAP_NAME], capture_output=True)
                        self.snap_alive = False
                    self.restore_count += 1
                    res = subprocess.run(
                        ["docker", "start", "--checkpoint", SNAP_CKPT, SNAP_NAME],
                        capture_output=True, text=True,
                    )
                    if res.returncode == 0:
                        self.snap_alive = True
            else:
                res = subprocess.run(
                    ["docker", "run", "-d", "--rm",
                     "--name", container_name,
                     "-p", f"{port}:8080",
                     self.image_name],
                    capture_output=True, text=True,
                )
            if res.returncode != 0:
                with self.lock:
                    self.state = "NONE"
                    self.log_event("boot_failed", container_name=container_name)
                return

            base_endpoint = f"http://127.0.0.1:{port}/"
            health_endpoint = f"http://127.0.0.1:{port}/health"
            deadline = time.monotonic() + 30.0

            # Poll /health every 2 ms so the app's own cold flag is not consumed
            while time.monotonic() < deadline:
                try:
                    req = urllib.request.Request(health_endpoint, method="GET")
                    with urllib.request.urlopen(req, timeout=0.5) as resp:
                        if resp.status == 200:
                            ready_flag = True
                            break
                except Exception:
                    pass
                time.sleep(0.002)

            with self.lock:
                if ready_flag:
                    self.endpoint = base_endpoint
                    self.state = "READY"
                    self.log_event("boot_ready", container_name=container_name)
                else:
                    self.state = "NONE"
                    self.endpoint = None
                    self.log_event("boot_timeout", container_name=container_name)
        except Exception:
            with self.lock:
                self.state = "NONE"
                self.endpoint = None
                self.log_event("boot_exception", container_name=container_name)
        finally:
            self.boot_event.set()

    def handle_request(self) -> tuple[str, str]:
        """Classifies an incoming request under lock from arrival time and container state."""
        now = time.monotonic()
        if self.predictor:
            self.predictor.observe(now)

        with self.lock:
            is_expired = self._expired(now)

            if self.state == "NONE" or is_expired:
                request_class = "cold_restore" if self.use_restore else "cold"
                old_container = self.current_container_name if is_expired else None
                if is_expired:
                    self._note_expiry(old_container, "container_expired")
                self.last_arrival = now
                self._launch("request")
                self.log_event("request_arrival", req_class=request_class)

                if old_container and not self.use_restore:
                    threading.Thread(
                        target=lambda c: subprocess.run(["docker", "rm", "-f", c],
                                                        capture_output=True),
                        args=(old_container,),
                        daemon=True,
                    ).start()

            elif self.state == "BOOTING":
                if self.container_origin == "prewarm" and not self.container_served:
                    request_class = "late_prewarm"       # arrived while the prewarm was booting
                    self.container_served = True
                else:
                    request_class = "cold_wait"
                self.last_arrival = now
                self.log_event("request_arrival", req_class=request_class)

            else:  # READY
                if self.container_origin == "prewarm" and not self.container_served:
                    request_class = "prewarm_hit"
                    self.container_served = True
                else:
                    request_class = "warm"
                self.last_arrival = now
                self.log_event("request_arrival", req_class=request_class)

        if request_class not in ("warm", "prewarm_hit"):
            self.boot_event.wait()

        with self.lock:
            target_endpoint = self.endpoint

        return request_class, target_endpoint


class ControllerRequestHandler(BaseHTTPRequestHandler):
    container_manager: ContainerManager = None

    def do_GET(self):
        req_type, target_endpoint = self.container_manager.handle_request()

        if not target_endpoint:
            self.send_error(500, "Container failed to boot or reach ready state")
            return

        parsed_path = urllib.parse.urlparse(self.path)
        forward_url = f"{target_endpoint.rstrip('/')}{parsed_path.path}"
        if parsed_path.query:
            forward_url += f"?{parsed_path.query}"

        try:
            req = urllib.request.Request(forward_url, method="GET")
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                body = resp.read()
                data = json.loads(body.decode("utf-8"))

                # Annotate response payload with controller classification
                data["controller_req_class"] = req_type

                resp_bytes = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp_bytes)))
                self.end_headers()
                self.wfile.write(resp_bytes)
        except Exception as e:
            self.send_error(502, f"Bad Gateway forwarding to container: {e}")

    def log_message(self, format, *args):
        # Silenced to prevent disk/console IO latency bias
        pass


def run_controller(port, T, k, log_file, use_reaper,
                   restore=False, prewarm=False, alpha=0.3, grace=0.5, margin=0.1,
                   psp=False, psp_hi=None, psp_lo=None):
    t_prime = T / k
    cm = ContainerManager(t_prime=t_prime, log_file=log_file, use_reaper=use_reaper,
                          use_restore=restore, use_prewarm=prewarm,
                          alpha=alpha, grace=grace, margin=margin,
                          use_psp=psp, psp_hi=psp_hi, psp_lo=psp_lo)
    cm.event_log.append({"event": "config", "T": T, "k": k, "t_prime": t_prime,
                         "restore": restore, "prewarm": prewarm, "psp": psp,
                         "psp_hi": psp_hi, "psp_lo": psp_lo,
                         "alpha": alpha, "grace": grace, "margin": margin})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serverless Controller and Container Manager")
    parser.add_argument("--port", type=int, default=9000, help="Controller listening port")
    parser.add_argument("-T", "--idle-timeout", type=float, default=10.0, help="Idle timeout T (seconds)")
    parser.add_argument("-k", "--speedup", type=float, default=1.0, help="Speedup multiplier k")
    parser.add_argument("--log", type=str, default="controller_events.json", help="Controller event log JSON path")
    parser.add_argument("--no-reaper", action="store_true", help="Disable background proactive reaper thread")
    parser.add_argument("--restore", action="store_true", help="Cold requests restore from the CRIU snapshot")
    parser.add_argument("--prewarm", action="store_true", help="EWMA predictive pre-warming")
    parser.add_argument("--alpha", type=float, default=0.3, help="EWMA smoothing factor")
    parser.add_argument("--grace", type=float, default=0.5, help="Hold a prewarmed container this long past the predicted arrival (s)")
    parser.add_argument("--margin", type=float, default=0.1, help="Safety margin added to start-up lead time (s)")
    parser.add_argument("--psp", action="store_true", help="Confidence-gated policy (implies restore and prewarm)")
    parser.add_argument("--psp-hi", type=float, default=None, help="rel. error at or below this = high confidence")
    parser.add_argument("--psp-lo", type=float, default=None, help="rel. error at or below this = medium confidence")
    args = parser.parse_args()

    run_controller(args.port, args.idle_timeout, args.speedup, args.log, not args.no_reaper,
                   args.restore, args.prewarm, args.alpha, args.grace, args.margin,
                   args.psp, args.psp_hi, args.psp_lo)