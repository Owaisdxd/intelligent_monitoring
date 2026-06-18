curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=probe_success'   | python3 -c "
import json,sys
d=json.load(sys.stdin)
for r in d['data']['result']:
      print(f\"{r['metric']['instance']} > {r['value'][1]}\")
  "
curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=histogram_quantile(0.99,sum(rate(http_request_duration_seconds_bucket[1m]))by(le))'   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['result'])"

curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=sum(rate(http_requests_total{http_status=~"5.."}[1m]))'   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['result'])"

curl -s -G http://localhost:9090/api/v1/query   --data-urlencode 'query=sum(rate(http_requests_total[1m]))'   | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['data']['result'])"

{ curl -s http://localhost:9090/-/healthy; curl -s http://localhost:5000/healthz; curl -s http://localhost:8000/metrics | grep "http_requests_total" | head -3; }

kubectl exec -it pod/node-exporter-52q8n -n monitoring -- curl http://localhost:9100/metrics | head -n 10

kubectl logs deployment/fluent-bit -n monitoring --tail=20

kubectl logs ds/fluent-bit -n monitoring --tail=20

kubectl exec -it deployment/prometheus -n monitoring -- wget -qO- "http://localhost:9090/api/v1/query?query=node_cpu_utilization_percent"

kubectl exec -it deployment/loki -n monitoring -- wget -qO- "http://localhost:3100/ready"

kubectl exec -it deployment/loki -n monitoring -- curl "http://localhost:3100/ready"

kubectl run triage-chaos-test --image=jess/stress --restart=Never -n monitoring -- --cpu 3 --timeout 60s

kubectl delete pod/triage-chaos-test -n monitoring

curl -k -X GET -u "admin:admin123" "https://localhost:3000/api/annotations"

