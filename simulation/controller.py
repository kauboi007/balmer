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

IMAGE_NAME = "serverless-sim:latest"
CONTAINER_PREFIX = "serverless-ctrl-"


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
    ):
        self.t_prime = t_prime
        self.image_name = image_name
        self.log_file = log_file
        self.use_reaper = use_reaper
        self.lock = threading.Lock()

        # Lifecycle state
        self.state = "NONE"  # NONE, BOOTING, READY
        self.last_arrival = 0.0
        self.endpoint = None
        self.boot_event = threading.Event()
        self.current_container_name = None
        self.run_counter = 0

        # Structured event log
        self.event_log = []

        # Run startup check & cleanup
        check_image(self.image_name)
        cleanup_leftovers(CONTAINER_PREFIX)

        # Register exit handler for synchronous teardown and log flush
        atexit.register(self.shutdown)

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

        with self.lock:
            active_container = self.current_container_name
            self.current_container_name = None

        if active_container:
            subprocess.run(["docker", "rm", "-f", active_container], capture_output=True)

        if self.log_file:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(self.event_log, f, indent=2)

    def _reaper_loop(self):
        """Background thread checking every 20 ms to reclaim expired containers eagerly."""
        while not self.stop_reaper.is_set():
            time.sleep(0.02)
            to_remove = None
            with self.lock:
                if self.state == "READY":
                    if (time.monotonic() - self.last_arrival) > self.t_prime:
                        to_remove = self.current_container_name
                        self.state = "NONE"
                        self.endpoint = None
                        self.current_container_name = None
                        self.log_event("reaper_expired", container_name=to_remove)

            if to_remove:
                subprocess.run(["docker", "rm", "-f", to_remove], capture_output=True)

    def start_container(self, container_name: str, port: int):
        """Container boot sequence with health check and error handling."""
        self.log_event("boot_start", container_name=container_name)
        ready_flag = False
        try:
            cmd = [
                "docker", "run", "-d", "--rm",
                "--name", container_name,
                "-p", f"{port}:8080",
                self.image_name,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                with self.lock:
                    self.state = "NONE"
                    self.log_event("boot_failed", container_name=container_name)
                return

            base_endpoint = f"http://127.0.0.1:{port}/"
            health_endpoint = f"http://127.0.0.1:{port}/health"
            deadline = time.monotonic() + 30.0

            # Poll /health every 2 ms to prevent consuming application / cold status flags
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
            # Guarantee boot event release under all execution branches
            self.boot_event.set()

    def handle_request(self) -> tuple[str, str]:
        """Classifies incoming requests under lock based on arrival delta and container state."""
        now = time.monotonic()

        with self.lock:
            # Expiry check ONLY applies when state == "READY"
            is_expired = (self.state == "READY") and ((now - self.last_arrival) > self.t_prime)

            if self.state == "NONE" or is_expired:
                request_class = "cold"
                old_container = self.current_container_name if is_expired else None

                if is_expired:
                    self.log_event("container_expired", container_name=old_container)

                self.run_counter += 1
                self.current_container_name = f"{CONTAINER_PREFIX}{self.run_counter}-{int(now)}"
                port = get_free_port()

                self.state = "BOOTING"
                self.endpoint = None  # Clear endpoint until boot completes successfully
                self.boot_event.clear()
                self.last_arrival = now
                self.log_event("request_arrival", req_class=request_class)

                # Asynchronously clean up old container if not already removed by reaper
                if old_container:
                    threading.Thread(
                        target=lambda c: subprocess.run(["docker", "rm", "-f", c], capture_output=True),
                        args=(old_container,),
                        daemon=True,
                    ).start()

                threading.Thread(
                    target=self.start_container,
                    args=(self.current_container_name, port),
                    daemon=True,
                ).start()

            elif self.state == "BOOTING":
                request_class = "cold_wait"
                self.last_arrival = now
                self.log_event("request_arrival", req_class=request_class)

            else:  # READY
                request_class = "warm"
                self.last_arrival = now
                self.log_event("request_arrival", req_class=request_class)

        if request_class in ("cold", "cold_wait"):
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


def run_controller(port: int, T: float, k: float, log_file: str, use_reaper: bool):
    t_prime = T / k
    cm = ContainerManager(t_prime=t_prime, log_file=log_file, use_reaper=use_reaper)
    cm.event_log.append({"event": "config", "T": T, "k": k, "t_prime": t_prime})

    class ThreadedHandler(ControllerRequestHandler):
        container_manager = cm

    server = ThreadingHTTPServer(("127.0.0.1", port), ThreadedHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Serverless Controller and Container Manager")
    parser.add_argument("--port", type=int, default=8080, help="Controller listening port")
    parser.add_argument("-T", "--idle-timeout", type=float, default=10.0, help="Idle timeout T (seconds)")
    parser.add_argument("-k", "--speedup", type=float, default=1.0, help="Speedup multiplier k")
    parser.add_argument("--log", type=str, default="controller_events.json", help="Controller event log JSON path")
    parser.add_argument("--no-reaper", action="store_true", help="Disable background proactive reaper thread")
    args = parser.parse_args()

    run_controller(args.port, args.idle_timeout, args.speedup, args.log, not args.no_reaper)