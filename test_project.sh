echo "Step 1"
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

echo "Step 5"
echo "Checking Entry Points"
curl -s http://localhost:9090/-/healthy
curl -s http://localhost:5000/healthz
curl -s http://localhost:8000/metrics | grep "http_requests_total" | head -3

echo "Step 6"
echo "Creating test pod to increase the flow of traffic "
kubectl run triage-chaos-test --image=jess/stress --restart=Never -n monitoring -- --cpu 3 --timeout 60s
sleep 30

echo "Step 7"
echo "Deleting test pog"
kubectl delete pod/triage-chaos-test -n monitoring
sleep 2

echo "Step 8"
echo "Verifying Grafana Data"
curl -k -X GET -u "admin:admin123" "https://localhost:3000/api/annotations"
