#!/usr/bin/env bash
# One benchmark run: the NDT localization loop (map loader, NDT, EKF, pose initializer) on the recorded inputs with
# one option. driver.py times the initial pose search, then replays the inputs and records the outputs.
# sampler.py records the CPU, memory and GPU use of the scan matcher process.
#
# usage: harness/run_one.sh <builtin|ndt_cuda|ndt_cuda_fix|fast_gicp|cuda_ndt_matcher> <run name>
#
# Environment (see also config/bench.env):
#   RATE        replay rate of the input bag (default 8: the 30 s bag plays in about 3.7 s)
#   MAP_KIND    single (the sample map as one PCD file, default) or tiled (20 m tiles: dynamic map loading swaps tiles)
#   OPEN_LOOP=1 map loader and NDT only. The bag plays the EKF poses of a reference run as NDT's initial guesses,
#               so every option gets the same guess for every scan.
#   NDT_PARAM   open loop only: an NDT parameter file instead of Autoware's
#   GPU_TRACE=1 record CUDA kernels and copies with Nsight Systems (a separate run: it adds overhead)
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

VARIANT="$1"
NAME="$2"
RATE="${RATE:-8}"
OUT="$RESULTS_DIR/$VARIANT/$NAME"
MAP_KIND="${MAP_KIND:-single}"
if [[ "$MAP_KIND" == tiled ]]; then
  MAP="$DATA_DIR/maps/sample-map-rosbag-tiled"; PCD="$MAP/pointcloud_map"
else
  MAP="$DATA_DIR/maps/sample-map-rosbag"; PCD="$MAP/pointcloud_map.pcd"
fi
if [[ "${OPEN_LOOP:-0}" == 1 ]]; then
  INPUTS="$DATA_DIR/inputs_open/bag"
  LAUNCH_FILE="$HARNESS/ndt_bench_open.launch.xml"
  PLAY_TOPICS=(/localization/util/downsample/pointcloud /localization/pose_twist_fusion_filter/biased_pose_with_covariance)
  DRIVER_ARGS=(--open-loop)
else
  INPUTS="$DATA_DIR/inputs/bag"
  LAUNCH_FILE="$HARNESS/ndt_bench.launch.xml"
  PLAY_TOPICS=(/localization/util/downsample/pointcloud /localization/twist_estimator/twist_with_covariance /sensing/gnss/pose_with_covariance)
  DRIVER_ARGS=()
fi
for path in "$INPUTS" "$PCD"; do
  [[ -e "$path" ]] || { echo "missing $path: run scripts/download_data.sh" >&2; exit 1; }
done

bash "$HARNESS/kill_ours.sh"
rm -rf "$OUT"
mkdir -p "$OUT"

export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST
export ROS_LOG_DIR="$OUT/roslog"
source_autoware
case "$VARIANT" in
  builtin) EXE=autoware_ndt_scan_matcher_node ;;
  ndt_cuda | ndt_cuda_fix | fast_gicp)
    [[ -f "$WORKSPACES_DIR/$VARIANT/install/setup.bash" ]] || { echo "build $VARIANT first: scripts/setup_workspaces.sh" >&2; exit 1; }
    source_overlay "$WORKSPACES_DIR/$VARIANT"
    EXE=autoware_ndt_scan_matcher_node
    ;;
  cuda_ndt_matcher)
    [[ -f "$WORKSPACES_DIR/$VARIANT/install/setup.bash" ]] || { echo "build $VARIANT first: scripts/setup_workspaces.sh" >&2; exit 1; }
    source_overlay "$WORKSPACES_DIR/$VARIANT"
    # cuda_ndt_matcher loads NVRTC and cuSOLVER at runtime: they must come from the same CUDA as the build.
    export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
    # find-pkg-share autoware_ndt_scan_matcher then returns the overlay, whose launch file starts cuda_ndt_matcher.
    export AMENT_PREFIX_PATH="$BENCH_ROOT/overlays/cuda_ndt_matcher:$AMENT_PREFIX_PATH"
    EXE=cuda_ndt_matcher
    ;;
  *) echo "unknown option $VARIANT" >&2; exit 1 ;;
esac

{
  echo "variant=$VARIANT name=$NAME map=$MAP_KIND open_loop=${OPEN_LOOP:-0} ndt_param=${NDT_PARAM:-default} rate=$RATE ndt_cpus=$NDT_CPUS other_cpus=$OTHER_CPUS gpu_trace=${GPU_TRACE:-0}"
  date -Is
  nvidia-smi --query-gpu=name,driver_version,clocks.sm,temperature.gpu,utilization.gpu --format=csv,noheader
  uptime
} > "$OUT/info.txt"

TRACE=()
if [[ "${GPU_TRACE:-0}" == 1 ]]; then
  TRACE=(nsys profile --trace=cuda --sample=none --cpuctxsw=none --output="$OUT/gpu_trace" --force-overwrite=true)
fi
T_START=$(date +%s.%N)
taskset -c "$OTHER_CPUS" "${TRACE[@]}" ros2 launch "$LAUNCH_FILE" map_path:="$MAP" pointcloud_map_path:="$PCD" \
  ${NDT_PARAM:+ndt_param_path:="$NDT_PARAM"} > "$OUT/launch.log" 2>&1 &
LAUNCH=$!
taskset -c "$OTHER_CPUS" ros2 bag play "$INPUTS" -r "$RATE" --clock 200 --start-paused --topics "${PLAY_TOPICS[@]}" \
  > "$OUT/play.log" 2>&1 &

cleanup() {
  [[ -n "${SAMPLER:-}" ]] && kill "$SAMPLER" 2>/dev/null
  if [[ "${GPU_TRACE:-0}" == 1 ]]; then
    # nsys writes the trace when the launch ends: let it end cleanly.
    kill -INT "$LAUNCH" 2>/dev/null; kill -TERM "$LAUNCH" 2>/dev/null
    for _ in $(seq 1 120); do kill -0 "$LAUNCH" 2>/dev/null || break; sleep 0.25; done
  fi
  bash "$HARNESS/kill_ours.sh"
}
trap cleanup EXIT

# Find the scan matcher process of this run as soon as it exists, and pin it.
NDT_PID=""
for _ in $(seq 1 200); do
  for p in $(pgrep -u "$(id -u)" -f "$EXE"); do
    [[ "$(basename "$(readlink -f "/proc/$p/exe" 2>/dev/null)")" == "$EXE" ]] || continue
    { tr '\0' '\n' < "/proc/$p/environ"; } 2>/dev/null | grep -qx "ROS_LOG_DIR=$OUT/roslog" && NDT_PID=$p
  done
  [[ -n "$NDT_PID" ]] && break
  sleep 0.05
done
if [[ -z "$NDT_PID" ]]; then echo "scan matcher process not found" | tee -a "$OUT/info.txt"; exit 1; fi
taskset -a -cp "$NDT_CPUS" "$NDT_PID" > "$OUT/taskset.txt" 2>&1
echo "ndt_pid=$NDT_PID" >> "$OUT/info.txt"

taskset -c "$OTHER_CPUS" python3 "$HARNESS/sampler.py" "$NDT_PID" "$OUT/resources.csv" 0.1 &
SAMPLER=$!

taskset -c "$OTHER_CPUS" python3 "$HARNESS/driver.py" "$OUT/driver.json" --max-seconds 60 "${DRIVER_ARGS[@]}" > "$OUT/driver.log" 2>&1
STATUS=$?
# Threads created after the first pinning (for example by a late CUDA initialization) are pinned too.
taskset -a -cp "$NDT_CPUS" "$NDT_PID" >> "$OUT/taskset.txt" 2>&1
T_END=$(date +%s.%N)
echo "driver_exit=$STATUS wall_s=$(echo "$T_END - $T_START" | bc)" | tee -a "$OUT/info.txt"
exit $STATUS
