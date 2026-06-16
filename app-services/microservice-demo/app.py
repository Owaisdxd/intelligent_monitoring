from flask import Flask, jsonify, request, Response
from prometheus_client import (
    start_http_server, Counter, Histogram, Gauge,
    generate_latest, CONTENT_TYPE_LATEST
)
import time
import random
import logging

from opentelemetry import trace
from opentelemetry.trace import StatusCode
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# OPENTELEMETRY
# ─────────────────────────────────────────────
resource  = Resource(attributes={"service.name": "payment-api"})
provider  = TracerProvider(resource=resource)
exporter  = OTLPSpanExporter(endpoint="http://127.0.0.1:4318/v1/traces")
processor = BatchSpanProcessor(exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)

# ─────────────────────────────────────────────
# PROMETHEUS METRICS
# ─────────────────────────────────────────────
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'http_status']
)

#Histogram
REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'Request latency in seconds',
    ['method', 'endpoint'],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5]
)

ERROR_COUNT = Counter(
    'http_errors_total',
    'Total 5xx errors',
    ['method', 'endpoint']
)

DEPLOY_COUNT = Counter(
    'deployment_events_total',
    'Deployment events',
    ['status']
)

ACTIVE_REQUESTS = Gauge(
    'http_active_requests',
    'In-flight requests',
    ['endpoint']
)

# ─────────────────────────────────────────────
# FLASK
# ─────────────────────────────────────────────
app = Flask(__name__)


@app.route('/healthz')
def liveness():
    return jsonify({"status": "alive"}), 200


@app.route('/readyz')
def readiness():
    return jsonify({"status": "ready"}), 200


@app.route('/metrics')
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)


@app.route('/checkout', methods=['POST'])
def checkout():
    endpoint = '/checkout'
    ACTIVE_REQUESTS.labels(endpoint=endpoint).inc()
    start = time.time()

    with tracer.start_as_current_span("process_payment") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')
        span.set_attribute("http.method", "POST")
        span.set_attribute("http.route", endpoint)

        try:
            query_count = random.randint(1, 5)
            span.set_attribute("db.query.count", query_count)
            time.sleep(random.uniform(0.01, 0.08) * query_count)

            if random.random() < 0.02:
                raise ValueError("Payment gateway timeout")

            http_status = "200"
            span.set_attribute("http.status_code", 200)
            response = ("Success", 200)

        except Exception as e:
            http_status = "500"
            span.set_status(StatusCode.ERROR, str(e))
            span.record_exception(e)
            ERROR_COUNT.labels(method='POST', endpoint=endpoint).inc()
            response = ("Error", 500)

        finally:
            latency = time.time() - start
            REQUEST_LATENCY.labels(method='POST', endpoint=endpoint).observe(latency)
            REQUEST_COUNT.labels(method='POST', endpoint=endpoint, http_status=http_status).inc()
            ACTIVE_REQUESTS.labels(endpoint=endpoint).dec()
            log.info("POST /checkout | %s | %.3fs | %s", http_status, latency, trace_id[:8])

    return response


@app.route('/api/data')
def api_data():
    endpoint = '/api/data'
    ACTIVE_REQUESTS.labels(endpoint=endpoint).inc()
    start = time.time()

    with tracer.start_as_current_span("api.data") as span:
        trace_id = format(span.get_span_context().trace_id, '032x')
        span.set_attribute("http.method", "GET")
        span.set_attribute("http.route", endpoint)

        try:
            time.sleep(random.uniform(0.005, 0.2))
            # 1% chance of latency spike — anomaly injection
            if random.random() < 0.01:
                time.sleep(random.uniform(0.5, 1.5))
                span.set_attribute("slow_query", True)

            http_status = "200"
            span.set_attribute("http.status_code", 200)
            response = (jsonify({"data": "ok", "trace_id": trace_id}), 200)

        except Exception as e:
            http_status = "500"
            span.set_status(StatusCode.ERROR, str(e))
            ERROR_COUNT.labels(method='GET', endpoint=endpoint).inc()
            response = (jsonify({"error": str(e)}), 500)

        finally:
            latency = time.time() - start
            REQUEST_LATENCY.labels(method='GET', endpoint=endpoint).observe(latency)
            REQUEST_COUNT.labels(method='GET', endpoint=endpoint, http_status=http_status).inc()
            ACTIVE_REQUESTS.labels(endpoint=endpoint).dec()

    return response


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────
if __name__ == '__main__':
    start_http_server(8000)
    log.info("Metrics: :8000 | App :5000")
    app.run(host='0.0.0.0', port=5000, debug=False)