import requests
import time
import numpy as np
from sklearn.ensemble import IsolationForest
import json
import os

# ─────────────────────────────────────────────
# CONFIGURATIONS
# ─────────────────────────────────────────────
SERVICE_NAME = os.getenv("MONITOR_SERVICE", "payment-api")
PROM_URL     = "http://127.0.0.1:9090/api/v1/query"
JAEGER_URL   = "http://127.0.0.1:16686"
DATA_FILE          = "data_points.json"
MIN_POINTS         = 10      # minimum data points before anomaly detection kicks in
SLO_COOLDOWN_SEC   = 60      # only re-alert on SLO violation every 60 seconds
ANOMALY_COOLDOWN_SEC = 30    # only re-alert on anomaly every 30 seconds


headers = {
    "Authorization": "glsa_1Ck47Oy9riYxbk947RC51WzSKdxstrcA_4abbe9b6",
    "Accept": "application/json"
}

# ─────────────────────────────────────────────
# PERSISTENCE: Load / Save
# ─────────────────────────────────────────────
def load_data():
    """Load historical data points from disk (survives restarts)."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r") as f:
            return json.load(f)
    return []


def save_data(data_points):
    """Save last 1500 data points to disk."""
    with open(DATA_FILE, "w") as f:
        json.dump(data_points[-1500:], f)


# ─────────────────────────────────────────────
# METRIC FETCHERS
# ─────────────────────────────────────────────
def get_request_rate():
    """Fetch HTTP request rate (requests/sec) from Prometheus."""
    query = "rate(http_requests_total[1m])"
    try:
        response = requests.get(PROM_URL, params={'query': query},headers=headers).json()
        results = response['data']['result']
        if results:
            return float(results[0]['value'][1])
    except Exception:
        return None
    return None


def fetch_slo_metric():
    """Fetch SLO availability % — ratio of 200 responses to total requests."""
    query = "(sum(rate(http_requests_total{http_status='200'}[5m])) / sum(rate(http_requests_total[5m]))) * 100"
    try:
        response = requests.get(PROM_URL, params={'query': query}).json()
        result = response['data']['result']
        return float(result[0]['value'][1]) if result else 100.0
    except Exception:
        return 100.0


def get_error_rate():
    """Fetch 5xx error rate from Prometheus."""
    query = "rate(http_requests_total{status=~'5..'}[1m])"
    try:
        r = requests.get(PROM_URL, params={'query': query}).json()
        result = r['data']['result']
        return float(result[0]['value'][1]) if result else 0.0
    except Exception:
        return None


def get_p99_latency():
    """Fetch 99th percentile latency from Prometheus."""
    query = "histogram_quantile(0.99, rate(http_request_duration_seconds_bucket[1m]))"
    try:
        r = requests.get(PROM_URL, params={'query': query}).json()
        result = r['data']['result']
        return float(result[0]['value'][1]) if result else 0.0
    except Exception:
        return None


# ─────────────────────────────────────────────
# ROOT CAUSE ANALYSIS
# ─────────────────────────────────────────────
def get_latest_trace_id(service=SERVICE_NAME):
    """Jaeger se pichle 2 minutes ki sab se latest trace ID nikalta hai."""
    url = f"{JAEGER_URL}/api/traces"
    params = {
        'service': service,
        'limit': 1,
        'lookback': '2m' # Pichle 2 minute ka data
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json().get("data", [])
        if data:
            return data[0]['traceID'] # Sab se pehli (latest) ID return karein
    except:
        pass
    return None

def get_root_cause(trace_id, service=SERVICE_NAME):
    """
    Fetch a specific trace from Jaeger by trace_id and identify
    the slowest span as the likely root cause.
    """
    url = f"{JAEGER_URL}/api/traces/{trace_id}"
    try:
        response = requests.get(url, params={"service": service}, timeout=5)
        response.raise_for_status()
        body = response.json()

        # ✅ Fix: safely handle None or missing 'data' key
        data = body.get("data")
        trace_data = data[0]
        spans = trace_data.get("spans", [])
        processes = trace_data.get("processes", {})  # Dynamic Service Names yahan hotay hain

        if not spans:
            return "Trace has no spans."

            # 1. Sab se slow span dhundain
        slowest_span = max(spans, key=lambda s: s.get("duration", 0))
        proc_id = slowest_span.get("processID")
        actual_svc_name = processes.get(proc_id, {}).get("serviceName", "unknown-service")

        op = slowest_span.get("operationName", "unknown-op")
        dur_ms = slowest_span.get("duration", 0) / 1000

        return f"Bottleneck in {actual_svc_name} → operation {op} took {dur_ms:.1f}ms"

    except Exception as e:
        return f"RCA Error: {str(e)}"



# ─────────────────────────────────────────────
# ML MODEL INITIALIZATION
# ─────────────────────────────────────────────
model = IsolationForest(contamination=0.1, random_state=42)

# ✅ Fixed: load persisted data ONCE before the loop (not mid-loop, not before functions)
data_points = load_data()
print(f" Loaded {len(data_points)} historical data points")
print(f" AI Active: Monitoring '{SERVICE_NAME}' | SLO & Anomaly Detection Running...")

# Cooldown trackers — track when we last alerted to avoid spam
last_slo_alert_time     = 0
last_anomaly_alert_time = 0


# ─────────────────────────────────────────────
# MAIN MONITORING LOOP
# ─────────────────────────────────────────────
while True:
    now = time.time()

    # ── Fetch all three metrics ──────────────
    req_rate = get_request_rate()
    err_rate = get_error_rate()
    p99      = get_p99_latency()
    slo_val  = fetch_slo_metric()

    # ── Step A: SLO Violation Check (with cooldown) ──────────
    if slo_val < 80:
        if now - last_slo_alert_time >= SLO_COOLDOWN_SEC:
            print(f"SLO Violation! Availability: {slo_val:.2f}%  (threshold: 80%)")
            print(f"Blocking deployments to protect Error Budget...")
            last_slo_alert_time = now
        else:
            # Still in cooldown — print a quieter reminder
            remaining = int(SLO_COOLDOWN_SEC - (now - last_slo_alert_time))
            print(f"⚠️  SLO still degraded: {slo_val:.2f}% (next alert in {remaining}s)")

    # ── Step B: Anomaly Detection ─────────────
    if all(v is not None for v in [req_rate, err_rate, p99]):

        data_points.append([req_rate, err_rate, p99])
        save_data(data_points)

        TRAIN_WINDOW = min(len(data_points), 100)

        if len(data_points) >= MIN_POINTS:
            X= np.array(data_points[-TRAIN_WINDOW:])
            model.fit(X)
            prediction = model.predict([[req_rate, err_rate, p99]])
            print("Model Output",prediction)

            if prediction[0] == -1:
                if now - last_anomaly_alert_time >= ANOMALY_COOLDOWN_SEC:
                    print(f"🚨   ANOMALY DETECTED! Rate={req_rate:.2f} | Errors={err_rate:.2f} | P99={p99:.3f}s")

                    # ── Step C: Automated RCA ────────────────
                    latest_id = get_latest_trace_id(SERVICE_NAME)

                    if latest_id:
                        cause = get_root_cause(latest_id, service=SERVICE_NAME)
                        print(f" Root Cause: {cause}")
                    else:
                        print(" Root Cause: No recent traces found in Jaeger to analyze.")

                    # ── Step D: Deployment Risk ──────────────
                    print("  High Deployment Risk! Halt rollout immediately.")
                    last_anomaly_alert_time = now
                else:
                    remaining = int(ANOMALY_COOLDOWN_SEC - (now - last_anomaly_alert_time))
                    print(f"🚨 Anomaly ongoing (next alert in {remaining}s) | Rate={req_rate:.2f}")
            else:
                print(f"✅ Normal | Rate={req_rate:.2f} | Errors={err_rate:.2f} | P99={p99:.3f}s | SLO={slo_val:.2f}%")

    else:
        print(f"⏳ Waiting for metrics... (req={req_rate}, err={err_rate}, p99={p99})")

    time.sleep(5)