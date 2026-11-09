#!/usr/bin/env bash
# The benchmark matrix. The options are interleaved, so slow drifts of the machine affect all of them alike.
#   A: 8x replay, 5 runs per option, on the single-file map and on the tiled map (dynamic map loading)
#   B: 1x replay (real time), tiled map, 1 run per option
#   C: 8x with Nsight Systems, tiled map, 1 run per GPU option (GPU busy time)
#   D: 16x, tiled map, 1 run per option
#   E: open loop (map loader and NDT only, recorded EKF poses as initial guesses), single-file map, 8x, 3 runs per option
#
# usage: harness/run_matrix.sh            (all phases, about 20 minutes)
#        PHASES="A E" harness/run_matrix.sh
#        OPTIONS="builtin ndt_cuda_fix" harness/run_matrix.sh
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
read -r -a VARIANTS <<< "${OPTIONS:-builtin ndt_cuda ndt_cuda_fix fast_gicp cuda_ndt_matcher}"
PHASES="${PHASES:-A B C D E}"

run() {
  local v=$1 name=$2; shift 2
  timeout 300 env "$@" bash "$HARNESS/run_one.sh" "$v" "$name" > /dev/null 2>&1
  echo "$(date +%T) $v $name exit=$? $(grep -o 'wall_s=[0-9.]*' "$RESULTS_DIR/$v/$name/info.txt" 2>/dev/null)"
}

if [[ " $PHASES " == *" A "* ]]; then
  for i in 1 2 3 4 5; do
    for v in "${VARIANTS[@]}"; do run "$v" "r8_run$i" RATE=8 MAP_KIND=single; done
    for v in "${VARIANTS[@]}"; do run "$v" "tiled_r8_run$i" RATE=8 MAP_KIND=tiled; done
  done
fi
[[ " $PHASES " == *" B "* ]] && for v in "${VARIANTS[@]}"; do run "$v" tiled_r1_run1 RATE=1 MAP_KIND=tiled; done
if [[ " $PHASES " == *" C "* ]]; then
  for v in "${VARIANTS[@]}"; do
    [[ "$v" == builtin ]] && continue
    run "$v" tiled_r8_trace RATE=8 MAP_KIND=tiled GPU_TRACE=1
    python3 "$HARNESS/gpu_trace.py" "$RESULTS_DIR/$v/tiled_r8_trace" > /dev/null 2>&1 || echo "gpu_trace failed for $v"
  done
fi
[[ " $PHASES " == *" D "* ]] && for v in "${VARIANTS[@]}"; do run "$v" tiled_r16_run1 RATE=16 MAP_KIND=tiled; done
[[ " $PHASES " == *" E "* ]] && for i in 1 2 3; do for v in "${VARIANTS[@]}"; do run "$v" "open_r8_run$i" RATE=8 MAP_KIND=single OPEN_LOOP=1; done; done
echo "$(date +%T) matrix done"
