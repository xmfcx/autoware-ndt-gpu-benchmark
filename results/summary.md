### Resource use (tiled map)

CPU at 10 Hz: CPU time of the scan matcher process in one real-time (1x) run, in % of one core. GPU at 10 Hz: GPU busy time per scan (Nsight Systems, 8x run) times 10 scans per second, in % of the GPU. Initial pose search and memory: median of the five 8x runs.

| Option | CPU at 10 Hz (% of a core) | GPU at 10 Hz (% busy) | Initial pose: time (s) | Initial pose: CPU time (s) | Initial pose: peak CPU (% of a core) | Initial pose: GPU busy (ms) | RSS (MiB) | VRAM (MiB) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Autoware NDT (CPU) | 17.6 | 0.00 | 4.11 | 16.19 | 410 | 0 | 53 | 0 |
| ndt_cuda (Melike Tanrıkulu), original | 3.3 | 0.23 | 0.50 | 0.45 | 110 | 302 | 210 | 262 |
| ndt_cuda (Melike Tanrıkulu), fixed | 3.3 | 0.21 | 0.51 | 0.46 | 109 | 298 | 204 | 264 |
| fast_gicp NDTCuda (Kenji Koide), adapter | 5.3 | 0.45 | 1.11 | 1.07 | 110 | 405 | 394 | 282 |
| cuda_ndt_matcher (NEWSLabNTU) | 6.2 | 0.89 | 1.63 | 1.60 | 110 | 1340 | 512 | 770 |

### Speed-up against Autoware NDT (tiled map)

Autoware NDT value divided by the value of the option. 6.0x means 6 times faster (or 6 times less CPU). Below 1.0x means slower than Autoware NDT.

| Measure | ndt_cuda (Melike Tanrıkulu), original | ndt_cuda (Melike Tanrıkulu), fixed | fast_gicp NDTCuda (Kenji Koide), adapter | cuda_ndt_matcher (NEWSLabNTU) |
| --- | --- | --- | --- | --- |
| Scan to pose, median | 6.6x | 6.7x | 5.0x | 1.7x |
| Scan to pose, p99 | 2.8x | 7.4x | 1.5x | 0.5x |
| Scan right after a map update, median | 1.7x | 7.3x | 2.2x | 0.4x |
| Initial pose search, time | 8.2x | 8.0x | 3.7x | 2.5x |
| Initial pose search, CPU time | 36.3x | 35.5x | 15.1x | 10.1x |
| CPU use at 10 Hz | 5.4x | 5.3x | 3.3x | 2.9x |

### Tracking, 8x replay, single-file map (median of the runs)

| Option | Runs | Poses/scans | Latency median (ms) | Latency p99 (ms) | Latency max (ms) | Map updates | Latency after a map update, median (ms) | Latency after a map update, max (ms) | exe_time median (ms) | CPU per scan (ms) | vs Autoware NDT, median (mm) | vs Autoware NDT, max (mm) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Autoware NDT (CPU) | 5 | 290/293 | 4.68 | 8.38 | 10.11 | 0 | n/a | n/a | 4.32 | 17.21 | 0.2 | 27.3 |
| ndt_cuda (Melike Tanrıkulu), original | 5 | 290/293 | 0.81 | 1.45 | 1.80 | 0 | n/a | n/a | 0.51 | 1.57 | 0.9 | 31.5 |
| ndt_cuda (Melike Tanrıkulu), fixed | 5 | 290/293 | 0.79 | 1.39 | 1.63 | 0 | n/a | n/a | 0.46 | 1.55 | 0.6 | 23.4 |
| fast_gicp NDTCuda (Kenji Koide), adapter | 5 | 280/293 | 1.03 | 5.50 | 8.80 | 0 | n/a | n/a | 0.70 | 2.49 | 256.7 | 682.8 |
| cuda_ndt_matcher (NEWSLabNTU) | 5 | 290/293 | 2.96 | 17.18 | 20.30 | 1 | 19.64 | 19.64 | 2.87 | 4.09 | 3.9 | 25.1 |

### Tracking, 8x replay, tiled map (median of the runs)

| Option | Runs | Poses/scans | Latency median (ms) | Latency p99 (ms) | Latency max (ms) | Map updates | Latency after a map update, median (ms) | Latency after a map update, max (ms) | exe_time median (ms) | CPU per scan (ms) | vs Autoware NDT, median (mm) | vs Autoware NDT, max (mm) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Autoware NDT (CPU) | 5 | 290/293 | 5.02 | 9.03 | 11.27 | 5 | 5.98 | 6.38 | 4.57 | 18.16 | 0.4 | 26.7 |
| ndt_cuda (Melike Tanrıkulu), original | 5 | 290/293 | 0.76 | 3.19 | 4.22 | 5 | 3.54 | 4.22 | 0.41 | 1.60 | 1.1 | 32.2 |
| ndt_cuda (Melike Tanrıkulu), fixed | 5 | 290/293 | 0.75 | 1.23 | 1.49 | 5 | 0.82 | 1.00 | 0.41 | 1.51 | 0.8 | 25.1 |
| fast_gicp NDTCuda (Kenji Koide), adapter | 5 | 279/293 | 1.01 | 6.03 | 8.77 | 5 | 2.68 | 3.65 | 0.68 | 3.61 | 296.2 | 632.0 |
| cuda_ndt_matcher (NEWSLabNTU) | 5 | 290/293 | 2.91 | 16.95 | 20.19 | 5 | 14.36 | 19.48 | 2.76 | 4.44 | 3.9 | 25.2 |

### Replay rate, tiled map

| Option | Rate | Poses/scans | Latency median (ms) | Latency p99 (ms) | Latency max (ms) | CPU per scan (ms) | CPU while tracking (% of a core) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Autoware NDT (CPU) | 1x | 291/293 | 4.45 | 7.48 | 7.76 | 18.16 | 17.6 |
| Autoware NDT (CPU) | 8x | 290/293 | 5.02 | 9.03 | 11.27 | 18.16 | 118.1 |
| Autoware NDT (CPU) | 16x | 281/293 | 5.12 | 14.08 | 16.65 | 17.89 | 189.3 |
| ndt_cuda (Melike Tanrıkulu), original | 1x | 290/293 | 0.91 | 2.85 | 3.85 | 3.38 | 3.3 |
| ndt_cuda (Melike Tanrıkulu), original | 8x | 290/293 | 0.76 | 3.19 | 4.22 | 1.60 | 10.4 |
| ndt_cuda (Melike Tanrıkulu), original | 16x | 290/293 | 0.71 | 3.20 | 4.07 | 1.27 | 13.8 |
| ndt_cuda (Melike Tanrıkulu), fixed | 1x | 291/293 | 0.93 | 1.56 | 1.84 | 3.42 | 3.3 |
| ndt_cuda (Melike Tanrıkulu), fixed | 8x | 290/293 | 0.75 | 1.23 | 1.49 | 1.51 | 9.8 |
| ndt_cuda (Melike Tanrıkulu), fixed | 16x | 290/293 | 0.72 | 1.25 | 1.65 | 1.25 | 13.7 |
| fast_gicp NDTCuda (Kenji Koide), adapter | 1x | 276/293 | 1.24 | 5.31 | 9.65 | 5.52 | 5.3 |
| fast_gicp NDTCuda (Kenji Koide), adapter | 8x | 279/293 | 1.01 | 6.03 | 8.77 | 3.61 | 23.5 |
| fast_gicp NDTCuda (Kenji Koide), adapter | 16x | 242/293 | 1.02 | 10.56 | 12.13 | 4.46 | 46.3 |
| cuda_ndt_matcher (NEWSLabNTU) | 1x | 290/293 | 3.18 | 16.51 | 19.50 | 6.36 | 6.2 |
| cuda_ndt_matcher (NEWSLabNTU) | 8x | 290/293 | 2.91 | 16.95 | 20.19 | 4.44 | 28.9 |
| cuda_ndt_matcher (NEWSLabNTU) | 16x | 290/293 | 2.81 | 20.80 | 26.22 | 4.08 | 44.5 |

### Open loop: same initial guess for every scan (single-file map, 8x)

Map loader and scan matcher only. The bag plays the EKF poses of one closed-loop run of Autoware NDT as the initial guesses, so every option aligns every scan from the same guess. The reference is the first open-loop run of Autoware NDT. Position and rotation differences are per scan, matched by the scan time stamp. The Autoware NDT row compares its runs 2 and 3 with run 1.

x and y of the output pose are float32 values in map coordinates (Autoware's NDT keeps the pose as a float matrix). At this map's coordinates they can only change in steps of 7.8 mm (x) and 3.9 mm (y), so the table shows how often they are the same float value. z is near 0 and has no such limit, so the z difference shows how far the alignments really differ.

| Option | Runs | Poses/scans | Iterations | Same iteration count (%) | Same x and y float value (%) | z diff median (µm) | z diff p95 (µm) | z diff max (µm) | Rotation diff median (deg) | Rotation diff max (deg) | 3D diff median (µm) | 3D diff max (µm) | TP diff median | NVTL diff median |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Autoware NDT (CPU) | 3 | 284/298 | 2.24 | 100.0 | 100.0 | 0 | 0 | 0 | 0.0000 | 0.0000 | 0 | 0 | 0.0000 | 0.0000 |
| ndt_cuda (Melike Tanrıkulu), original | 3 | 284/298 | 2.23 | 92.2 | 62.5 | 211 | 1073 | 4879 | 0.0015 | 0.0462 | 429 | 14087 | 0.0020 | 0.0003 |
| ndt_cuda (Melike Tanrıkulu), fixed | 3 | 285/298 | 2.22 | 92.2 | 62.5 | 211 | 1073 | 4879 | 0.0015 | 0.0462 | 429 | 14087 | 0.0020 | 0.0003 |
| fast_gicp NDTCuda (Kenji Koide), adapter | 3 | 278/298 | 1.49 | 37.8 | 0.0 | 23319 | 55934 | 71922 | 0.1747 | 0.5233 | 59124 | 197677 | 0.0311 | 0.0167 |
| cuda_ndt_matcher (NEWSLabNTU) | 3 | 289/298 | 2.23 | 90.5 | 48.2 | 298 | 1648 | 3468 | 0.0021 | 0.0388 | 3906 | 11729 | 0.0049 | 0.0006 |
