An end-to-end cloud-native observability stack integrated with an AI-driven Anomaly Detection Engine. 
This platform automates infrastructure health checks, monitors SLOs, and performs Automated Root Cause Analysis (RCA) using distributed tracing.Key FeaturesAutomated Orchestration: Single-script boot process for K8s nodes, pods, and port-forwarding.AIOps Brain: Real-time anomaly detection using the Isolation Forest algorithm.SRE Governance: Live Error Budget tracking and SLO violation alerts.Full-Stack Monitoring: Integrated Prometheus, Grafana, and Jaeger for P99 latency and trace analysis.Pipeline Intelligence: CI/CD monitoring with automated deployment risk assessment.

Prerequisites 
Before running the platform, ensure you have the following installed:

Kubernetes Cluster (Minikube or Kind)

kubectl configured to your cluster

Python 3.9+
Helm (for monitoring stack deployment)Installation

1. Clone the Repository
git clone https://github.com/your-username/intelligent-observability-platform.git
cd intelligent-observability-platform

2. Install Python Dependencies
pip install -r requirements.txt

3. Deploy the Monitoring Stack (K8s)
Ensure your Prometheus and Jaeger services are running in the monitoring namespace.
kubectl create namespace monitoring

# Deploy your Helm charts or manifests here
 How to Run The  is designed with a One-Click Start philosophy using the Orchestrator script.
 The platform is designed with a One-Click Start philosophy using the Orchestrator script.

1. Configure Paths
Open orchestrator.sh and update the PROJECT_DIR variable to your local path:

PROJECT_DIR=/your/path/to/project
2. Execute the Orchestrator
Give execution permissions and run the script:

chmod +x orchestrator.sh
./orchestrator.sh

3. What Happens Next?
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
