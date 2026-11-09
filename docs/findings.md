# Findings

1. With the fix, ndt_cuda is the best option on every measure: 3.3% of a core and 0.2% of the GPU at 10 Hz, 0.75 ms median and 1.2 ms p99 latency, and a 0.5 s initial pose search. Its poses agree with Autoware NDT about as well as Autoware NDT agrees with itself between runs.
2. The fix removes the map update stall: scans right after an update now take 0.8 ms instead of 3.5 ms. The original's p99 on the tiled map (3.2 ms) came from these scans.
3. cuda_ndt_matcher has the highest latency outliers: p99 17 ms, which is worse than the CPU NDT (9 ms). Right after its map updates, scans take 14 ms (median). It also needs 4 times the GPU time of ndt_cuda per scan, 4.5 times the GPU time for the initial pose search, and 3 times the video memory.
4. Autoware's CPU NDT also slows down right after a map update (6.0 ms against 5.0 ms median), but by much less in relative terms.
5. fast_gicp converges to a different pose (0.3 to 0.5 m away), because it minimizes a Mahalanobis distance, not the NDT score. Autoware's score check rejects about 4% of its results. It cannot replace NDT without changes to the cost function and the thresholds.
6. With identical inputs (open loop), ndt_cuda differs from Autoware NDT by 0.2 mm in z (median). The millimeter differences in x and y are float32 rounding steps of the output pose, which Autoware's NDT also has. See the open-loop section.
7. Autoware NDT's CPU use is real work. Its 4 threads are busy for the whole scan (CPU per scan is 4 times `exe_time_ms`). In an earlier matrix on the single-file map, `OMP_WAIT_POLICY=passive` changed its CPU use by less than 5%. Those runs are not part of the published results.
