from flask import Flask, request
import random, time
from prometheus_client import start_http_server, Counter
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

app = Flask(__name__)

# 1. SIMPLE METRIC: Sirf requests count karne ke liye
REQUESTS = Counter('http_requests_total', 'Total Requests', ['status'])

# 2. SIMPLE TRACING: Jaeger ko data bhejney ke liye setup
provider = TracerProvider()
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces"))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


@app.route('/pay')
def pay():
    # Aik span banayein tracing ke liye
    with tracer.start_as_current_span("payment_logic"):
        # Failure simulate karein (Anomaly detection ke liye)
        status = "200" if random.random() > 0.2 else "500"

        # Metric record karein
        REQUESTS.labels(status=status).inc()

        return f"Payment Status: {status}", int(status)


if __name__ == '__main__':
    start_http_server(8000)  # Prometheus metrics yahan se uthayega
    app.run(port=5000)  # Aapki App yahan chalegi