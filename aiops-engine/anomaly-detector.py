import requests
import time
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.linear_model import LinearRegression
import json
import os
import logging
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIGURATIONS
# ─────────────────────────────────────────────────────────────
SERVICE_NAME             = os.getenv("MONITOR_SERVICE", "payment-api")
PROM_URL                 = "http://127.0.0.1:9090/api/v1/query"
JAEGER_URL               = "http://127.0.0.1:16686"
GRAFANA_ANNOTATION_URL   = "https://127.0.0.1:3000/api/annotations"
DATA_FILE                = "data_points.json"

GRAFANA_TOKEN            = os.getenv("GRAFANA_API_KEY")
GRAFANA_ANNOTATIONS_ENABLED = True

MIN_POINTS       = 60
SLO_THRESHOLD    = 80.0
SLO_COOLDOWN_SEC = 60
MAX_HISTORY      = 1500
TRAIN_WINDOW     = 500
RETRAIN_EVERY    = 60
REQUEST_TIMEOUT  = 5
CONTAMINATION    = 0.3
RANDOM_STATE     = 42

# ─────────────────────────────────────────────────────────────
# SESSIONS
# ─────────────────────────────────────────────────────────────
prom_session = requests.Session()

grafana_session = requests.Session()
grafana_session.headers.update({
        "Authorization": f"Bearer {GRAFANA_TOKEN}",
    "X-Grafana-Org-Id": "1",
    "Content-Type": "application/json",
})
grafana_session.verify = False

# ─────────────────────────────────────────────────────────────
# ALERT CORRELATION STATE
# ─────────────────────────────────────────────────────────────
active_incident = {
    "is_open":     False,
    "start_time":  None,
    "alert_count": 0
}

# ─────────────────────────────────────────────────────────────
# PERSISTENCE
# ─────────────────────────────────────────────────────────────
def load_data() -> list:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                raw = json.load(f)
            # Filter out old 1D data (error_rate & latency both 0)
            valid = [p for p in raw if not (p[1] == 0.0 and p[2] == 0.0)]
            if valid:
                log.info("Loaded %d valid 3D points (%d old 1D filtered)",
                         len(valid), len(raw) - len(valid))
                return valid
        except Exception:
            pass
    return []


def save_data(data_points: list) -> list:
    import math

    clean = [
        p for p in data_points
        if all(isinstance(v, (int, float)) and math.isfinite(v) for v in p)
    ]
    trimmed = clean[-MAX_HISTORY:]
    with open(DATA_FILE, "w") as f:
        json.dump(trimmed, f)
    return trimmed

# ─────────────────────────────────────────────────────────────
# METRIC FETCHERS
# ─────────────────────────────────────────────────────────────
def _prom_query(query: str) -> list:
    resp = prom_session.get(PROM_URL, params={"query": query}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()["data"]["result"]


def get_request_rate() -> float | None:
    try:
        results = _prom_query("sum(rate(http_requests_total[1m]))")
        return float(results[0]["value"][1]) if results else 0.0
    except Exception as e:
        log.warning("Failed fetching request rate: %s", e)
        return None


def fetch_slo_metric() -> float:
    query = (
        "(sum(rate(http_requests_total{http_status='200'}[5m])) "
        "/ sum(rate(http_requests_total[5m]))) * 100"
    )
    try:
        result = _prom_query(query)
        return float(result[0]["value"][1]) if result else 100.0
    except Exception:
        return 100.0


def get_error_rate() -> float | None:
    try:
        result = _prom_query(
            "sum(rate(http_requests_total{http_status=~'5..'}[1m]))"
        )
        return float(result[0]["value"][1]) if result else 0.0
    except Exception:
        return None


def get_p99_latency() -> float | None:
    try:
        result = _prom_query(
            "histogram_quantile(0.99, "
            "sum(rate(http_request_duration_seconds_bucket[1m])) by (le))"
        )
        return float(result[0]["value"][1]) if result else 0.0
    except Exception:
        return None


def get_cpu_utilization() -> float:
    try:
        result = _prom_query("node:cpu_utilization:percent")
        return float(result[0]["value"][1]) if result else 0.0
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────
# MOST IMPORTANT PART: ROOT CAUSE ANALYSIS
# ─────────────────────────────────────────────────────────────
def get_latest_trace_id(service: str) -> str | None:
    url    = f"{JAEGER_URL}/api/traces"
    params = {"service": service, "limit": 1, "lookback": "2m"}
    try:
        r    = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        data = r.json().get("data", [])
        if data:
            return data[0]["traceID"]
    except Exception:
        return None


def get_root_cause(trace_id: str, service: str) -> str:
    url = f"{JAEGER_URL}/api/traces/{trace_id}"
    try:
        response  = requests.get(url, params={"service": service}, timeout=REQUEST_TIMEOUT)
        body      = response.json()
        spans     = body["data"][0].get("spans", [])
        processes = body["data"][0].get("processes", {})

        if not spans:
            return "Trace empty — no spans found"

        slowest  = max(spans, key=lambda s: s.get("duration", 0))
        proc_id  = slowest.get("processID")
        svc_name = processes.get(proc_id, {}).get("serviceName", "unknown")
        op       = slowest.get("operationName", "unknown")
        dur_ms   = slowest.get("duration", 0) / 1000


        cpu_load = get_cpu_utilization()
        if cpu_load > 85.0:
            return (
                f"Resource Exhaustion — Host CPU @{cpu_load:.1f}% "
                f"throttling '{op}' in {svc_name}"
            )

        return (
            f"Code-level Bottleneck in '{svc_name}' "
            f"-> operation '{op}' took {dur_ms:.1f}ms"
        )
    except Exception as e:
        return f"RCA correlation engine error: {e}"


# ─────────────────────────────────────────────────────────────
# GRAFANA ANNOTATION
# ─────────────────────────────────────────────────────────────
def post_to_grafana(text: str, tags: list = None) -> None:
    if not GRAFANA_ANNOTATIONS_ENABLED:
        return
    if tags is None:
        tags = ["aiops-incident"]
    payload = {
        "text": text,
        "tags": tags,
        "time": int(time.time() * 1000),
    }
    try:
        r = grafana_session.post(
            GRAFANA_ANNOTATION_URL, json=payload, timeout=REQUEST_TIMEOUT
        )
        if r.status_code == 200:
            log.info("Annotation synced with Grafana visualization plane")
        else:
            log.debug("Grafana annotation status %s", r.status_code)
    except Exception as e:
        log.debug("Grafana channel offline: %s", e)


# ─────────────────────────────────────────────────────────────
# PERFORMANCE PREDICTION (Linear Trend Forecasting)
# ─────────────────────────────────────────────────────────────
def predict_performance_trends(history: list) -> float:
    """Forecast P99 latency 5 minutes (60 steps) ahead."""
    if len(history) < 20:
        return 0.0

    df = pd.DataFrame(history, columns=["rate", "errors", "p99"])
    y  = df["p99"].values
    X  = np.arange(len(y)).reshape(-1, 1)

    predictor = LinearRegression()
    predictor.fit(X, y)

    future_step   = len(y) + 60
    predicted_p99 = predictor.predict([[future_step]])[0]
    return float(max(0.0, predicted_p99))


# ─────────────────────────────────────────────────────────────
# INITIALIZATION
# ─────────────────────────────────────────────────────────────
model         = IsolationForest(contamination=CONTAMINATION, random_state=RANDOM_STATE)
data_points   = load_data()
loop_counter  = 0
model_trained = False
last_slo_alert_time = 0.0

log.info("AIOps Engine active — monitoring '%s' | %d historical points loaded",
         SERVICE_NAME, len(data_points))

# ─────────────────────────────────────────────────────────────
# ENTERPRISE MONITORING LOOP
# ─────────────────────────────────────────────────────────────
while True:
    now          = time.time()
    loop_counter += 1

    req_rate = get_request_rate()
    err_rate = get_error_rate()
    p99      = get_p99_latency()
    slo_val  = fetch_slo_metric()

    #SLO Check
    if slo_val < SLO_THRESHOLD:
        if now - last_slo_alert_time >= SLO_COOLDOWN_SEC:
            log.warning("SLO VIOLATION — availability: %.2f%% (threshold: %.0f%%)",
                        slo_val, SLO_THRESHOLD)
            last_slo_alert_time = now

    #Anomaly Detection
    if all(v is not None for v in [req_rate, err_rate, p99]):

        data_points.append([req_rate, err_rate, p99])
        data_points = save_data(data_points)

        if len(data_points) >= MIN_POINTS:
            X_train = np.array(data_points[-TRAIN_WINDOW:])
            X_train = X_train[~np.isinf(X_train).any(axis=1)]

            if len(X_train) < MIN_POINTS:
                log.warning("Not enough clean data after NaN filter: %d", len(X_train))
            else:
                if not model_trained or loop_counter % RETRAIN_EVERY == 0:
                    model.fit(X_train)
                    model_trained = True
                    log.info("ML Engine retrained on %d clean vectors", len(X_train))

            if not model_trained or loop_counter % RETRAIN_EVERY == 0:
                model.fit(X_train)
                model_trained = True
                log.info("ML Engine retrained on %d vectors (loop #%d)",
                         len(X_train), loop_counter)

            prediction     = model.predict([[req_rate, err_rate, p99]])
            forecasted_p99 = predict_performance_trends(data_points)

            #ANOMALY DETECTED
            if prediction[0] == -1:

                #RCA
                latest_id = get_latest_trace_id(SERVICE_NAME)
                cause = (
                    get_root_cause(latest_id, SERVICE_NAME)
                    if latest_id
                    else "Infrastructure mutation — no Jaeger trace found"
                )

                #Alert Correlation & Noise Reduction
                if not active_incident["is_open"]:
                    active_incident.update({
                        "is_open":     True,
                        "start_time":  now,
                        "alert_count": 1,
                    })
                    log.warning("[INCIDENT_OPENED] Anomaly signature detected")
                    log.warning("RCA Result -> %s", cause)

                    alert_msg = (
                        f"<h3>INCIDENT STARTED: {SERVICE_NAME}</h3>"
                        f"<b>RCA:</b> {cause}<br>"
                        f"<b>Metrics:</b> Rate={req_rate:.2f}/s | "
                        f"Errors={err_rate:.4f}/s | P99={p99:.3f}s"
                    )
                    post_to_grafana(alert_msg, tags=["incident-start", SERVICE_NAME])

                else:
                    #Noise reduction > deduplicate, do not flood annotations
                    active_incident["alert_count"] += 1
                    log.info(
                        "NOISE REDUCTION: Suppressed redundant alert "
                        "(total in incident: %d)",
                        active_incident["alert_count"]
                    )

                #Predictive Warning
                if forecasted_p99 > 2.5:
                    log.critical(
                        "PREDICTION: P99 heading to %.2fs in 5 minutes — "
                        "consider scaling now",
                        forecasted_p99
                    )

            #NORMAL STATE
            else:
                if active_incident["is_open"]:
                    duration = int(now - active_incident["start_time"])
                    log.info("[INCIDENT_RESOLVED] System recovered after %ds | "
                             "%d alerts correlated",
                             duration, active_incident["alert_count"])

                    resolve_msg = (
                        f"<h3>INCIDENT RESOLVED</h3>"
                        f"{SERVICE_NAME} recovered after {duration}s | "
                        f"{active_incident['alert_count']} alerts correlated"
                    )
                    post_to_grafana(resolve_msg, tags=["incident-resolve", SERVICE_NAME])

                    active_incident.update({
                        "is_open":     False,
                        "start_time":  None,
                        "alert_count": 0,
                    })

                log.info(
                    "Steady State | Rate=%.2f/s | Errors=%.4f/s | "
                    "P99=%.3fs | Forecast(5m)=%.3fs | SLO=%.2f%%",
                    req_rate, err_rate, p99, forecasted_p99, slo_val
                )

        else:
            log.info("Collecting baseline — %d more points needed",
                     MIN_POINTS - len(data_points))

    else:
        log.warning("Incomplete metric vector — req=%s err=%s p99=%s",
                    req_rate, err_rate, p99)

    time.sleep(5)