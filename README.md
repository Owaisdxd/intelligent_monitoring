An end-to-end cloud-native observability stack integrated with an AI-driven Anomaly Detection Engine. 

This platform automates infrastructure health checks, monitors SLOs, and performs Automated Root Cause Analysis (RCA) using distributed tracing.

**Key Features Automated Orchestration:**

    1_Single-script boot process for K8s nodes, pods, and port-forwarding.

    2_AIOps Brain: Real-time anomaly detection using the Isolation Forest algorithm.

    3_SRE Governance: Live Error Budget tracking and SLO violation alerts.

    4_Full-Stack Monitoring: Integrated Prometheus, Grafana, and Jaeger for P99 latency and trace analysis.

**Prerequisites**
 
    Before running the platform, ensure you have the following installed:

    Kubernetes Cluster (Minikube or Kind)

    kubectl configured to your cluster

    Python 3.9+

1. Clone the Repository

    git clone https://github.com/Owaisdxd/intelligent_monitoring
    cd intelligent_monitoring

2. Install Python Dependencies

    pip install -r requirements.txt

3. Deploy the Monitoring Stack (K8s)
    
    kubectl apply -f k8s-manifests/grafana-storage.yaml 2>/dev/null
    
    kubectl apply -f k8s-manifests/prometheus_storage.yaml 2>/dev/null
    
    kubectl apply -f k8s-manifests/jaeger_storage.yaml 2>/dev/null

    ./start_building_env.sh

4. Now Start checking the environment
    **NOTE this is my environment so do not confuse with the number of days and hours it is up your will be some minutes**
watch -n 1 kubectl get pods,svc,cm,pv,pvc -n monitoring

**NAME                                    READY       STATUS      RESTARTS        AGE*
pod/grafana-d997b9cc5-zsnkm             2/2         Running     0               33m
pod/jaeger-5754dcd74c-m55w9             1/1         Running     1 (14h ago)     4d12h
pod/otel-collector-dc8b885d7-65thh      1/1         Running     1 (14h ago)     4d12h
pod/otel-collector-dc8b885d7-x9jft      1/1         Running     1 (14h ago)     4d12h
pod/prometheus-6d4b48bc89-t7zng         1/1         Running     1 (14h ago)     4d12h**


**NAME                            TYPE            CLUSTER-IP          EXTERNAL-IP     PORT(S)                       AGE*
service/grafana-service         ClusterIP       10.96.137.50        <none>          3000/TCP                      4d12h
service/jaeger-service          ClusterIP       10.96.30.13         <none>          16686/TCP,4317/TCP,4318/TCP   4d12h
service/otel-collector          ClusterIP       10.96.202.247       <none>          4317/TCP,4318/TCP,8889/TCP    4d12h
service/prometheus-service      ClusterIP       10.96.103.202       <none>          9090/TCP                      4d12h**


**NAME                                DATA        AGE*
configmap/grafana-dashboard         1           4d12h
configmap/kube-root-ca.crt          1           4d12h
configmap/otel-collector-config     1           4d12h
configmap/prometheus-config         1           4d12h**


**NAME                                    CAPACITY   ACCESS MODES   RECLAIM POLICY   STATUS   CLAIM                       STORAGECLASS     VOLUMEATTRIBUTESCLASS   REASON   AGE
persistentvolume/grafana-pv-manual      5Gi        RWO            Retain           Bound    monitoring/grafana-pvc      manual-storage   <unset>                          2d20h
persistentvolume/jaeger-pv              10Gi       RWO            Retain           Bound    monitoring/jaeger-pvc       manual-storage   <unset>                          4d12h
persistentvolume/prometheus-pv          10Gi       RWO            Retain           Bound    monitoring/prometheus-pvc   manual-storage   <unset>                          4d12h**


**NAME**                                    STATUS   VOLUME              CAPACITY   ACCESS MODES   STORAGECLASS     VOLUMEATTRIBUTESCLASS   AGE
persistentvolumeclaim/grafana-pvc       Bound    grafana-pv-manual   5Gi        RWO            manual-storage   <unset>                 2d20h
persistentvolumeclaim/jaeger-pvc        Bound    jaeger-pv           10Gi       RWO            manual-storage   <unset>                 4d12h
persistentvolumeclaim/prometheus-pvc    Bound    prometheus-pv       10Gi       RWO            manual-storage   <unset>                 4d12h**

5. You do not need to start port forwarding it will be done by initiate_project_update.sh

    cd .. && chmod +x initiate_project_update.sh && ./initiate_project_update.sh

6. **What Happens Next?**

    The script will perform the following sequence:

    Check K8s Health: Validates that nodes and monitoring pods are Ready.

    Port-Forwarding: Tunnels Prometheus (9090), Grafana (3000), and Jaeger (16686) to your localhost.

    App & Traffic: Starts the Microservices (app.py) and the Traffic Generator.

    Launch AI Brain: Starts the Anomaly Detector to begin real-time system analysis.

**Dashboards**

    Once the script is running, access your insights here:

    Grafana: https://localhost:3000 (View Error Budgets & DORA Metrics)

    Prometheus: http://localhost:9090

    Jaeger UI: http://localhost:16686

**Shutdown**

    To stop all services and background processes safely, simply press Ctrl+C in the terminal. The script will trigger a cleanup function to kill all background PIDs.

#intelligent_monitoring
