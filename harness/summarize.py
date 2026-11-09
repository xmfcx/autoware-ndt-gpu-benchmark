#!/usr/bin/env python3
"""Runs analyze.py over all results and writes Markdown tables (median over the runs of each group).

usage: summarize.py <results_dir> <out_prefix>     for example: harness/summarize.py results/runs results/summary
Writes <out_prefix>.json (all per-run metrics) and <out_prefix>.md (tables).
Run names: r8_runN (single-file map, 8x), tiled_r8_runN, tiled_r1_run1, tiled_r8_trace, tiled_r16_run1.
"""

import glob
import json
import os
import subprocess
import sys

import numpy as np

VARIANTS = ["builtin", "ndt_cuda", "ndt_cuda_fix", "fast_gicp", "cuda_ndt_matcher"]
NAMES = {"builtin": "Autoware NDT (CPU)", "ndt_cuda": "ndt_cuda (Melike Tanrıkulu), original",
         "ndt_cuda_fix": "ndt_cuda (Melike Tanrıkulu), fixed", "fast_gicp": "fast_gicp NDTCuda (Kenji Koide), adapter",
         "cuda_ndt_matcher": "cuda_ndt_matcher (NEWSLabNTU)"}


def med(values):
    values = [v for v in values if v is not None and not (isinstance(v, float) and np.isnan(v))]
    return float(np.median(values)) if values else float("nan")


def get(r, path):
    for k in path.split("."):
        if not isinstance(r, dict) or k not in r:
            return None
        r = r[k]
    return r


def fmt(v, digits=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    return f"{v:.{digits}f}"


def table(header, rows):
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    return "\n".join(out + ["| " + " | ".join(r) + " |" for r in rows])


def main():
    results_dir, prefix = sys.argv[1], sys.argv[2]
    here = os.path.dirname(os.path.abspath(__file__))
    runs = sorted(os.path.dirname(p) for p in glob.glob(os.path.join(results_dir, "*", "*", "driver.json")))
    name = os.path.basename
    tiled = [r for r in runs if name(r).startswith("tiled_")]
    opened = [r for r in runs if name(r).startswith("open_")]
    single = [r for r in runs if r not in tiled and r not in opened and name(r) != "ekf_source"]
    data = []
    for group_runs, ref in ((single, "builtin/r8_run1"), (tiled, "builtin/tiled_r8_run1"), (opened, "builtin/open_r8_run1")):
        if not group_runs:
            continue
        tmp = prefix + ".part.json"
        subprocess.run([sys.executable, os.path.join(here, "analyze.py"), tmp, os.path.join(results_dir, ref)] + group_runs, check=True)
        data += json.load(open(tmp))
        os.remove(tmp)
    json.dump(data, open(prefix + ".json", "w"), indent=1)

    def group(variant, name_prefix):
        return [r for r in data if r.get("variant") == variant and os.path.basename(r["run"]).startswith(name_prefix) and r.get("ok")]

    def trace(variant):
        t = group(variant, "tiled_r8_trace")
        return t[0] if t else None

    def gpu_per_scan(v):
        t = trace(v)
        if t is None:
            return 0.0 if v == "builtin" else None
        busy, n = get(t, "gpu.windows.tracking.busy_ms"), get(t, "tracking.outputs")
        return busy / n if busy is not None and n else None

    md = []
    # 1. Resource use (tiled map: dynamic map loading as on a vehicle)
    rows = []
    for v in VARIANTS:
        g8, g1 = group(v, "tiled_r8_run"), group(v, "tiled_r1_run")
        t = trace(v)
        gpu_init = get(t, "gpu.windows.init.busy_ms") if t else (0.0 if v == "builtin" else None)
        gs = gpu_per_scan(v)
        # GPU % at 10 Hz: busy ms per scan * 10 scans/s / 1000 ms * 100 % = busy ms per scan
        rows.append([NAMES[v], fmt(100.0 * med([get(r, "tracking.cpu_cores") for r in g1]), 1), fmt(gs, 2),
                     fmt(med([get(r, "init.seconds") for r in g8])), fmt(med([get(r, "init.cpu_s") for r in g8])),
                     fmt(100.0 * med([get(r, "init.cpu_cores_peak") for r in g8]), 0), fmt(gpu_init, 0),
                     fmt(med([get(r, "memory.rss_mib_max") for r in g8]), 0), fmt(med([get(r, "memory.vram_mib_max") for r in g8]), 0)])
    md.append("### Resource use (tiled map)\n")
    md.append("CPU at 10 Hz: CPU time of the scan matcher process in one real-time (1x) run, in % of one core. "
              "GPU at 10 Hz: GPU busy time per scan (Nsight Systems, 8x run) times 10 scans per second, in % of the GPU. "
              "Initial pose search and memory: median of the five 8x runs.\n")
    md.append(table(["Option", "CPU at 10 Hz (% of a core)", "GPU at 10 Hz (% busy)", "Initial pose: time (s)", "Initial pose: CPU time (s)",
                     "Initial pose: peak CPU (% of a core)", "Initial pose: GPU busy (ms)", "RSS (MiB)", "VRAM (MiB)"], rows))

    # 1b. Speed-up against Autoware NDT (tiled map): how many times faster (time) or lighter (CPU) each option is
    def metric(v, prefix_name, path):
        return med([get(r, path) for r in group(v, prefix_name)])
    metrics = [
        ("Scan to pose, median", lambda v: metric(v, "tiled_r8_run", "tracking.latency_ms_median")),
        ("Scan to pose, p99", lambda v: metric(v, "tiled_r8_run", "tracking.latency_ms_p99")),
        ("Scan right after a map update, median", lambda v: metric(v, "tiled_r8_run", "map_updates.latency_after_update_ms_median")),
        ("Initial pose search, time", lambda v: metric(v, "tiled_r8_run", "init.seconds")),
        ("Initial pose search, CPU time", lambda v: metric(v, "tiled_r8_run", "init.cpu_s")),
        ("CPU use at 10 Hz", lambda v: 100.0 * metric(v, "tiled_r1_run", "tracking.cpu_cores")),
    ]
    rows = []
    for label, f in metrics:
        base = f("builtin")
        row = [label]
        for v in VARIANTS[1:]:
            x = f(v)
            row.append(f"{base / x:.1f}x" if x and x == x and base == base else "n/a")
        rows.append(row)
    md.append("\n### Speed-up against Autoware NDT (tiled map)\n")
    md.append("Autoware NDT value divided by the value of the option. 6.0x means 6 times faster (or 6 times less CPU). "
              "Below 1.0x means slower than Autoware NDT.\n")
    md.append(table(["Measure"] + [NAMES[v] for v in VARIANTS[1:]], rows))

    # 2. Tracking at 8x on both maps
    for name_prefix, title in (("r8_run", "single-file map"), ("tiled_r8_run", "tiled map")):
        rows = []
        for v in VARIANTS:
            g = group(v, name_prefix)
            tr = lambda k: med([get(r, "tracking." + k) for r in g])
            mu = lambda k: med([get(r, "map_updates." + k) for r in g])
            rows.append([NAMES[v], str(len(g)), f"{fmt(tr('poses'),0)}/{fmt(tr('scans'),0)}", fmt(tr("latency_ms_median")),
                         fmt(tr("latency_ms_p99")), fmt(tr("latency_ms_max")), fmt(mu("count"), 0), fmt(mu("latency_after_update_ms_median")),
                         fmt(mu("latency_after_update_ms_max")), fmt(tr("exe_ms_median")), fmt(tr("cpu_ms_per_scan")),
                         fmt(med([get(r, "vs_reference.mm_median") for r in g]), 1), fmt(med([get(r, "vs_reference.mm_max") for r in g]), 1)])
        md.append(f"\n### Tracking, 8x replay, {title} (median of the runs)\n")
        md.append(table(["Option", "Runs", "Poses/scans", "Latency median (ms)", "Latency p99 (ms)", "Latency max (ms)", "Map updates",
                         "Latency after a map update, median (ms)", "Latency after a map update, max (ms)", "exe_time median (ms)",
                         "CPU per scan (ms)", "vs Autoware NDT, median (mm)", "vs Autoware NDT, max (mm)"], rows))

    # 3. Real time and stress (tiled map)
    rows = []
    for v in VARIANTS:
        for name_prefix, label in (("tiled_r1_run", "1x"), ("tiled_r8_run", "8x"), ("tiled_r16_run", "16x")):
            g = group(v, name_prefix)
            if not g:
                continue
            tr = lambda k: med([get(r, "tracking." + k) for r in g])
            rows.append([NAMES[v], label, f"{fmt(tr('poses'),0)}/{fmt(tr('scans'),0)}", fmt(tr("latency_ms_median")), fmt(tr("latency_ms_p99")),
                         fmt(tr("latency_ms_max")), fmt(tr("cpu_ms_per_scan")), fmt(100.0 * tr("cpu_cores"), 1)])
    md.append("\n### Replay rate, tiled map\n")
    md.append(table(["Option", "Rate", "Poses/scans", "Latency median (ms)", "Latency p99 (ms)", "Latency max (ms)", "CPU per scan (ms)",
                     "CPU while tracking (% of a core)"], rows))

    # 4. Open loop: same initial guess for every scan (recorded EKF poses), compared with Autoware NDT scan by scan
    rows = []
    for v in VARIANTS:
        g = group(v, "open_r8_run")
        if not g:
            continue
        a = lambda k: med([get(r, "vs_reference." + k) for r in g])
        tr = lambda k: med([get(r, "tracking." + k) for r in g])
        rows.append([NAMES[v], str(len(g)), f"{fmt(tr('poses'),0)}/{fmt(tr('scans'),0)}", fmt(tr("iterations_mean")),
                     fmt(100.0 * a("iterations_equal_share"), 1), fmt(100.0 * a("xy_same_float_share"), 1),
                     fmt(a("z_um_median"), 0), fmt(a("z_um_p95"), 0), fmt(a("z_um_max"), 0),
                     fmt(a("rot_deg_median"), 4), fmt(a("rot_deg_max"), 4), fmt(a("um_median"), 0), fmt(a("um_max"), 0),
                     fmt(a("tp_absdiff_median"), 4), fmt(a("nvtl_absdiff_median"), 4)])
    if rows:
        md.append("\n### Open loop: same initial guess for every scan (single-file map, 8x)\n")
        md.append("Map loader and scan matcher only. The bag plays the EKF poses of one closed-loop run of Autoware NDT as the initial "
                  "guesses, so every option aligns every scan from the same guess. The reference is the first open-loop run of Autoware NDT. "
                  "Position and rotation differences are per scan, matched by the scan time stamp. The Autoware NDT row compares its runs 2 and 3 with run 1.\n")
        md.append("x and y of the output pose are float32 values in map coordinates (Autoware's NDT keeps the pose as a float matrix). "
                  "At this map's coordinates they can only change in steps of 7.8 mm (x) and 3.9 mm (y), so the table shows how often they are "
                  "the same float value. z is near 0 and has no such limit, so the z difference shows how far the alignments really differ.\n")
        md.append(table(["Option", "Runs", "Poses/scans", "Iterations", "Same iteration count (%)", "Same x and y float value (%)",
                         "z diff median (µm)", "z diff p95 (µm)", "z diff max (µm)", "Rotation diff median (deg)", "Rotation diff max (deg)",
                         "3D diff median (µm)", "3D diff max (µm)", "TP diff median", "NVTL diff median"], rows))

    text = "\n".join(md) + "\n"
    open(prefix + ".md", "w").write(text)
    print(text)


if __name__ == "__main__":
    main()
