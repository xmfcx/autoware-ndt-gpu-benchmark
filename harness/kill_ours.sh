#!/usr/bin/env bash
# Stops the processes of this benchmark only: those whose environment has ROS_LOG_DIR inside the results directory.
# SIGTERM first, SIGKILL for what is left after 3 s.
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
ours() {
  # One grep over all environments (-z: the entries are NUL separated). Skips this script and its caller.
  grep -lz "^ROS_LOG_DIR=$RESULTS_DIR/" /proc/[0-9]*/environ 2>/dev/null | cut -d/ -f3 | grep -vx -e "$$" -e "$PPID"
}
PIDS=$(ours)
[[ -z "$PIDS" ]] && exit 0
# shellcheck disable=SC2086
kill -TERM $PIDS 2>/dev/null
for _ in $(seq 1 30); do
  PIDS=$(ours)
  [[ -z "$PIDS" ]] && exit 0
  sleep 0.1
done
# shellcheck disable=SC2086
kill -KILL $PIDS 2>/dev/null
exit 0
