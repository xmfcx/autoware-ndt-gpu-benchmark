# Sourced by the scripts of this repository: loads the configuration and sets BENCH_ROOT, HARNESS and the CPU sets.
# shellcheck shell=bash

HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCH_ROOT="$(dirname "$HARNESS")"
export BENCH_ROOT HARNESS

if [[ -f "$BENCH_ROOT/config/local.env" ]]; then
  # shellcheck disable=SC1091
  source "$BENCH_ROOT/config/local.env"
fi
# shellcheck disable=SC1091
source "$BENCH_ROOT/config/bench.env"
export ROS_SETUP AUTOWARE_DIR CUDA_HOME CUDA_ARCHITECTURES DATA_DIR WORKSPACES_DIR RESULTS_DIR ROS_DOMAIN_ID RMW_IMPLEMENTATION

# Automatic CPU sets: the first NDT_CORES physical cores (with their SMT siblings) for the scan matcher, the rest for
# everything else.
auto_cpu_sets() {
  local -A seen=()
  local ndt=() other=() cores=0 cpu siblings
  for cpu in $(ls /sys/devices/system/cpu | grep -E '^cpu[0-9]+$' | sed 's/cpu//' | sort -n); do
    siblings=$(cat "/sys/devices/system/cpu/cpu$cpu/topology/thread_siblings_list" 2>/dev/null || echo "$cpu")
    [[ -n "${seen[$siblings]:-}" ]] && continue
    seen[$siblings]=1
    if (( cores < NDT_CORES )); then ndt+=("$siblings"); cores=$((cores + 1)); else other+=("$siblings"); fi
  done
  NDT_CPUS=$(IFS=,; echo "${ndt[*]}")
  OTHER_CPUS=$(IFS=,; echo "${other[*]}")
}
if [[ -z "$NDT_CPUS" || -z "$OTHER_CPUS" ]]; then
  auto_cpu_sets
fi
export NDT_CPUS OTHER_CPUS

# Sources ROS 2 and Autoware (they read unset variables, so -u is off while sourcing).
source_autoware() {
  local restore_u=0
  [[ $- == *u* ]] && restore_u=1 && set +u
  # shellcheck disable=SC1090
  source "$ROS_SETUP"
  # shellcheck disable=SC1091
  source "$AUTOWARE_DIR/install/setup.bash"
  ((restore_u)) && set -u
  return 0
}

# Sources one overlay workspace.
source_overlay() {
  local restore_u=0
  [[ $- == *u* ]] && restore_u=1 && set +u
  # shellcheck disable=SC1090
  source "$1/install/setup.bash"
  ((restore_u)) && set -u
  return 0
}
