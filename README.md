An end-to-end cloud-native observability stack integrated with an AI-driven Anomaly Detection Engine. 
This platform automates infrastructure health checks, monitors SLOs, and performs Automated Root Cause Analysis (RCA) using distributed tracing.Key Features Automated Orchestration:
Single-script boot process for K8s nodes, pods, and port-forwarding.
AIOps Brain: Real-time anomaly detection using the Isolation Forest algorithm.
SRE Governance: Live Error Budget tracking and SLO violation alerts.
Full-Stack Monitoring: Integrated Prometheus, Grafana, and Jaeger for P99 latency and trace analysis.
Pipeline Intelligence: CI/CD monitoring with automated deployment risk assessment.

Prerequisites 
Before running the platform, ensure you have the following installed:

Kubernetes Cluster (Minikube or Kind)

kubectl configured to your cluster

Python 3.9+
Helm (for monitoring stack deployment)Installation

1. Clone the Repository
git clone https://github.com/Owaisdxd/intelligent_monitoring
cd intelligent-observability-platform

2. Install Python Dependencies
pip install -r requirements.txt

3. Deploy the Monitoring Stack (K8s)
Ensure your Prometheus and Jaeger services are running in the monitoring namespace.
kubectl create namespace monitoring
kubectl get ns
kubectl get ns | grep "monitoring"

4. Now start applying yaml configuration files in  ../k8s-manifests dir
**NOTE this is my environment so do not confuse with the number of days and hours it is up your will be some minutes**
kubectl get all -n monitoring
NAME                              READY   STATUS    RESTARTS   AGE
pod/grafana-769646d885-zpbwj      2/2     Running   0          3d
pod/jaeger-5668fb4bcb-mm9bf       1/1     Running   0          3d
pod/jaeger-5668fb4bcb-t57fn       1/1     Running   0          3d
pod/prometheus-5db5d7b68c-js9vl   1/1     Running   0          3d

NAME                         TYPE        CLUSTER-IP      EXTERNAL-IP   PORT(S)                       AGE
service/grafana-service      ClusterIP   10.96.11.109    <none>        3000/TCP                      9d
service/jaeger-service       ClusterIP   10.96.65.62     <none>        16686/TCP,4317/TCP,4318/TCP   9d
service/otel-collector       ClusterIP   10.96.209.198   <none>        4317/TCP,4318/TCP,8889/TCP    9d
service/prometheus-service   ClusterIP   10.96.251.83    <none>        9090/TCP                      9d

NAME                         READY   UP-TO-DATE   AVAILABLE   AGE
deployment.apps/grafana      1/1     1            1           3d
deployment.apps/jaeger       2/2     2            2           3d
deployment.apps/prometheus   1/1     1            1           3d

NAME                                    DESIRED   CURRENT   READY   AGE
replicaset.apps/grafana-769646d885      1         1         1       3d
replicaset.apps/jaeger-5668fb4bcb       2         2         2       3d
replicaset.apps/prometheus-5db5d7b68c   1         1         1       3d

5. You do not need to start port forwarding it will be done by initiate_project_update.sh

cd .. && chmod +x initiate_project_update.sh && ./initiate_project_update.sh

6. What Happens Next?
The script will perform the following sequence:

Check K8s Health: Validates that nodes and monitoring pods are Ready.

Port-Forwarding: Tunnels Prometheus (9090), Grafana (3000), and Jaeger (16686) to your localhost.

App & Traffic: Starts the Microservices (app.py) and the Traffic Generator.

Launch AI Brain: Starts the Anomaly Detector to begin real-time system analysis.

Dashboards
Once the script is running, access your insights here:

Grafana: http://localhost:3000 (View Error Budgets & DORA Metrics)

Prometheus: http://localhost:9090

Jaeger UI: http://localhost:16686

Shutdown
To stop all services and background processes safely, simply press Ctrl+C in the terminal. The script will trigger a cleanup function to kill all background PIDs.
# Intelligent-DevOps-Observability-Platform
