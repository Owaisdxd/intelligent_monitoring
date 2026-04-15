#!/usr/bin/env bash
# =============================================================================
#  AIOps Platform Orchestrator
#  Boots the full stack: K8s checks → port-forwards → services → traffic → brain
# =============================================================================

set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
PROJECT_DIR="/home/os/PycharmProjects/project/intelligent-observability-platform"
SERVICES_SCRIPT="${PROJECT_DIR}/app-services/microservice-demo/app.py"
TRAFFIC_SCRIPT="${PROJECT_DIR}/aiops-engine/traffic_generator.py"
BRAIN_SCRIPT="${PROJECT_DIR}/aiops-engine/anomaly-detector.py"

NAMESPACE="monitoring"
PROMETHEUS_SVC="prometheus-service"
GRAFANA_SVC="grafana-service"
JAEGER_SVC="jaeger-service"
OTEL_COLLECTOR_SVC="otel-collector"
OTEL_HTTP_PORT=4318

PROMETHEUS_PORT=9090
GRAFANA_PORT=3000
JAEGER_UI_PORT=16686
JAEGER_OTLP_PORT=4318

PORT_FORWARD_WAIT=8
PORT_CHECK_RETRIES=5
PORT_CHECK_INTERVAL=2

# ── Watcher config ────────────────────────────────────────────────────────────
POD_WATCH_INTERVAL=60          # check pods every 1 minute
PF_WATCH_INTERVAL=30            # check port-forwards every 30 seconds
PF_RESTART_MAX_ATTEMPTS=1       # max auto-restart attempts per service

# Directory that holds all *_deploy.yaml files (grafana_deploy.yaml, etc.)
DEPLOY_DIR="${PROJECT_DIR}/k8s-manifests"
DEPLOY_READY_WAIT=30            # seconds to wait after kubectl apply before re-checking

PF_LOG_DIR="/tmp/aiops_portforward_logs"
mkdir -p "$PF_LOG_DIR"

BACKGROUND_PIDS=()

# ── Colors & Logging ──────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC}    $*"; }
log_ok()      { echo -e "${GREEN}[OK]${NC}      $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC}    $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC}   $*"; }
log_watch()   { echo -e "${CYAN}[WATCHER]${NC} $*"; }
log_section() {
  echo -e "\n${BOLD}${CYAN}══════════════════════════════════════════${NC}"
  echo -e "${BOLD}${CYAN}  $*${NC}"
  echo -e "${BOLD}${CYAN}══════════════════════════════════════════${NC}"
}

# ── Cleanup on exit ───────────────────────────────────────────────────────────
cleanup() {
  echo ""
  log_warn "Shutting down — killing background processes..."
  for pid in "${BACKGROUND_PIDS[@]}"; do
    kill "$pid" 2>/dev/null && log_info "Killed PID $pid" || true
  done
}
trap cleanup EXIT INT TERM

# ── Helpers ───────────────────────────────────────────────────────────────────
wait_for_port() {
  local name="$1"
  local port="$2"
  local retries="${PORT_CHECK_RETRIES}"

  log_info "Waiting for ${name} on port ${port}..."
  for ((i=1; i<=retries; i++)); do
    if nc -z 127.0.0.1 "$port" 2>/dev/null; then
      log_ok "${name} is reachable on http://127.0.0.1:${port}"
      return 0
    fi
    log_warn "Attempt ${i}/${retries} — ${name}:${port} not ready yet, retrying in ${PORT_CHECK_INTERVAL}s..."
    sleep "$PORT_CHECK_INTERVAL"
  done

  log_error "${name} on port ${port} is NOT reachable after ${retries} attempts."
  return 1   # caller must handle; do NOT exit here
}

port_is_open() {
  nc -z 127.0.0.1 "$1" 2>/dev/null
}

start_port_forward() {
  local name="$1"
  local svc="$2"
  local ports="$3"
  local logfile="${PF_LOG_DIR}/${name}.log"

  log_info "Starting port-forward for ${name}: ${ports}"
  # shellcheck disable=SC2086
  kubectl port-forward "svc/${svc}" $ports -n "$NAMESPACE" \
    > "$logfile" 2>&1 &
  local pid=$!
  BACKGROUND_PIDS+=("$pid")
  log_info "Port-forward PID: ${pid} (logs: ${logfile})"
  sleep "$PORT_FORWARD_WAIT"
}

# ── Watcher 1: Pod Health ─────────────────────────────────────────────────────
# Runs in the background, checks every POD_WATCH_INTERVAL seconds.
# Warns about any pod not in Running/Completed state and lists its events.
watch_pod_health() {
  log_watch "Pod health watcher started (interval: ${POD_WATCH_INTERVAL}s)"

  while true; do
    sleep "$POD_WATCH_INTERVAL"

    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Collect pods not in Running or Completed state
    local bad_pods
    bad_pods=$(kubectl get pods -n "$NAMESPACE" --no-headers 2>/dev/null \
      | grep -v -E "Running|Completed" || true)

    if [[ -z "$bad_pods" ]]; then
      log_watch "[${timestamp}] All pods healthy in namespace '${NAMESPACE}'."
    else
      echo ""
      log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      log_warn "[${timestamp}] POD HEALTH ALERT — unhealthy pods detected:"
      log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
      echo "$bad_pods"
      echo ""

      # For each unhealthy pod, show recent events to help diagnose
      while IFS= read -r line; do
        local pod_name
        pod_name=$(echo "$line" | awk '{print $1}')
        local pod_status
        pod_status=$(echo "$line" | awk '{print $3}')

        log_warn "  Pod '${pod_name}' is in state: ${pod_status}"
        log_info  "  Recent events for '${pod_name}':"
        kubectl describe pod "$pod_name" -n "$NAMESPACE" 2>/dev/null \
          | awk '/^Events:/,0' \
          | tail -n 10 \
          | sed 's/^/    /'
        echo ""
      done <<< "$bad_pods"

      log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    fi
  done
}

# ── Recovery: Pod → Deployment → YAML apply ──────────────────────────────────
# Called by watch_port_forwards when a port-forward cannot be restored.
# Escalation ladder:
#   1. Check if any pod for the service exists in the namespace.
#   2. If no pod → check if the Deployment exists.
#   3. If no Deployment → find and apply the matching *_deploy.yaml from DEPLOY_DIR.
#   4. Wait DEPLOY_READY_WAIT seconds, then retry the port-forward once.
#
# Arguments: <name>  <svc>  <ports>  <check_port>
#   name       — friendly name used for log messages and deploy file lookup
#   svc        — Kubernetes service name
#   ports      — port-forward spec, e.g. "9090:9090"
#   check_port — the single port we probe with nc to confirm reachability
recover_service() {
  local name="$1"
  local svc="$2"
  local ports="$3"
  local check_port="$4"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')

  echo ""
  log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  log_warn "[${timestamp}] RECOVERY ESCALATION — starting deep recovery for '${name}'"
  log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

  # ── Stage 1: Check for running pods ──────────────────────────────────────
  log_info "  [1/3] Checking for pods matching service '${svc}' in namespace '${NAMESPACE}'..."

  # Get the label selector from the Service so we find the right pods
  local selector
  selector=$(kubectl get svc "$svc" -n "$NAMESPACE" \
    -o jsonpath='{.spec.selector}' 2>/dev/null \
    | tr -d '{}' | sed 's/"//g' | sed 's/:/=/g' | sed 's/,/,/g' || true)

  local pod_count=0
  if [[ -n "$selector" ]]; then
    pod_count=$(kubectl get pods -n "$NAMESPACE" -l "$selector" \
      --no-headers 2>/dev/null | grep -c "Running" || true)
  fi

  if [[ "$pod_count" -gt 0 ]]; then
    log_ok "  [1/3] Found ${pod_count} running pod(s) for '${name}'. Pod layer is healthy."
    log_info "  Port-forward will be retried by the watcher loop — no deployment action needed."
    return 0
  fi

  log_warn "  [1/3] No running pods found for '${name}'. Checking Deployment..."

  # ── Stage 2: Check for the Deployment object ──────────────────────────────
  log_info "  [2/3] Looking for Deployment for service '${svc}' in namespace '${NAMESPACE}'..."

  # Try common deployment naming patterns: exact svc name, or strip trailing "-service"
  local deploy_name=""
  local candidates=("$svc" "${svc%-service}" "${name}" "${name}-deployment")

  for candidate in "${candidates[@]}"; do
    if kubectl get deployment "$candidate" -n "$NAMESPACE" &>/dev/null; then
      deploy_name="$candidate"
      break
    fi
  done

  if [[ -n "$deploy_name" ]]; then
    log_warn "  [2/3] Deployment '${deploy_name}' exists but has no running pods."
    log_info "  Attempting rollout restart of '${deploy_name}'..."
    if kubectl rollout restart deployment/"$deploy_name" -n "$NAMESPACE" 2>/dev/null; then
      log_ok "  Rollout restart issued for '${deploy_name}'."
      log_info "  Waiting ${DEPLOY_READY_WAIT}s for pods to come up..."
      sleep "$DEPLOY_READY_WAIT"
    else
      log_error "  Rollout restart failed for '${deploy_name}'."
    fi
  else
    # ── Stage 3: No Deployment found — apply the YAML ──────────────────────
    log_warn "  [2/3] No existing Deployment found for '${name}'."
    log_info "  [3/3] Searching for deploy manifest in: ${DEPLOY_DIR}"

    # Build expected filename: e.g. grafana → grafana_deploy.yaml
    # Also try the short name (strip -service suffix)
    local short_name="${name%-service}"
    local yaml_path=""
    local yaml_candidates=(
      "${DEPLOY_DIR}/${short_name}_deploy.yaml"
      "${DEPLOY_DIR}/${name}_deploy.yaml"
    )

    for candidate_yaml in "${yaml_candidates[@]}"; do
      if [[ -f "$candidate_yaml" ]]; then
        yaml_path="$candidate_yaml"
        break
      fi
    done

    if [[ -z "$yaml_path" ]]; then
      log_error "  [3/3] No deploy manifest found for '${name}'."
      log_error "  Looked for: ${yaml_candidates[*]}"
      log_error "  Please apply manually: kubectl apply -f ${DEPLOY_DIR}/${short_name}_deploy.yaml -n ${NAMESPACE}"
      return 1
    fi

    log_warn "  [3/3] Applying manifest: ${yaml_path}"
    if kubectl apply -f "$yaml_path" -n "$NAMESPACE"; then
      log_ok "  Manifest applied successfully: ${yaml_path}"
      log_info "  Waiting ${DEPLOY_READY_WAIT}s for pods to reach Running state..."
      sleep "$DEPLOY_READY_WAIT"

      # Verify pods came up after apply
      local post_apply_pods=0
      if [[ -n "$selector" ]]; then
        post_apply_pods=$(kubectl get pods -n "$NAMESPACE" -l "$selector" \
          --no-headers 2>/dev/null | grep -c "Running" || true)
      fi

      if [[ "$post_apply_pods" -eq 0 ]]; then
        log_warn "  Pods still not Running after apply. They may still be initialising."
        log_info "  Check with: kubectl get pods -n ${NAMESPACE}"
      else
        log_ok "  ${post_apply_pods} pod(s) now Running after manifest apply."
      fi
    else
      log_error "  kubectl apply failed for: ${yaml_path}"
      return 1
    fi
  fi

  # ── Final: attempt to restore port-forward ────────────────────────────────
  log_info "  Attempting to restore port-forward for '${name}' after recovery..."

  local stale_pid
  stale_pid=$(pgrep -f "kubectl port-forward svc/${svc}" 2>/dev/null || true)
  if [[ -n "$stale_pid" ]]; then
    echo "$stale_pid" | xargs kill 2>/dev/null || true
    sleep 2
  fi

  local logfile="${PF_LOG_DIR}/${name}.log"
  # shellcheck disable=SC2086
  kubectl port-forward "svc/${svc}" $ports -n "$NAMESPACE" \
    > "$logfile" 2>&1 &
  local pf_pid=$!
  BACKGROUND_PIDS+=("$pf_pid")
  sleep "$PORT_FORWARD_WAIT"

  if port_is_open "$check_port"; then
    log_ok "  '${name}' fully recovered → http://127.0.0.1:${check_port} (PID: ${pf_pid})"
    echo ""
    return 0
  else
    log_error "  '${name}' port-forward still not reachable after recovery."
    log_error "  Manual check required: kubectl get pods -n ${NAMESPACE}"
    echo ""
    return 1
  fi
}

# ── Watcher 2: Port-Forward Health ───────────────────────────────────────────
# Runs in the background, checks every PF_WATCH_INTERVAL seconds.
# If a port is unreachable it kills the stale kubectl process (if any),
# restarts the port-forward, and verifies it comes back up.
# Gives up after PF_RESTART_MAX_ATTEMPTS consecutive failures per service.
watch_port_forwards() {
  log_watch "Port-forward watcher started (interval: ${PF_WATCH_INTERVAL}s)"

  # Map of: display_name | service_name | "port1:port2 ..." | primary_check_port
  # Add or remove rows here if your port-forward list changes.
  declare -A PF_SVC=(
    [prometheus]="$PROMETHEUS_SVC"
    [grafana]="$GRAFANA_SVC"
    [jaeger]="$JAEGER_SVC"
    [otel-collector]="$OTEL_COLLECTOR_SVC"
  )
  declare -A PF_PORTS=(
    [prometheus]="${PROMETHEUS_PORT}:${PROMETHEUS_PORT}"
    [grafana]="${GRAFANA_PORT}:${GRAFANA_PORT}"
    [jaeger]="${JAEGER_UI_PORT}:${JAEGER_UI_PORT} ${JAEGER_OTLP_PORT}:${JAEGER_OTLP_PORT}"
    [otel-collector]="${OTEL_HTTP_PORT}:${OTEL_HTTP_PORT}"
  )
  declare -A PF_CHECK_PORT=(
    [prometheus]="$PROMETHEUS_PORT"
    [grafana]="$GRAFANA_PORT"
    [jaeger]="$JAEGER_UI_PORT"
    [otel-collector]="$OTEL_HTTP_PORT"
  )
  # Track consecutive failures per service
  declare -A PF_FAILURES=(
    [prometheus]=0
    [grafana]=0
    [jaeger]=0
    [otel-collector]=0
  )

  while true; do
    sleep "$PF_WATCH_INTERVAL"

    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    for name in "${!PF_SVC[@]}"; do
      local check_port="${PF_CHECK_PORT[$name]}"
      local svc="${PF_SVC[$name]}"
      local ports="${PF_PORTS[$name]}"

      if port_is_open "$check_port"; then
        # Port is up — reset failure counter
        PF_FAILURES[$name]=0
        log_watch "[${timestamp}] ${name} OK → http://127.0.0.1:${check_port}"
      else
        local failures=$(( PF_FAILURES[$name] + 1 ))
        PF_FAILURES[$name]=$failures

        echo ""
        log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        log_warn "[${timestamp}] PORT-FORWARD ALERT — '${name}' is unreachable on port ${check_port}"
        log_warn "  Consecutive failures: ${failures} / ${PF_RESTART_MAX_ATTEMPTS}"
        log_warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

        if [[ "$failures" -gt "$PF_RESTART_MAX_ATTEMPTS" ]]; then
          log_error "  Max port-forward restart attempts reached for '${name}'."
          log_warn "  Escalating to deep recovery (pod → deployment → YAML apply)..."
          if recover_service "$name" "$svc" "$ports" "$check_port"; then
            PF_FAILURES[$name]=0
          fi
          continue
        fi

        # Kill any stale kubectl port-forward process holding that port
        local stale_pid
        stale_pid=$(pgrep -f "kubectl port-forward svc/${svc}" 2>/dev/null || true)
        if [[ -n "$stale_pid" ]]; then
          log_info "  Killing stale port-forward process(es): ${stale_pid}"
          echo "$stale_pid" | xargs kill 2>/dev/null || true
          sleep 2
        fi

        # Attempt restart
        log_info "  Restarting port-forward for '${name}' (attempt ${failures})..."
        local logfile="${PF_LOG_DIR}/${name}.log"
        # shellcheck disable=SC2086
        kubectl port-forward "svc/${svc}" $ports -n "$NAMESPACE" \
          > "$logfile" 2>&1 &
        local new_pid=$!
        BACKGROUND_PIDS+=("$new_pid")
        sleep "$PORT_FORWARD_WAIT"

        if port_is_open "$check_port"; then
          log_ok "  '${name}' port-forward restored → http://127.0.0.1:${check_port} (PID: ${new_pid})"
          PF_FAILURES[$name]=0
        else
          log_error "  '${name}' still unreachable after restart attempt ${failures}."
        fi
        echo ""
      fi
    done
  done
}

# ── Step 1: Check Kubernetes nodes ───────────────────────────────────────────
check_nodes() {
  log_section "Step 1 — Kubernetes Node Health"

  if ! kubectl get nodes &>/dev/null; then
    log_error "Cannot reach Kubernetes cluster. Is kubectl configured correctly?"
    exit 1
  fi

  local not_ready
  not_ready=$(kubectl get nodes --no-headers | grep -v " Ready" | wc -l || true)

  if [[ "$not_ready" -gt 0 ]]; then
    log_error "One or more nodes are NOT Ready:"
    kubectl get nodes
    exit 1
  fi

  log_ok "All nodes are Ready:"
  kubectl get nodes
}

# ── Step 2: Check pods in monitoring namespace ────────────────────────────────
check_pods() {
  log_section "Step 2 — Pod Health in namespace '${NAMESPACE}'"

  local not_running
  not_running=$(kubectl get pods -n "$NAMESPACE" --no-headers \
    | grep -v -E "Running|Completed" | wc -l || true)

  if [[ "$not_running" -gt 0 ]]; then
    log_error "Some pods are not in Running state:"
    kubectl get pods -n "$NAMESPACE"
    log_warn "Please fix pod issues before continuing."
    exit 1
  fi

  log_ok "All pods in '${NAMESPACE}' are Running:"
  kubectl get pods -n "$NAMESPACE"
}

# ── Step 3: Port-forward Prometheus, Grafana, Jaeger, OTel ───────────────────
# For each service we try the port-forward first. If the port is still not
# reachable after all retries we immediately call recover_service() — which
# checks pods → deployment → YAML apply — right here at boot time, before
# the background watchers are even running.
setup_port_forwards() {
  log_section "Step 3 — Port Forwarding"

  # Helper: attempt port-forward then run recovery if it fails at boot.
  # Usage: _boot_pf <name> <svc> <pf-ports> <check-port>
  _boot_pf() {
    local name="$1" svc="$2" ports="$3" check_port="$4"

    if port_is_open "$check_port"; then
      log_ok "${name} port ${check_port} already open — skipping port-forward."
      return 0
    fi

    start_port_forward "$name" "$svc" "$ports"

    if wait_for_port "$name" "$check_port"; then
      return 0
    fi

    # Port-forward failed at startup → run the full recovery ladder now
    log_warn "Port-forward for '${name}' failed at startup. Running recovery..."
    set +e
    recover_service "$name" "$svc" "$ports" "$check_port"
    local rc=$?
    set -e
    if [[ "$rc" -eq 0 ]]; then
      log_ok "'${name}' recovered successfully during startup."
    else
      log_error "'${name}' could not be recovered. Continuing startup — watcher will keep retrying."
    fi
  }

  _boot_pf "prometheus"     "$PROMETHEUS_SVC"     "${PROMETHEUS_PORT}:${PROMETHEUS_PORT}"                                   "$PROMETHEUS_PORT"
  _boot_pf "grafana"        "$GRAFANA_SVC"         "${GRAFANA_PORT}:${GRAFANA_PORT}"                                         "$GRAFANA_PORT"
  _boot_pf "jaeger"         "$JAEGER_SVC"          "${JAEGER_UI_PORT}:${JAEGER_UI_PORT} ${JAEGER_OTLP_PORT}:${JAEGER_OTLP_PORT}" "$JAEGER_UI_PORT"
  _boot_pf "otel-collector" "$OTEL_COLLECTOR_SVC"  "${OTEL_HTTP_PORT}:${OTEL_HTTP_PORT}"                                    "$OTEL_HTTP_PORT"

  echo ""
  log_info "Port-forward startup summary:"
  for _entry in \
    "Prometheus|${PROMETHEUS_PORT}" \
    "Grafana|${GRAFANA_PORT}" \
    "Jaeger UI|${JAEGER_UI_PORT}" \
    "OTel Collector|${OTEL_HTTP_PORT}"
  do
    local _label="${_entry%%|*}"
    local _port="${_entry##*|}"
    if port_is_open "$_port"; then
      log_ok "  • ${_label} → http://127.0.0.1:${_port}"
    else
      log_warn "  • ${_label} → http://127.0.0.1:${_port}  [NOT reachable — watcher will retry]"
    fi
  done
}

# ── Step 4: Start microservices ───────────────────────────────────────────────
start_services() {
  log_section "Step 4 — Starting Microservices"

  if [[ ! -f "$SERVICES_SCRIPT" ]]; then
    log_error "Services script not found: ${SERVICES_SCRIPT}"
    exit 1
  fi

  log_info "Launching: python3 ${SERVICES_SCRIPT}"
  python3 "$SERVICES_SCRIPT" &
  BACKGROUND_PIDS+=("$!")
  log_ok "Microservices started (PID: ${BACKGROUND_PIDS[-1]})"
  sleep 5
}

# ── Step 5: Initialize traffic ────────────────────────────────────────────────
start_traffic() {
  log_section "Step 5 — Initializing Traffic Generator"

  if [[ ! -f "$TRAFFIC_SCRIPT" ]]; then
    log_error "Traffic script not found: ${TRAFFIC_SCRIPT}"
    exit 1
  fi

  log_info "Launching: python3 ${TRAFFIC_SCRIPT}"
  python3 "$TRAFFIC_SCRIPT" &
  BACKGROUND_PIDS+=("$!")
  log_ok "Traffic generator started (PID: ${BACKGROUND_PIDS[-1]})"
  sleep 3
}

# ── Step 6: Launch AIOps Brain ────────────────────────────────────────────────
start_brain() {
  log_section "Step 6 — Launching AIOps Brain"

  if [[ ! -f "$BRAIN_SCRIPT" ]]; then
    log_error "AIOps brain script not found: ${BRAIN_SCRIPT}"
    exit 1
  fi

  log_info "Launching: python3 ${BRAIN_SCRIPT}"
  log_info "The brain will now run in the foreground. Press Ctrl+C to shut everything down."
  echo ""

  python3 "$BRAIN_SCRIPT"
}

# ── Main ──────────────────────────────────────────────────────────────────────
main() {
  echo ""
  echo -e "${BOLD}${CYAN}"
  echo "  ╔══════════════════════════════════════════╗"
  echo "  ║        AIOps Platform Orchestrator       ║"
  echo "  ╚══════════════════════════════════════════╝"
  echo -e "${NC}"

  check_nodes
  check_pods
  setup_port_forwards
  start_services
  start_traffic

  # ── Launch background watchers ──────────────────────────────────────────────
  log_section "Background Watchers"

  watch_pod_health &
  BACKGROUND_PIDS+=("$!")
  log_ok "Pod health watcher launched (PID: ${BACKGROUND_PIDS[-1]}, every ${POD_WATCH_INTERVAL}s)"

  watch_port_forwards &
  BACKGROUND_PIDS+=("$!")
  log_ok "Port-forward watcher launched (PID: ${BACKGROUND_PIDS[-1]}, every ${PF_WATCH_INTERVAL}s)"

  # ── Brain runs in foreground (keeps script + trap alive) ───────────────────
  start_brain
}

main "$@"
