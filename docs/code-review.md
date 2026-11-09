# Code review of the options

This page is the code-level review that came before the benchmark. It compares the source code of the options, their math against Autoware's ndt_omp, their build and their fitness for Autoware. The benchmark pages measure them.

## Short answer

I recommend ndt_cuda (meliketanrikulu) as the base for Autoware, but not in its current form. It is the only candidate that keeps the Autoware node, its C++ build, and the ndt_omp math. I confirmed the math on my GPU: all four test suites pass and the poses match ndt_omp to about 10 µm. Before it can go upstream, it needs a CPU fallback, Jetson AGX Orin results, and working CI. It also had a map upload that ran in the scan thread. The fix for that is in meliketanrikulu/ndt_cuda pull request 2 (see [The ndt_cuda fix](ndt-cuda-fix.md)).

cuda_ndt_matcher (NEWSLabNTU) has the most features and the only Orin results, but it replaces the node with about 45k lines of Rust. It has no LICENSE file, and code review found several math bugs. fast_gicp's `NDTCuda` uses a different cost function, has no Autoware scores, and does not compile with CUDA 12.8 without a patch.

## What each implementation is

- fast_gicp `NDTCuda` (koide3, 2020). A small `pcl::Registration` class in a GICP library. It minimizes a Mahalanobis distance (point-to-distribution P2D or distribution-to-distribution D2D) with a Cauchy robust kernel and Levenberg-Marquardt. It is not the Magnusson NDT score that ndt_omp and Autoware use.
- ndt_cuda (meliketanrikulu, created 2026-11-07). A C++ library that ports PCL NDT, koide3/ndt_omp and tier4/ndt_omp to CUDA with the same API. The GPU computes score, gradient and Hessian. The CPU keeps the 6x6 Newton solve and the More-Thuente line search. A script swaps two headers in `autoware_ndt_scan_matcher`, so the Autoware node itself does not change.
- cuda_ndt_matcher (NEWSLabNTU, Dec 2025 to Oct 2026). A complete ROS 2 node in Rust (rclrs) that copies the behavior of `autoware_ndt_scan_matcher`. The tracking loop runs in hand-written CUDA kernels. NVTL scoring and helpers use CubeCL (a Rust GPU kernel language that compiles at runtime through NVRTC). This is the implementation that the Autoware discussion proposes.
  - [autowarefoundation/autoware#6905](https://github.com/orgs/autowarefoundation/discussions/6905)

## Comparison table

| | fast_gicp `NDTCuda` | ndt_cuda | cuda_ndt_matcher |
| --- | --- | --- | --- |
| Form | Registration class | Library, drop-in for `pclomp::` types | Full ROS 2 node |
| Language | C++, CUDA with Thrust | C++17, CUDA | Rust, CUDA C, CubeCL |
| Size | about 700 lines for NDT | about 3.4k lines of library code | about 45k lines of Rust, 6.8k lines of CUDA |
| Cost function | Mahalanobis least squares with Cauchy kernel | Magnusson NDT score, same as ndt_omp | Magnusson NDT score |
| Optimizer | Levenberg-Marquardt (CPU) | Newton and More-Thuente on CPU, as in ndt_omp | Newton on GPU, own parallel line search |
| Per-point precision | float | float, origin-relative coordinates, double reduction | float, absolute map coordinates, float atomics |
| Determinism | not designed for it | bit-identical repeated runs (fixed reduction order) | not deterministic (float `atomicAdd`) |
| Neighbor search | DIRECT1/7/27, radius | KDTREE (exact), DIRECT26/7/1 | radius search, at most 8 voxels per point |
| Voxel grid build | GPU hash, full rebuild | CPU, bit-identical to ndt_omp, then upload | CPU, full rebuild of all tiles on each change |
| Map tiles (dynamic loading) | no | yes, `addTarget`/`removeTarget` as tier4/ndt_omp | yes, inside its own node |
| NVTL and transform probability | no | yes, on GPU | yes, NVTL by brute force over all voxels |
| GNSS regularization | no | yes, on GPU | yes, but it falls back to the CPU solver |
| Autoware node features (TPE initial pose, covariance estimation, diagnostics) | not applicable | all, because the node does not change | re-implemented in Rust |
| Build system | CMake, catkin era | ament_cmake, `find_package(ndt_cuda)` | cargo, `colcon-cargo-ros2`, rclrs |
| Runtime CUDA dependency | CUDA runtime | driver only (cudart is static) | driver plus NVRTC and cuSOLVER at runtime |
| Tested on Jetson AGX Orin | no | no (compiled for sm_87 only) | yes, by the author |
| License | BSD-3-Clause | BSD-3-Clause, plus Apache-2.0 for 3 files | no LICENSE file, crates say "MIT OR Apache-2.0" |
| Maturity | last commit April 2025, author moved to small_gicp | 13 commits in 2 days, one author | 382 commits in 11 months, one author |
| CI | none for CUDA | workflow exists, but no job ever ran (account billing lock) | none |

## What I measured myself

### ndt_cuda

I built ndt_cuda with tests, GPU tests and benchmark. The build downloads koide3/ndt_omp (`5495fd9`) and tier4/ndt_omp (`025f263`) as references.

- All four test suites pass on the RTX 3090: `ndt_cuda_test`, `ndt_cuda_multigrid_test`, `ndt_cuda_gpu_test`, `ndt_cuda_multigrid_gpu_test`.
- The benchmark aligns the two sample scans of ndt_omp (about 16k points each). In every search method and at both resolutions, ndt_cuda converged in the same number of iterations as ndt_omp. The pose difference was at most 40 µm and 0.0013°.
- GPU time per `align()` was 0.31 to 0.43 ms at 1 m resolution and 0.35 to 0.88 ms at 2 m resolution. These values agree with the author's report.

| Resolution | Method | ndt_omp (ms) | ndt_cuda (ms) | Iterations | Translation difference (m) |
| --- | --- | --- | --- | --- | --- |
| 1 m | KDTREE | 30.4 | 0.43 | 5 / 5 | 0.00000 |
| 1 m | DIRECT7 | 23.5 | 0.36 | 5 / 5 | 0.00000 |
| 2 m | KDTREE | 101 to 189 | 0.87 to 0.88 | 6 / 6 | 0.00001 |
| 2 m | DIRECT7 | 70 to 90 | 0.67 to 0.78 | 6 / 6 | 0.00004 |

The ndt_omp times on my machine were noisy, so I do not quote a speedup factor from them. The agreement values are reliable. The GPU times are stable from run to run.

### The map upload moves into the scan thread (ndt_cuda)

I found this problem in the code and then measured it. In Autoware, `MapUpdateModule::update_map_internal()` builds the map in `secondary_ndt_ptr`, copies it with `std::make_shared<NdtType>(*secondary_ndt_ptr)`, and swaps the copy into `ndt_ptr_` (`src/map_update_module.cpp:186-193`). The goal is to keep heavy work out of the scan callback.

The ndt_cuda copy constructor creates a new, empty GPU state and sets `target_upload_pending_` (`include/ndt_cuda/impl/ndt_cuda.hpp:93-94`). The first `align()` after the swap then merges all tiles, builds the hash table, and uploads the map (`prepareTarget()` in `computeTransformation()`, `impl/ndt_cuda.hpp:247`). This work runs in the scan callback while it holds the `ndt_ptr_` lock. The secondary instance also uploads the same map once, and that upload is never used for alignment.

I measured it with a synthetic map: 225 tiles of 20 m (300 m by 300 m, like `map_radius` 150 m), resolution 2 m, 36000 voxels, 1102 scan points. The test program is `tools/copy_stall/copy_stall.cpp`, and `tools/copy_stall/build_and_run.sh` builds and runs it against the original and the fixed ndt_cuda.

| Step | Thread in Autoware | Time |
| --- | --- | --- |
| `secondary.createVoxelKdtree()` | map update | 3.71 ms |
| Copy constructor | map update | 0.05 ms |
| First `align()` on the copy | scan callback | 5.13 ms |
| Next `align()` calls | scan callback | 0.43 ms |

The cost grows with the number of voxels (about 0.13 µs per voxel here). A dense city map can have several hundred thousand voxels, so the stall can reach tens of milliseconds once per map update. The fix is small: upload in the copy constructor, or upload on the copy before the swap. The ndt_cuda Autoware README says that map updates do not delay the alignment. That statement is not correct for this copy path.

### fast_gicp

The CUDA build fails with CUDA 12.8 with `error: "thrust::pair" is ambiguous`. The cause is a forward declaration of `thrust::pair` in `include/fast_gicp/cuda/ndt_cuda.cuh` and `fast_vgicp_cuda.cuh`, which conflicts with newer CCCL. I replaced the forward declarations with includes in a scratch copy, and then it built.

On the same sample scans, `NDTCuda` D2D took about 4 ms per call (with a voxel map rebuild in each call) and P2D about 5 ms. The final fitness scores (0.200 and 0.197) differ from PCL NDT (0.229) and GICP (0.204), because each method minimizes a different cost. That is expected, but it means that its results and scores are not comparable with Autoware's NDT.

### cuda_ndt_matcher

The node crate did not build here, because it needs ROS message crates that `colcon-cargo-ros2` generates from an Autoware 1.5.0 Humble install. I built and tested the two library crates (`cuda_ffi`, `ndt_cuda`) in a copy of the workspace without the node.

- With CUDA 12.8 runtime libraries, all 397 unit tests pass (60 in `cuda_ffi`, 337 in `ndt_cuda`, 1 ignored).
- With the default `/usr/local/cuda` (CUDA 13.0) on the library path, 18 GPU tests fail with `libnvrtc.so: undefined symbol: nvrtcGetNVVM`. The cause is cudarc's runtime loading of NVRTC and cuSOLVER. It shows that the runtime CUDA version must match what cudarc expects. ndt_cuda does not have this problem, because it links the CUDA runtime statically and compiles its kernels ahead of time.

## Findings for each implementation

### fast_gicp `NDTCuda`

Strengths:

- Small and readable. The GPU builds the voxel hash map, which ndt_cuda does on the CPU.
- D2D mode is fast when the source is also voxelized.

Problems for Autoware:

- It is a different algorithm. Autoware uses the transform probability and NVTL (nearest voxel transformation likelihood) to accept or reject a pose, and `NDTCuda` computes neither.
- No map tiles, no regularization, no Hessian in Autoware's form for covariance estimation.
- Float coordinates without an origin shift. Autoware maps use coordinates near 10^5 m, where one float step is about 8 mm.
- Voxels with 6 or fewer points are skipped (`num_points <= 6`), and covariances are clamped at a minimum eigenvalue of 1e-3. Both differ from ndt_omp.
- Maintenance mode. The author recommends small_gicp, which has no CUDA support.

### ndt_cuda (meliketanrikulu)

Strengths:

- Same math as ndt_omp. The per-point code in `src/ndt_cuda_kernels.cuh` follows Equations 6.9 to 6.13 of Magnusson (2009). The tests compare it with koide3/ndt_omp and tier4/ndt_omp, and they pass on my GPU.
- The Autoware node stays the same, so every node feature keeps working: TPE initial pose, all covariance estimation modes, GNSS regularization, no-ground scores, diagnostics, and debug topics.
- C++17 and ament_cmake. It fits the Autoware build without new tools.
- Origin-relative float coordinates (`chooseOrigin()`, `setTransform()`), so large map coordinates do not lose precision. The author's test shifts the map by 47 km and gets the same result.
- Deterministic results through a fixed reduction order in double precision.
- The KDTREE search is exact on the GPU. It scans the 27 neighbor cells and keeps voxels whose mean is closer than the resolution. This is the same neighbor set as ndt_omp's radius search, with no cap.
- Low GPU use: 86 MiB of video memory and about 0.3 ms of GPU time per scan in the author's Autoware run.
- Kernels share code with a CPU emulation, so most tests run without a GPU.

Problems:

- No CPU fallback. The Autoware patch deletes the ndt_omp sources, and the node stops at startup without an NVIDIA GPU. `autoware_ndt_scan_matcher` is in `autoware_core`, which must build and run without CUDA.
- The map upload runs in the scan callback after each map update (see the measurement in the previous section).
- Every map change merges and uploads all loaded tiles again. The voxel grid is built on the CPU. Both are on the author's roadmap.
- Not tested on Jetson AGX Orin, which is the platform that started the discussion.
- Very new: 13 commits in 2 days, one author. No CI job ever ran, because the GitHub account is locked for billing.
- Float per-point math. Autoware's in-tree ndt_omp uses double (`Eigen::Matrix<double, 16, 4> h_ang_`), so results are close but not identical (a 4 mm median difference in the author's replay).
- One documentation claim is wrong for Autoware. The README says that ndt_cuda fixes a Hessian sign error (`+sin(pitch)` in `h_ang.row(6)`). Autoware's copy already uses `-sy` there (`src/ndt_omp/multigrid_ndt_omp_impl.hpp:599`). So against Autoware the difference comes from float precision, not from the sign.
- Every copy of the NDT object creates its own GPU stream and its own map copy in video memory. Autoware holds two or three copies during a map update.

### cuda_ndt_matcher (NEWSLabNTU)

Strengths:

- The most complete GPU work. The whole tracking loop runs in CUDA kernels, with an f64 Jacobi eigen-solve inside the kernel for the Newton step.
- Re-implements almost all node features: `ndt_align_srv`, `trigger_node_srv`, differential map loading, TPE initial pose, all four covariance modes, no-ground scores, diagnostics, and debug topics.
- The only candidate with Jetson AGX Orin results (JetPack 6.2, CUDA 12.6).
- Many unit tests (about 491 in total), which pass on my GPU with CUDA 12.8 libraries.

Problems found in code review (file paths relative to `src/`):

- TPE guidance score is inverted. The trial score is `exp(-score / 10)` (`cuda_ndt_matcher/src/initial_pose/estimator.rs:231-232` and `:334-337`), but `score` is a sum where higher is better. Good particles get a value near 0. Final selection uses NVTL, which hides the error, but the guided phase of TPE does not work. Autoware uses the transform probability here. I confirmed the code, but I did not run the node.
- Float pose state in absolute map coordinates, with no origin shift (`ndt_cuda/src/optimization/full_gpu_pipeline_v2.rs:530`). At x = 89571 m, one float step is 7.8 mm, close to `trans_epsilon` 0.01 m.
- NVTL search loops over all map voxels for each point (`ndt_cuda/src/derivatives/gpu.rs`, the `for v in 0..num_voxels` loop). The cost grows with the map size and it runs for each scan and each particle. It also keeps the first 8 voxels by index, so it can miss the best voxel.
- The tracking kernels keep at most 8 neighbor voxels per point (`GRAPH_MAX_NEIGHBORS = 8` in `cuda_ffi/csrc/ndt_graph_common.cuh:20`). ndt_omp has no cap.
- GNSS regularization sends the alignment to the CPU solver (`ndt_cuda/src/ndt.rs:437`).
- The opt-in batch mode solves with Cholesky, which fails for the negative definite Hessian that Autoware's constants give. The kernel then reports convergence without a step. This comes from code reading only.
- The node is not a drop-in replacement. It publishes different topic names, it hard-codes `output_pose_covariance`, and an environment variable (`NDT_USE_GPU`) selects the GPU.
- Some documentation claims have no code behind them. No CUDA Graph call exists, and the TPE "GPU batch" is a sequential loop (`ndt_cuda/src/optimization/solver.rs:634`).
- License risk. There is no LICENSE file, and the math is ported from ndt_omp (BSD-2-Clause) and PCL (BSD-3-Clause) without their notices.
- Toolchain. Rust, `colcon-cargo-ros2`, rclrs and CubeCL are not in Autoware's toolchain, and rosdep cannot install rclrs. The discussion lists this as an open question.

## Published performance numbers

These numbers come from the authors, not from my runs.

| Source | Hardware | Tracking time per scan | Initial pose search | Video memory |
| --- | --- | --- | --- | --- |
| ndt_cuda Autoware report: Autoware NDT | RTX 3050 Ti laptop | 3.40 ms median, 8.56 ms p99 | 3.09 s | 0 |
| ndt_cuda Autoware report: ndt_cuda | RTX 3050 Ti laptop | 0.74 ms median, 1.19 ms p99 | 0.56 s | 86 MiB |
| ndt_cuda Autoware report: cuda_ndt_matcher | RTX 3050 Ti laptop | 3.41 ms median, 15.96 ms p99 | 1.57 s | 404 MiB |
| cuda_ndt_matcher report | RTX 5090 | 5.0 ms against 7.97 ms for Autoware | 2.6 s against 6.7 s | not given |
| cuda_ndt_matcher report | Jetson AGX Orin | 28.7 ms against 37.8 ms for Autoware | 7.4 s against 22.6 s | not given |

The three-way comparison comes from the author of ndt_cuda, on one laptop GPU and the 30 s sample bag. It ran cuda_ndt_matcher with Autoware's parameter file (line search off), not with its own configuration. Neither project has ground truth. Both measure agreement with Autoware NDT only.

## Recommendation for Autoware

Use ndt_cuda as the GPU backend of the existing `autoware_ndt_scan_matcher` node. Do not replace the node. This keeps one node, one set of parameters, and one place for future fixes. Take these steps before upstream:

1. Add a CPU fallback. Keep the ndt_omp code and select the backend with a parameter (for example `ndt.backend: omp | cuda`), or with a build option that falls back to ndt_omp when CUDA is not found. `autoware_cuda_pointcloud_preprocessor` shows the existing pattern for optional CUDA builds.
2. Apply the fix for the upload in the copy path (`patches/ndt_cuda/0001-fix-gpu_backend-share-the-uploaded-map-between-copies.patch`): copies share the uploaded GPU map, so the scan thread does no upload. It passes the ndt_cuda tests and removes the stall in the benchmark. Add a test that times the first `align()` after a copy, and also apply `patches/ndt_cuda/0002-feat-integrations-autoware-support-the-NDT-interface.patch` for the current Autoware interface.
3. Put the library in its own package (for example `autoware_ndt_cuda`) so that `autoware_core` does not need CUDA. Keep the BSD-3-Clause and Apache-2.0 notices.
4. Measure on Jetson AGX Orin with a long real drive and dynamic map loading. Compare against the Orin numbers of cuda_ndt_matcher on the same bag.
5. Upload only changed tiles, and build voxels on the GPU if the Orin numbers show that the map update is slow.
6. Get CI to run, including the GPU-less emulation tests.
7. Agree on maintainers. Both GPU projects have one author each.

What to take from the other two:

- cuda_ndt_matcher: its Orin test setup and numbers, and its fully GPU-side iteration loop. That loop is worth a test on Orin, where each host synchronization costs more. Its kernels have a C ABI, so parts can be reused if the license is clarified first.
- fast_gicp: its GPU voxel hash build is a reference for item 5. Its NDT itself is not a fit.
