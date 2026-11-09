#!/usr/bin/env bash
# Downloads the data of the benchmark into $DATA_DIR and checks it against config/data.sha256.
#
#   benchmark-inputs-v1.tar.gz  the recorded inputs (closed and open loop) and the sample map in 20 m tiles
#   sample-map-rosbag.zip       Autoware's sample map (the single-file map of the benchmark)
#   sample-rosbag.zip           Autoware's sample rosbag (raw sensor data), only with --raw
#
# The files come from the release "data-v1" of this repository. The two Autoware files are copies of the files that
# Autoware's demo_artifacts Ansible role downloads, with the same checksums. --from-autoware gets them from there.
#
# usage: scripts/download_data.sh [--raw] [--from-autoware]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../harness/common.sh"

RELEASE_URL="${RELEASE_URL:-https://github.com/xmfcx/autoware-ndt-gpu-benchmark/releases/download/data-v1}"
AUTOWARE_URL="https://autoware-files.s3.us-west-2.amazonaws.com"
RAW=0
FROM_AUTOWARE=0
for arg in "$@"; do
  case "$arg" in
    --raw) RAW=1 ;;
    --from-autoware) FROM_AUTOWARE=1 ;;
    *) echo "usage: $0 [--raw] [--from-autoware]" >&2; exit 1 ;;
  esac
done

DOWNLOADS="$DATA_DIR/downloads"
mkdir -p "$DOWNLOADS"

fetch() {
  local name=$1 url=$2
  local expected
  expected=$(awk -v n="$name" '$2 == n {print $1}' "$BENCH_ROOT/config/data.sha256")
  if [[ -f "$DOWNLOADS/$name" ]] && echo "$expected  $DOWNLOADS/$name" | sha256sum -c --status; then
    echo "[data] $name is already downloaded"
    return 0
  fi
  echo "[data] downloading $name"
  curl -fL --retry 3 -o "$DOWNLOADS/$name.part" "$url"
  mv "$DOWNLOADS/$name.part" "$DOWNLOADS/$name"
  echo "$expected  $DOWNLOADS/$name" | sha256sum -c --quiet || { echo "checksum mismatch for $name" >&2; exit 1; }
}

fetch benchmark-inputs-v1.tar.gz "$RELEASE_URL/benchmark-inputs-v1.tar.gz"
if ((FROM_AUTOWARE)); then
  fetch sample-map-rosbag.zip "$AUTOWARE_URL/maps/demos/sample-map-rosbag.zip"
else
  fetch sample-map-rosbag.zip "$RELEASE_URL/sample-map-rosbag.zip"
fi
if ((RAW)); then
  if ((FROM_AUTOWARE)); then
    fetch sample-rosbag.zip "$AUTOWARE_URL/recordings/bags/demos/sample-rosbag.zip"
  else
    fetch sample-rosbag.zip "$RELEASE_URL/sample-rosbag.zip"
  fi
fi

echo "[data] extracting into $DATA_DIR"
tar -xzf "$DOWNLOADS/benchmark-inputs-v1.tar.gz" -C "$DATA_DIR"
mkdir -p "$DATA_DIR/maps"
unzip -oq "$DOWNLOADS/sample-map-rosbag.zip" -d "$DATA_DIR/maps"
if ((RAW)); then
  mkdir -p "$DATA_DIR/raw"
  unzip -oq "$DOWNLOADS/sample-rosbag.zip" -d "$DATA_DIR/raw"
fi
echo "[data] ready:"
for path in inputs/bag inputs_open/bag maps/sample-map-rosbag/pointcloud_map.pcd maps/sample-map-rosbag-tiled/pointcloud_map_metadata.yaml; do
  echo "  $DATA_DIR/$path"
done
((RAW)) && echo "  $DATA_DIR/raw/sample-rosbag"
exit 0
