#!/bin/bash
echo "======================================="
echo " LAUNCHING INEL OBSERVABILITY PLATFORM "
echo "======================================="

#1. Namespace Check & Creation
echo "[INFO] Verifying Monitoring Namespace Layer..."
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

#2. Automated SSL/TLS Engine Fix (The Gatekeeper)
echo "[INFO] Securing Communication: Injecting TLS Credentials..."
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /tmp/grafana.key \
  -out /tmp/grafana.crt \
  -subj "/CN=127.0.0.1/O=AIOps" \
  -addext "subjectAltName=IP:127.0.0.1"

kubectl delete secret grafana-tls-secret -n monitoring --ignore-not-found
kubectl create secret tls grafana-tls-secret \
  --cert=/tmp/grafana.crt \
  --key=/tmp/grafana.key \
  -n monitoring

echo "TLS Secret creation confirmation"
kubectl get secret grafana-tls-secret -n monitoring

kubectl create secret generic grafana-github-oauth \
  --from-literal=client_id=Ov23liONDXiYq08LkxE0 \
  --from-literal=client_secret=b092606d3358b32cf5703a01a3895d76fa5e2876 \
  -n monitoring
#Core Networking, Storage and Service Accounts
kubectl apply -f k8s-manifests/service_account.yaml 2>/dev/null
kubectl apply -f k8s-manifests/grafana_rbac.yaml
kubectl apply -f k8s-manifests/fluent-bit_rbac.yaml

#Configuration
kubectl apply -f k8s-manifests/prometheus_cm.yaml
kubectl apply -f k8s-manifests/prometheus-rules.yaml
kubectl apply -f k8s-manifests/alertmanager_cm.yaml
kubectl apply -f k8s-manifests/otel-collector_cm.yaml
kubectl apply -f k8s-manifests/fluent-bit_cm.yaml
kubectl apply -f k8s-manifests/jaeger_cm.yaml
kubectl apply -f k8s-manifests/grafana-dashboards.yaml

#Core Backend Services Infrastructure Triggers
kubectl apply -f k8s-manifests/fluent-bit-ds.yaml
kubectl apply -f k8s-manifests/prometheus_deploy.yaml
kubectl apply -f k8s-manifests/prometheus_svc.yaml
kubectl apply -f k8s-manifests/jaeger_deploy.yaml
kubectl apply -f k8s-manifests/alertmanager_deploy.yaml
kubectl apply -f k8s-manifests/alertmanager_svc.yaml
kubectl apply -f k8s-manifests/otel-collector_deploy.yaml
kubectl apply -f k8s-manifests/otel-collector_svc.yaml
kubectl apply -f k8s-manifests/blackbox_deploy.yaml
kubectl apply -f k8s-manifests/blackbox_svc.yaml
kubectl apply -f k8s-manifests/loki_deploy.yaml
kubectl apply -f k8s-manifests/loki_svc.yaml
kubectl apply -f k8s-manifests/node-exporter_deploy.yaml
kubectl apply -f k8s-manifests/node-exporter_svc.yaml

#Grafana Portal Deployment
kubectl apply -f k8s-manifests/grafana_deploy.yaml
kubectl apply -f k8s-manifests/grafana_svc.yaml
kubectl apply -f k8s-manifests/grafana_ingress.yaml
kubectl apply -f k8s-manifests/grafana-storage.yaml
kubectl apply -f k8s-manifests/prometheus_storage.yaml
kubectl apply -f k8s-manifests/jaeger_storage.yaml

echo "============================================="
echo "InelObservPlatform Setted Up Successfully"
