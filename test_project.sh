# ═══ COMPLETE VERIFICATION SCRIPT ═══
echo "=========================================="
echo "PLATFORM HEALTH CHECK"
echo "=========================================="

# ── 1. Prometheus ──
echo ""
echo "1. PROMETHEUS"
curl -s http://localhost:9090/-/healthy
curl -s -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=up' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d['data']['result']:
    status = 'UP' if r['value'][1]=='1' else 'DOWN'
    print(f\"  {r['metric'].get('job','unknown'):20} >{status}\")
"
curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=probe_success'   | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d['data']['result']:
      print(f\"{r['metric']['instance']} > {r['value'][1]}\")
  "
echo "Step 2"
curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_bucket[1m]))by(le))'   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['result'])"

echo "Step 3"
curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=sum(rate(http_requests_total{http_status=~"5.."}[1m]))'   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['result'])"

echo "Step 4"
curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=sum(rate(http_requests_total[1m]))'   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['result'])"

# ── 2. Alertmanager ──
echo ""
echo "2. ALERTMANAGER"
curl -s http://localhost:9093/-/healthy

# ── 3. Grafana ──
echo ""
echo "3. GRAFANA"
curl -sk https://localhost:3000/api/health | python3 -c "
import json,sys
d=json.load(sys.stdin)
print('  Status:', d.get('database','unknown'))
"

# ── 4. Jaeger ──
echo ""
echo "4. JAEGER"
curl -s http://localhost:16686/api/services | python3 -c "
import json,sys
d=json.load(sys.stdin)
services = d.get('data',[])
print(f'  Services found: {len(services)}')
for s in services:
    print(f'  > {s}')
"

# ── 5. Loki ──
echo ""
echo "5. LOKI"
kubectl run test-loki --image=curlimages/curl --rm -it \
  --restart=Never -n monitoring \
  -- curl -s http://loki-service:3100/ready 2>/dev/null

# ── 6. Fluent Bit ──
echo ""
echo "6. FLUENT BIT"
kubectl logs -l app=fluent-bit -n monitoring --tail=3 | grep -i "loki\|flush\|info"

# ── 7. Node Exporter ──
echo ""
echo "7. NODE EXPORTER"
curl -s -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=node_cpu_seconds_total' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
count = len(d['data']['result'])
print(f'  CPU metrics: {count} time series ' if count>0 else '  No data')
"

# ── 8. Blackbox Exporter ──
echo ""
echo "8. BLACKBOX EXPORTER"
curl -s -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=probe_success' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d['data']['result']:
    status = 'UP' if r['value'][1]=='1' else ' DOWN'
    print(f\"  {r['metric']['instance']:40} → {status}\")
"

# ── 9. OTel Collector ──
echo ""
echo "9. OTEL COLLECTOR"
curl -s -G http://localhost:9090/api/v1/query \
  --data-urlencode 'query=up{job="otel-collector"}' \
  | python3 -c "
import json,sys
d=json.load(sys.stdin)
count = len(d['data']['result'])
print(f'  OTel replicas up: {count}')
" 2>/dev/null || echo "  Check Jaeger for traces"

# ── 10. Jaeger traces ──
echo ""
echo "10. TRACES IN JAEGER"
curl -s "http://localhost:16686/api/traces?service=payment-api&limit=3" | python3 -c "
import json,sys
d=json.load(sys.stdin)
traces = d.get('data',[])
print(f'  Recent traces: {len(traces)}')
for t in traces[:3]:
    spans = len(t.get('spans',[]))
    print(f'  > TraceID: {t[\"traceID\"][:16]}... | Spans: {spans}')
" 2>/dev/null || echo "  Port forward check karo"


echo "Verifying Grafana Data"
curl -k -X GET -u "admin:admin123" "https://localhost:3000/api/annotations"

echo "Creating test pod to increase the flow of traffic "
kubectl run triage-chaos-test --image=jess/stress --restart=Never -n monitoring -- --cpu 3 --timeout 60s
sleep 30

echo "Deleting test pog"
kubectl delete pod/triage-chaos-test -n monitoring
sleep 2



echo ""
echo "=========================================="
echo "VERIFICATION COMPLETE"
echo "=========================================="
