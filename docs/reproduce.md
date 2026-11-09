# Reproduce

This page shows how to run the benchmark on your own computer. The published results come from an AMD Ryzen 9 5900X and an NVIDIA GeForce RTX 3090. On other hardware the values differ, but you can compare the options with each other.

## Requirements

- Ubuntu 24.04 with ROS 2 Jazzy.
- An NVIDIA GPU with a driver for CUDA 12.8 or newer.
- The CUDA 12.8 toolkit in `/usr/local/cuda-12.8`. Another path works if you set `CUDA_HOME`.
- Autoware, built from source (see the next section).
- Rust (from [rustup](https://rustup.rs)) and `ros-jazzy-test-msgs`, for cuda_ndt_matcher only.
- Nsight Systems (`nsys`), for the GPU busy time only.
- Python 3 with NumPy and Matplotlib.
- About 10 GB of disk space for the workspaces and the data.

## Build Autoware

The benchmark uses Autoware as the underlay of the options. `config/autoware.repos` has the exact commit of every repository that produced the published results.

1. Clone Autoware at the pinned commit:

    ```bash
    git clone https://github.com/autowarefoundation/autoware.git ~/autoware
    cd ~/autoware
    git checkout 8fbd8d94ed00a3c36221a15aa6499253e0fd1c21
    ```

2. Import the repositories at the published versions:

    ```bash
    mkdir -p src
    vcs import src < /path/to/autoware-ndt-gpu-benchmark/config/autoware.repos
    ```

3. Install the dependencies and build Autoware as the [Autoware source installation](https://autowarefoundation.github.io/autoware-documentation/main/installation/autoware/source-installation/) explains.

If your Autoware workspace is not in `~/autoware`, set its path in `config/local.env` (next section).

## Configure

Create `config/local.env` with the values of your computer. Usually you only set these two:

```bash
AUTOWARE_DIR=$HOME/autoware
CUDA_HOME=/usr/local/cuda-12.8
```

`config/bench.env` lists every value with its default. `config/local.env` is not tracked by git. The scan matcher runs on the first 4 physical cores of the CPU, and everything else runs on the other cores. To change this, set `NDT_CPUS` and `OTHER_CPUS`.

## Get the data

Download the inputs and the sample map from the release of this repository:

```bash
scripts/download_data.sh
```

The script checks every file against `config/data.sha256`. [Data](data.md) describes the files.

## Build the options

Build one overlay workspace for each GPU option:

```bash
scripts/setup_workspaces.sh
```

The script clones each option at its pinned commit (`config/versions.env`), applies the patches in `patches/`, and builds it on top of Autoware. It takes about 10 minutes. To build only some options, name them:

```bash
scripts/setup_workspaces.sh ndt_cuda_fix cuda_ndt_matcher
```

If a build fails, read `workspaces/<option>/build.log`.

## Run

1. Run one test of one option:

    ```bash
    harness/run_one.sh ndt_cuda_fix my_first_run
    ```

    The result is in `results/runs/ndt_cuda_fix/my_first_run/`.

2. Run the full matrix of the published results (about 20 minutes):

    ```bash
    harness/run_matrix.sh
    ```

3. Make the tables and the charts:

    ```bash
    python3 harness/summarize.py results/runs results/summary
    python3 harness/make_plots.py results/runs results/summary.json docs/assets/figures
    ```

The option names are `builtin` (Autoware NDT), `ndt_cuda`, `ndt_cuda_fix`, `fast_gicp` and `cuda_ndt_matcher`. These environment variables change one run:

| Variable | Values | Effect |
| --- | --- | --- |
| `RATE` | `8` (default), `1`, `16` | Replay rate of the input bag |
| `MAP_KIND` | `single` (default), `tiled` | Sample map as one file, or in 20 m tiles |
| `OPEN_LOOP` | `0` (default), `1` | Open loop: the same initial guess for every scan |
| `GPU_TRACE` | `0` (default), `1` | Record the GPU work with Nsight Systems |

Example:

```bash
MAP_KIND=tiled RATE=1 harness/run_one.sh builtin real_time_run
```

To run only some phases or options of the matrix, set `PHASES` and `OPTIONS`:

```bash
PHASES="A E" OPTIONS="builtin ndt_cuda_fix" harness/run_matrix.sh
```

## Make the inputs yourself

The inputs come from one full Autoware replay of the sample rosbag. To make them yourself instead of downloading them:

1. Download the raw sample rosbag too:

    ```bash
    scripts/download_data.sh --raw
    ```

2. Make the inputs:

    ```bash
    scripts/make_inputs.sh
    ```

The script replays the sample rosbag through the full Autoware stack once, splits the map into tiles, and makes the open-loop bag. It replaces the downloaded inputs in `data/`.

## Measure the copy stall of ndt_cuda

`tools/copy_stall/build_and_run.sh` measures the first `align()` of a copy of the NDT object, with the original and the fixed ndt_cuda. [The ndt_cuda fix](ndt-cuda-fix.md) explains the stall.

```bash
tools/copy_stall/build_and_run.sh
```

## Troubleshooting

- If a run stops with `scan matcher process not found`, read `results/runs/<option>/<run>/launch.log`.
- If cuda_ndt_matcher fails with `undefined symbol: nvrtcGetNVVM`, the runtime loads another CUDA version than the build used. Set `CUDA_HOME` to the CUDA of the build.
- If runs leave processes behind, run `harness/kill_ours.sh`. It stops only the processes of the benchmark.
- The first run of fast_gicp after a build can take a few seconds longer in the initial pose search. fast_gicp builds its CUDA code with the old FindCUDA module, which does not use `CUDA_ARCHITECTURES`. So the CUDA driver probably compiles its kernels for your GPU at the first run, and it keeps them in its cache for the next runs.
