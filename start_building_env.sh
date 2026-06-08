#!/bin/bash
echo "========================================================="
echo " LAUNCHING INEL OBSERVABILITY PLATFORM AUTOMATION ENGINE"
echo "========================================================="

# 1. Namespace Check & Creation
echo "[INFO] Verifying Monitoring Namespace Layer..."
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -

# 2. Automated SSL/TLS Engine Fix (The Gatekeeper)
echo "[INFO] Securing Communication: Injecting TLS Credentials..."
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout k8s-manifests/tls.key -out k8s-manifests/tls.crt \
  -subj "/CN=localhost/O=InelObservPlatform" 2>/dev/null

kubectl delete secret grafana-tls-secret -n monitoring --ignore-not-found
kubectl create secret tls grafana-tls-secret \
  --cert=k8s-manifests/tls.crt \
  --key=k8s-manifests/tls.key \
  --namespace=monitoring

# 3. Step-by-Step Order-Based Kubernetes Deployment
echo "[INFO] Orchestrating Infrastructure Manifests Layer..."

# Core Networking, Storage and Service Accounts First
kubectl apply -f k8s-manifests/service_account.yaml 2>/dev/null
kubectl apply -f k8s-manifests/grafana_rbac.yaml
kubectl apply -f k8s-manifests/grafana-storage.yaml 2>/dev/null
kubectl apply -f k8s-manifests/prometheus_storage.yaml 2>/dev/null
kubectl apply -f k8s-manifests/jaeger_storage.yaml 2>/dev/null

# Configuration Engine Mounts
kubectl apply -f k8s-manifests/prometheus_cm.yaml
kubectl apply -f k8s-manifests/otel-collector_cm.yaml
kubectl apply -f k8s-manifests/jaeger_cm.yaml
kubectl apply -f k8s-manifests/grafana-dashboards.yaml 2>/dev/null
kubectl apply -f k8s-manifests/slo-rules.yaml 2>/dev/null

# Core Backend Services Infrastructure Triggers
kubectl apply -f k8s-manifests/prometheus_deploy.yaml
kubectl apply -f k8s-manifests/prometheus_svc.yaml
kubectl apply -f k8s-manifests/jaeger_deploy.yaml
kubectl apply -f k8s-manifests/otel-collector_deploy.yaml
kubectl apply -f k8s-manifests/otel-collector_svc.yaml

# Main Application & Secured Grafana Portal Deployment
kubectl apply -f k8s-manifests/grafana_deploy.yaml
kubectl apply -f k8s-manifests/grafana_svc.yaml
kubectl apply -f k8s-manifests/grafana_ingress.yaml
echo "========================================================="
