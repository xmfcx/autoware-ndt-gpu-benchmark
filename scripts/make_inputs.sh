#!/usr/bin/env bash
# Makes the inputs of the benchmark from Autoware's raw sample data, instead of downloading them. Needs the raw data
# (scripts/download_data.sh --raw) and a built Autoware.
#
#   1. One full Autoware replay of the sample rosbag (logging simulator, built-in NDT, 1x). It records the inputs of the
#      localization loop that do not depend on the scan matcher: the downsampled scan, the twist (gyro_odometer) and
#      the GNSS pose. The recorder uses the bag clock, so the result replays with --clock and works offline.
#   2. The sample map in 20 m tiles, with pointcloud_map_metadata.yaml (split_map.py).
#   3. One closed-loop benchmark run of the built-in NDT at 1x, which records the EKF poses, and the open-loop bag
#      made from them (make_open_loop_bag.py).
#
# usage: scripts/make_inputs.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../harness/common.sh"

RAW_BAG="$DATA_DIR/raw/sample-rosbag"
MAP="$DATA_DIR/maps/sample-map-rosbag"
[[ -d "$RAW_BAG" && -f "$MAP/pointcloud_map.pcd" ]] || { echo "run scripts/download_data.sh --raw first" >&2; exit 1; }

# 1. inputs of the closed loop
LOGS="$RESULTS_DIR/_make_inputs"
rm -rf "$LOGS" "$DATA_DIR/inputs"
mkdir -p "$LOGS" "$DATA_DIR/inputs"
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST ROS_LOG_DIR="$LOGS/roslog"
source_autoware
echo "[inputs] full Autoware replay of $RAW_BAG"
ros2 launch autoware_launch logging_simulator.launch.xml map_path:="$MAP" \
  vehicle_model:=sample_vehicle sensor_model:=sample_sensor_kit perception:=false planning:=false control:=false rviz:=false \
  > "$LOGS/autoware.log" 2>&1 &
trap 'kill -TERM ${RECORD:-} 2>/dev/null; bash "$HARNESS/kill_ours.sh"' EXIT
for _ in $(seq 1 120); do
  ros2 service list 2>/dev/null | grep -q /localization/pose_estimator/ndt_align_srv && break
  sleep 1
done
sleep 10
ros2 bag record --use-sim-time -s mcap -o "$DATA_DIR/inputs/bag" \
  /localization/util/downsample/pointcloud \
  /localization/twist_estimator/twist_with_covariance \
  /sensing/gnss/pose_with_covariance \
  /localization/pose_estimator/pose_with_covariance \
  > "$LOGS/record.log" 2>&1 &
RECORD=$!
sleep 3
ros2 bag play "$RAW_BAG" -r 1.0 > "$LOGS/play.log" 2>&1
sleep 3
kill -TERM "$RECORD"
wait "$RECORD" || true
RECORD=""
bash "$HARNESS/kill_ours.sh"
ros2 bag info "$DATA_DIR/inputs/bag" | grep -E 'Duration|Count'

# 2. tiled map
echo "[inputs] tiled map"
rm -rf "$DATA_DIR/maps/sample-map-rosbag-tiled"
python3 "$HARNESS/split_map.py" "$MAP/pointcloud_map.pcd" "$DATA_DIR/maps/sample-map-rosbag-tiled" 20
cp "$MAP/lanelet2_map.osm" "$MAP/map_projector_info.yaml" "$DATA_DIR/maps/sample-map-rosbag-tiled/"

# 3. open-loop inputs: EKF poses of one closed-loop run of the built-in NDT
echo "[inputs] reference run for the open-loop bag"
RATE=1 MAP_KIND=single bash "$HARNESS/run_one.sh" builtin ekf_source
rm -rf "$DATA_DIR/inputs_open"
mkdir -p "$DATA_DIR/inputs_open"
python3 "$HARNESS/make_open_loop_bag.py" "$DATA_DIR/inputs/bag" "$RESULTS_DIR/builtin/ekf_source" "$DATA_DIR/inputs_open/bag"
echo "[inputs] done"
