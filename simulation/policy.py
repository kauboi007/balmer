import threading
import time


class EwmaGapPredictor:
    """Smoothed estimate of the gap between arrivals; predicts the next arrival time.
    Also tracks how wrong its own forecasts have been (used by PSP)."""

    def __init__(self, alpha=0.3, beta=0.3):
        self.alpha = alpha
        self.beta = beta
        self.gap_hat = None
        self.err_hat = None          # smoothed absolute forecast error, seconds
        self.n_gaps = 0
        self.last = None
        self._lock = threading.Lock()

    def observe(self, t):
        with self._lock:
            if self.last is not None:
                gap = t - self.last
                if self.gap_hat is None:
                    self.gap_hat = gap
                else:
                    err = abs(gap - self.gap_hat)       # error of the forecast made before this gap
                    if self.err_hat is None:
                        self.err_hat = err
                    else:
                        self.err_hat = self.beta * err + (1 - self.beta) * self.err_hat
                    self.gap_hat = self.alpha * gap + (1 - self.alpha) * self.gap_hat
                self.n_gaps += 1
            self.last = t

    def predict_next(self):
        with self._lock:
            if self.gap_hat is None:
                return None, None
            return self.last + self.gap_hat, self.last

    def rel_error(self):
        with self._lock:
            if self.err_hat is None or self.gap_hat <= 0:
                return None, self.n_gaps
            return self.err_hat / self.gap_hat, self.n_gaps


def psp_tier(rel_err, n_gaps, hi, lo, min_gaps=5):
    if rel_err is None or n_gaps < min_gaps:
        return "low"

    t_high = min(hi, lo)
    t_med = max(hi, lo)

    if rel_err <= t_high:
        return "high"
    if rel_err <= t_med:
        return "medium"
    return "low"


class Prewarmer(threading.Thread):


    def __init__(self, pred, prewarm_fn, lead_s, margin_s=0.1, tick_s=0.01):
        super().__init__(daemon=True)
        self.pred = pred
        self.prewarm_fn = prewarm_fn
        self.lead = lead_s
        self.margin = margin_s
        self.tick = tick_s
        self.stop_evt = threading.Event()

    def run(self):
        acted_for = None
        while not self.stop_evt.wait(self.tick):
            t_pred, anchor = self.pred.predict_next()
            if t_pred is None or anchor == acted_for:
                continue
            if time.monotonic() >= t_pred - self.lead - self.margin:
                acted_for = anchor
                self.prewarm_fn(t_pred)