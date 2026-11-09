#!/usr/bin/env bash
# Clones the options at their pinned commits (config/versions.env), applies the patches of patches/ and builds one
# overlay workspace per option in $WORKSPACES_DIR. The Autoware workspace in $AUTOWARE_DIR is the underlay.
#
# usage: scripts/setup_workspaces.sh [ndt_cuda] [ndt_cuda_fix] [fast_gicp] [cuda_ndt_matcher]
#        (no argument: all four)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../harness/common.sh"
source "$BENCH_ROOT/config/versions.env"

OPTIONS=("$@")
[[ ${#OPTIONS[@]} -eq 0 ]] && OPTIONS=(ndt_cuda ndt_cuda_fix fast_gicp cuda_ndt_matcher)
SOURCES="$WORKSPACES_DIR/_sources"
PATCHES="$BENCH_ROOT/patches"
mkdir -p "$SOURCES"

log() { echo "[setup] $*" >&2; }

# Clones one commit without the history and without the large data folders of the repositories.
clone_at() {
  local repo=$1 commit=$2 dir=$3
  if [[ -d "$dir/.git" && "$(git -C "$dir" rev-parse HEAD)" == "$commit" ]]; then
    return 0
  fi
  rm -rf "$dir"
  log "cloning $repo at $commit"
  git init -q "$dir"
  git -C "$dir" remote add origin "$repo"
  git -C "$dir" sparse-checkout set --no-cone '/*' '!/data/'
  git -C "$dir" fetch -q --depth 1 --filter=blob:none origin "$commit"
  git -C "$dir" checkout -q FETCH_HEAD
}

# Copies a source tree into a workspace, without its .git directory.
copy_tree() {
  mkdir -p "$2"
  (cd "$1" && tar --exclude=.git -cf - .) | (cd "$2" && tar -xf -)
}

check_prerequisites() {
  [[ -f "$ROS_SETUP" ]] || { echo "ROS 2 not found at $ROS_SETUP" >&2; exit 1; }
  [[ -f "$AUTOWARE_DIR/install/setup.bash" ]] || { echo "Autoware not built at $AUTOWARE_DIR (see docs: setup)" >&2; exit 1; }
  [[ -x "$CUDA_HOME/bin/nvcc" ]] || { echo "CUDA toolkit not found at $CUDA_HOME" >&2; exit 1; }
}

autoware_ndt_scan_matcher_source() {
  local dir="$SOURCES/autoware_core"
  clone_at "$AUTOWARE_CORE_REPO" "$AUTOWARE_CORE_COMMIT" "$dir"
  echo "$dir/localization/autoware_ndt_scan_matcher"
}

ndt_cuda_source() {
  local dir="$SOURCES/ndt_cuda"
  clone_at "$NDT_CUDA_REPO" "$NDT_CUDA_COMMIT" "$dir"
  echo "$dir"
}

colcon_build() {
  local ws=$1; shift
  log "building $ws"
  (
    cd "$ws"
    source_autoware
    export PATH="$CUDA_HOME/bin:$PATH" CUDACXX="$CUDA_HOME/bin/nvcc"
    colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release -DBUILD_TESTING=OFF \
      -DCMAKE_CUDA_COMPILER="$CUDA_HOME/bin/nvcc" -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCHITECTURES" "$@" \
      > "$ws/build.log" 2>&1
  ) || { echo "build failed, see $ws/build.log" >&2; exit 1; }
}

# ndt_cuda: the library and Autoware's node with the integration headers of ndt_cuda (apply.sh).
setup_ndt_cuda() {
  local name=$1; shift
  local ws="$WORKSPACES_DIR/$name"
  rm -rf "$ws"
  mkdir -p "$ws/src"
  copy_tree "$(ndt_cuda_source)" "$ws/src/ndt_cuda"
  for patch in "$@"; do
    log "applying $(basename "$patch")"
    # patch, not git apply: the workspace is inside this repository, and git apply would resolve paths against it.
    patch -s -p1 -d "$ws/src/ndt_cuda" < "$patch"
  done
  copy_tree "$(autoware_ndt_scan_matcher_source)" "$ws/src/autoware_ndt_scan_matcher"
  bash "$ws/src/ndt_cuda/integrations/autoware/apply.sh" "$ws/src/autoware_ndt_scan_matcher"
  colcon_build "$ws" -DNDT_CUDA_BUILD_EXAMPLES=OFF
}

# fast_gicp: fast_gicp, ndt_cuda (for the scores), and Autoware's node with the adapter header.
setup_fast_gicp() {
  local ws="$WORKSPACES_DIR/fast_gicp"
  local src="$SOURCES/fast_gicp"
  clone_at "$FAST_GICP_REPO" "$FAST_GICP_COMMIT" "$src"
  git -C "$src" submodule update -q --init --depth 1 thirdparty/nvbio
  rm -rf "$ws"
  mkdir -p "$ws/src"
  copy_tree "$src" "$ws/src/fast_gicp"
  rm -rf "$ws/src/fast_gicp/data"
  log "applying 0001-thrust-forward-declarations.patch"
  patch -s -d "$ws/src/fast_gicp" -p1 < "$PATCHES/fast_gicp/0001-thrust-forward-declarations.patch"
  copy_tree "$(ndt_cuda_source)" "$ws/src/ndt_cuda"
  patch -s -p1 -d "$ws/src/ndt_cuda" < "$PATCHES/ndt_cuda/0002-feat-integrations-autoware-support-the-NDT-interface.patch"
  local pkg="$ws/src/autoware_ndt_scan_matcher"
  copy_tree "$(autoware_ndt_scan_matcher_source)" "$pkg"
  bash "$ws/src/ndt_cuda/integrations/autoware/apply.sh" "$pkg"
  cp "$PATCHES/autoware_ndt_scan_matcher/fast_gicp_multigrid_ndt_omp.h" "$pkg/include/autoware/ndt_scan_matcher/ndt_omp/multigrid_ndt_omp.h"
  python3 - "$pkg" <<'EOF'
import sys
pkg = sys.argv[1]
p = f"{pkg}/CMakeLists.txt"
s = open(p).read()
old = "target_link_libraries(multigrid_ndt_omp ${PCL_LIBRARIES} ndt_cuda::ndt_cuda)"
new = """find_package(fast_gicp REQUIRED)
find_package(CUDAToolkit REQUIRED)
target_include_directories(multigrid_ndt_omp SYSTEM PUBLIC ${fast_gicp_INCLUDE_DIRS})
target_link_libraries(multigrid_ndt_omp ${PCL_LIBRARIES} ndt_cuda::ndt_cuda ${fast_gicp_LIBRARIES} CUDA::cudart)"""
assert old in s, "CMakeLists.txt of autoware_ndt_scan_matcher changed: update scripts/setup_workspaces.sh"
open(p, "w").write(s.replace(old, new))
p = f"{pkg}/package.xml"
s = open(p).read()
open(p, "w").write(s.replace("<depend>ndt_cuda</depend>", "<depend>ndt_cuda</depend>\n  <depend>fast_gicp</depend>", 1))
EOF
  colcon_build "$ws" -DNDT_CUDA_BUILD_EXAMPLES=OFF -DBUILD_VGICP_CUDA=ON -DBUILD_apps=OFF -DCUDA_TOOLKIT_ROOT_DIR="$CUDA_HOME"
}

# cuda_ndt_matcher: a Rust workspace, built with colcon-cargo-ros2 from a Python virtual environment.
setup_cuda_ndt_matcher() {
  command -v cargo > /dev/null || { echo "cuda_ndt_matcher needs Rust (https://rustup.rs)" >&2; exit 1; }
  [[ -d "$(dirname "$ROS_SETUP")/share/test_msgs" ]] || { echo "cuda_ndt_matcher needs ros-jazzy-test-msgs (sudo apt install ros-jazzy-test-msgs)" >&2; exit 1; }
  local ws="$WORKSPACES_DIR/cuda_ndt_matcher"
  local src="$SOURCES/cuda_ndt_matcher"
  local venv="$WORKSPACES_DIR/_venv"
  clone_at "$CUDA_NDT_MATCHER_REPO" "$CUDA_NDT_MATCHER_COMMIT" "$src"
  if [[ ! -x "$venv/bin/python" ]]; then
    log "creating $venv with colcon-cargo-ros2"
    python3 -m venv --system-site-packages "$venv"
    "$venv/bin/pip" install -q colcon-cargo-ros2
  fi
  rm -rf "$ws"
  copy_tree "$src" "$ws"
  log "building $ws"
  (
    cd "$ws"
    source_autoware
    export PATH="$CUDA_HOME/bin:$PATH" CUDA_HOME CUDA_PATH="$CUDA_HOME"
    # The generated message bindings are new, but the check compares them with the time stamps of the Autoware
    # install, which a symlinked install can make look newer.
    export COLCON_CARGO_ROS2_SKIP_STAMP_CHECK=1
    "$venv/bin/python" -m colcon build --base-paths src --cmake-args -DCMAKE_BUILD_TYPE=Release --cargo-args --release \
      > "$ws/build.log" 2>&1
  ) || { echo "build failed, see $ws/build.log" >&2; exit 1; }
}

check_prerequisites
for option in "${OPTIONS[@]}"; do
  case "$option" in
    ndt_cuda) setup_ndt_cuda ndt_cuda "$PATCHES/ndt_cuda/0002-feat-integrations-autoware-support-the-NDT-interface.patch" ;;
    ndt_cuda_fix)
      setup_ndt_cuda ndt_cuda_fix "$PATCHES/ndt_cuda/0001-fix-gpu_backend-share-the-uploaded-map-between-copies.patch" \
        "$PATCHES/ndt_cuda/0002-feat-integrations-autoware-support-the-NDT-interface.patch"
      ;;
    fast_gicp) setup_fast_gicp ;;
    cuda_ndt_matcher) setup_cuda_ndt_matcher ;;
    *) echo "unknown option $option" >&2; exit 1 ;;
  esac
  log "$option ready in $WORKSPACES_DIR/$option"
done
