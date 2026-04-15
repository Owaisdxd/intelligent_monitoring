from flask import Flask
from prometheus_client import start_http_server, Counter
import time, random
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry import trace
# 1. Prometheus Metric: SLO tracking ke liye
REQUEST_COUNT = Counter('http_requests_total', 'Total HTTP Requests', ['method', 'endpoint', 'http_status'])

# 1. Resource definition (Service Name fix)
resource = Resource(attributes={"service.name":"payment-api"})
provider = TracerProvider(resource=resource)
# Sending to Jaeger via Port-Forward (localhost:4318)
exporter = OTLPSpanExporter(endpoint="http://localhost:4318/v1/traces")
processor = BatchSpanProcessor(exporter)
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


DEPLOY_COUNT = Counter('deployment_events_total', 'Total Deployments', ['status'])
app = Flask(__name__)

@app.route('/checkout', methods=['POST'])
def checkout():
    # Context Manager use karein taake span auto-close ho
    with tracer.start_as_current_span("process_payment") as span:
        status = "200"
        if random.random() < 0.01:
            status = "500"
            span.set_attribute("error", True) # Jaeger mein error highlight karne ke liye

        REQUEST_COUNT.labels(method='POST', endpoint='/checkout', http_status=status).inc()

        if status == "500":
            return "Error", 500
        return "Success", 200


if __name__ == '__main__':

    start_http_server(8000)  # Prometheus metrics server on port 8000
    app.run(port=5000)