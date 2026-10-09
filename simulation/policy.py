import threading
import time


class EwmaGapPredictor:
    """Smoothed estimate of the gap between arrivals; predicts the next arrival time."""

    def __init__(self, alpha=0.3):
        self.alpha = alpha
        self.gap_hat = None
        self.last = None
        self._lock = threading.Lock()

    def observe(self, t):
        with self._lock:
            if self.last is not None:
                gap = t - self.last
                if self.gap_hat is None:
                    self.gap_hat = gap
                else:
                    self.gap_hat = self.alpha * gap + (1 - self.alpha) * self.gap_hat
            self.last = t

    def predict_next(self):
        """Returns (predicted arrival time, anchor) or (None, None)."""
        with self._lock:
            if self.gap_hat is None:
                return None, None
            return self.last + self.gap_hat, self.last


class Prewarmer(threading.Thread):
    """Fires prewarm_fn(t_pred) once per arrival, when 'now' reaches
    predicted arrival - start-up time (lead) - safety margin."""

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