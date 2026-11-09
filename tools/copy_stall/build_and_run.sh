#!/usr/bin/env bash
# Measures where ndt_cuda uploads the map when Autoware's map update thread copies the NDT object: in the copy
# (map update thread) or in the first align() of the copy (scan callback). Compares the original and the fixed
# ndt_cuda of the benchmark workspaces (scripts/setup_workspaces.sh ndt_cuda ndt_cuda_fix).
#
# usage: tools/copy_stall/build_and_run.sh
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../../harness/common.sh"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for option in ndt_cuda ndt_cuda_fix; do
  ws="$WORKSPACES_DIR/$option"
  lib="$ws/install/ndt_cuda/lib"
  [[ -d "$lib" ]] || { echo "build $option first: scripts/setup_workspaces.sh $option" >&2; exit 1; }
  g++ -O2 -std=c++17 "$HERE/copy_stall.cpp" -I"$ws/install/ndt_cuda/include/ndt_cuda" -I/usr/include/pcl-1.14 -I/usr/include/eigen3 \
    -L"$lib" -Wl,-rpath,"$lib" -lndt_cuda -lpcl_common -lpcl_registration -lpcl_kdtree -lpcl_search -o "$HERE/copy_stall_$option"
  echo "== $option"
  WARM=1 "$HERE/copy_stall_$option"
done
