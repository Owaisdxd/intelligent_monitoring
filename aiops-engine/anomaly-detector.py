import requests
import time
import numpy as np
from sklearn.ensemble import IsolationForest
import json
import os
import logging

# ─────────────────────────────────────────────
# STRUCTURED LOGGING SETUP
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)
SERVICE_NAME = os.getenv("MONITOR_SERVICE", "payment-api")
PROM_URL     = "http://127.0.0.1:9090/api/v1/query"
JAEGER_URL   = "http://127.0.0.1:16686"
DATA_FILE          = "data_points.json"
MIN_POINTS         = 10      
SLO_COOLDOWN_SEC   = 60
ANOMALY_COOLDOWN_SEC = 30


# ─────────────────────────────────────────────
# CONFIGURATIONS  (all tuneable values in one place)
# ─────────────────────────────────────────────
SERVICE_NAME         = os.getenv("MONITOR_SERVICE", "payment-api")
PROM_URL             = "http://127.0.0.1:9090/api/v1/query"
JAEGER_URL           = "http://127.0.0.1:16686"
GRAFANA_ANNOTATION_URL = "http://127.0.0.1:3000/api/annotations"
DATA_FILE            = "data_points.json"

# BUG FIX 1 ─ token must be a plain string in f-string, NOT a set literal {token}
# Old (broken): "Authorization": {token}   ← this creates a Python set, not a string
# Fixed:        "Authorization": f"Bearer {token}"
GRAFANA_TOKEN = os.getenv("GRAFANA_TOKEN", "")
PROM_TOKEN    = os.getenv("PROM_TOKEN", "")        # set if your Prometheus also needs auth

# BUG FIX 2 ─ keyword argument is `headers`, not `header` (no trailing s = TypeError → None)
# All requests.get() calls were using header=headers which is silently ignored by requests,
# so every call went unauthenticated and likely returned a 401/403 → exception → None.
# Fixed by using a shared session with headers baked in.
prom_session = requests.Session()
prom_session.headers.update({
    "Authorization": f"Bearer {PROM_TOKEN}",
    "Accept": "application/json",
})

grafana_session = requests.Session()
grafana_session.headers.update({
    "Authorization": f"Bearer {GRAFANA_TOKEN}",
    "Content-Type": "application/json",
})

# Tuneable model / alert constants
MIN_POINTS           = 60       # data points needed before anomaly detection starts
SLO_THRESHOLD        = 80.0     # SLO availability threshold (%)
SLO_COOLDOWN_SEC     = 60       # seconds between repeated SLO alerts
ANOMALY_COOLDOWN_SEC = 30       # seconds between repeated anomaly alerts
MAX_HISTORY          = 1500     # max data points kept on disk AND in memory
TRAIN_WINDOW         = 500      # how many recent points to train on
RETRAIN_EVERY        = 60       # retrain model every N loop iterations (~5 min at 5s interval)
REQUEST_TIMEOUT      = 5        # seconds for all HTTP calls
CONTAMINATION        = 0.1      # IsolationForest contamination parameter
RANDOM_STATE         = 42


GRAFANA_TOKEN = os.getenv("GRAFANA_API_KEY")

GRAFANA_ANNOTATION_URL = "http://127.0.0.1:3000/api/annotations"

headers = {
    "Authorization":{"GRAFANA_API_KEY"},
    "Content-Type": "application/json"
}


# ─────────────────────────────────────────────
# PERSISTENCE: Load / Save
# ─────────────────────────────────────────────
def load_data() -> list:
    """Load historical data points from disk (survives restarts)."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []


def save_data(data_points: list) -> None:
    """Persist last MAX_HISTORY data points to disk and trim in memory."""
    trimmed = data_points[-MAX_HISTORY:]
    with open(DATA_FILE, "w") as f:
        json.dump(trimmed, f)
    return trimmed   # caller should reassign: data_points = save_data(data_points)


# ─────────────────────────────────────────────
# METRIC FETCHERS  (all use session, all have timeout, specific exceptions)
# ─────────────────────────────────────────────
def _prom_query(query: str) -> list:
    """
    Shared helper — runs a PromQL query and returns the result list.
    Raises on network or parse errors so callers can handle specifically.
    """
    resp = prom_session.get(PROM_URL, params={"query": query}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["result"]


def get_request_rate() -> float | None:
    """Fetch HTTP request rate (requests/sec) from Prometheus."""
    try:
        results = _prom_query("rate(http_requests_total[1m])")
        return float(results[0]["value"][1]) if results else None
    except requests.Timeout:
        log.warning("Prometheus timeout fetching request rate")
    except requests.ConnectionError:
        log.warning("Prometheus connection error fetching request rate")
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Unexpected Prometheus response (request rate): %s", e)
    return None


def fetch_slo_metric() -> float:
    """Fetch SLO availability % — ratio of 200 responses to total requests."""
    query = (
        "(sum(rate(http_requests_total{http_status='200'}[5m])) "
        "/ sum(rate(http_requests_total[5m]))) * 100"
    )
    try:
        result = _prom_query(query)
        return float(result[0]["value"][1]) if result else 100.0
    except requests.Timeout:
        log.warning("Prometheus timeout fetching SLO metric")
    except requests.ConnectionError:
        log.warning("Prometheus connection error fetching SLO metric")
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Unexpected Prometheus response (SLO): %s", e)
    return 100.0    # default to 100% (no false SLO alert) on failure


def get_error_rate() -> float | None:
    """Fetch 5xx error rate from Prometheus."""
    try:
        result = _prom_query("rate(http_requests_total{status=~'5..'}[1m])")
        return float(result[0]["value"][1]) if result else 0.0
    except requests.Timeout:
        log.warning("Prometheus timeout fetching error rate")
    except requests.ConnectionError:
        log.warning("Prometheus connection error fetching error rate")
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Unexpected Prometheus response (error rate): %s", e)
    return None


def get_p99_latency() -> float | None:
    """Fetch 99th percentile latency from Prometheus."""
    try:
        result = _prom_query(
            "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[1m]))"
        )
        return float(result[0]["value"][1]) if result else 0.0
    except requests.Timeout:
        log.warning("Prometheus timeout fetching p99 latency")
    except requests.ConnectionError:
        log.warning("Prometheus connection error fetching p99 latency")
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Unexpected Prometheus response (p99): %s", e)
    return None


# ─────────────────────────────────────────────
# ROOT CAUSE ANALYSIS
# ─────────────────────────────────────────────
def get_latest_trace_id(service: str = SERVICE_NAME) -> str | None:
    """Fetch the most recent trace ID for the service from Jaeger."""
    url = f"{JAEGER_URL}/api/traces"
    params = {"service": service, "limit": 1, "lookback": "2m"}
    try:
        # BUG FIX 3 ─ timeout was assigned AFTER the request call (had no effect)
        # Old: r = requests.get(...); timeout=5   ← timeout was a dangling assignment
        # Fixed: timeout is now passed into the call correctly via the session
        r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        data = r.json().get("data", [])
        if data:
            return data[0]["traceID"]
    except requests.Timeout:
        log.warning("Jaeger timeout fetching latest trace ID")
    except requests.ConnectionError:
        log.warning("Jaeger connection error fetching trace ID")
    except (KeyError, IndexError, ValueError) as e:
        log.warning("Unexpected Jaeger response (trace ID): %s", e)
    return None


def get_root_cause(trace_id: str, service: str = SERVICE_NAME) -> str:
    """Identify the slowest span in a trace as the likely root cause."""
    url = f"{JAEGER_URL}/api/traces/{trace_id}"
    try:
        response = requests.get(url, params={"service": service}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        body        = response.json()
        trace_data  = body["data"][0]
        spans       = trace_data.get("spans", [])
        processes   = trace_data.get("processes", {})

        if not spans:
            return "Trace has no spans."

        slowest_span   = max(spans, key=lambda s: s.get("duration", 0))
        proc_id        = slowest_span.get("processID")
        actual_svc     = processes.get(proc_id, {}).get("serviceName", "unknown-service")
        op             = slowest_span.get("operationName", "unknown-op")
        dur_ms         = slowest_span.get("duration", 0) / 1000

        return f"Bottleneck in {actual_svc} → operation '{op}' took {dur_ms:.1f}ms"

    except requests.Timeout:
        return "RCA failed: Jaeger request timed out"
    except requests.ConnectionError:
        return "RCA failed: could not connect to Jaeger"
    except KeyError as e:
        return f"RCA failed: missing key in trace data ({e})"
    except ValueError as e:
        return f"RCA failed: bad value in trace data ({e})"


# ─────────────────────────────────────────────
# GRAFANA ANNOTATION
# ─────────────────────────────────────────────
def post_to_grafana(text: str, tags: list = None) -> None:
    """Post an annotation (vertical marker) to the Grafana dashboard."""
    if tags is None:
        tags = ["ai-anomaly"]
    payload = {
        "text": text,
        "tags": tags,
        "time": int(time.time() * 1000),   # Grafana expects milliseconds
    }
    try:
        r = grafana_session.post(
            GRAFANA_ANNOTATION_URL, json=payload, timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            log.info("Annotation posted to Grafana dashboard")
        else:
            log.warning("Grafana annotation returned status %s: %s", r.status_code, r.text)
    except Exception as e:
        log.warning("Failed to post Grafana annotation: %s", e)


# ─────────────────────────────────────────────
# ML MODEL INITIALIZATION
# ─────────────────────────────────────────────
model = IsolationForest(
    contamination=CONTAMINATION,
    random_state=RANDOM_STATE
)

data_points = load_data()
log.info("Loaded %d historical data points", len(data_points))
log.info("AI Active: monitoring '%s' | SLO & Anomaly Detection running...", SERVICE_NAME)

last_slo_alert_time     = 0.0
last_anomaly_alert_time = 0.0
loop_counter            = 0       # tracks when to retrain the model
model_trained           = False   # True once we have enough points for a first fit


# ─────────────────────────────────────────────
# MAIN MONITORING LOOP
# ─────────────────────────────────────────────
while True:
    now          = time.time()
    loop_counter += 1

    # ── Fetch all metrics ────────────────────
    req_rate = get_request_rate()
    err_rate = get_error_rate()
    p99      = get_p99_latency()
    slo_val  = fetch_slo_metric()

    # ── Step A: SLO Violation Check ──────────
    if slo_val < SLO_THRESHOLD:
        if now - last_slo_alert_time >= SLO_COOLDOWN_SEC:
            log.warning(
                "SLO VIOLATION — availability: %.2f%% (threshold: %.0f%%) | blocking deployments",
                slo_val, SLO_THRESHOLD
            )
            last_slo_alert_time = now
        else:
            remaining = int(SLO_COOLDOWN_SEC - (now - last_slo_alert_time))
            log.info("SLO still degraded: %.2f%% (next alert in %ds)", slo_val, remaining)

    # ── Step B: Anomaly Detection ────────────
    if all(v is not None for v in [req_rate, err_rate, p99]):

        data_points.append([req_rate, err_rate, p99])
        data_points = save_data(data_points)   # trim in memory AND on disk

        if len(data_points) >= MIN_POINTS:
            X = np.array(data_points[-TRAIN_WINDOW:])

            # Retrain only on first fit or every RETRAIN_EVERY iterations
            # (not every single loop cycle — that was wasteful and noisy)
            if not model_trained or loop_counter % RETRAIN_EVERY == 0:
                model.fit(X)
                model_trained = True
                log.info("Model retrained on %d points (loop #%d)", len(X), loop_counter)

            prediction = model.predict([[req_rate, err_rate, p99]])

            if prediction[0] == -1:
                if now - last_anomaly_alert_time >= ANOMALY_COOLDOWN_SEC:
                    log.warning(
                        "ANOMALY DETECTED — Rate=%.2f | Errors=%.2f | P99=%.3fs",
                        req_rate, err_rate, p99
                    )

                    # ── Step C: Root Cause Analysis ──────────
                    latest_id = get_latest_trace_id(SERVICE_NAME)
                    if latest_id:
                        cause = get_root_cause(latest_id, service=SERVICE_NAME)
                        log.warning("Root cause: %s", cause)
                    else:
                        cause = "No recent traces found in Jaeger"
                        log.warning("Root cause: %s", cause)

                    # ── Step D: Deployment Risk + Grafana alert ───
                    log.warning("High deployment risk — halt rollout immediately")
                    alert_msg = (
                        f"<b>AI Alert:</b> Anomaly detected on {SERVICE_NAME}<br>"
                        f"<b>RCA:</b> {cause}<br>"
                        f"<b>Metrics:</b> rate={req_rate:.2f} err={err_rate:.2f} p99={p99:.3f}s"
                    )
                    post_to_grafana(alert_msg, tags=["anomaly", SERVICE_NAME])
                    last_anomaly_alert_time = now

                else:
                    remaining = int(ANOMALY_COOLDOWN_SEC - (now - last_anomaly_alert_time))
                    log.info(
                        "Anomaly ongoing (next alert in %ds) | Rate=%.2f",
                        remaining, req_rate
                    )
            else:
                log.info(
                    "Normal | Rate=%.2f | Errors=%.2f | P99=%.3fs | SLO=%.2f%%",
                    req_rate, err_rate, p99, slo_val
                )
        else:
            needed = MIN_POINTS - len(data_points)
            log.info("Collecting baseline data — %d more points needed before detection starts", needed)

    else:
        log.warning(
            "Waiting for metrics — req=%s err=%s p99=%s",
            req_rate, err_rate, p99
        )

    time.sleep(5)
