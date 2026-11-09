#!/usr/bin/env python3
"""Charts for BENCHMARK.md, from summary.json and the per-run driver.json files.

usage: make_plots.py <results_dir> <summary.json> <out_dir>
       for example: harness/make_plots.py results/runs results/summary.json docs/assets/figures

Colors: the validated categorical palette of the dataviz reference (slots 1-5 in fixed order), one color per option
in every chart. Values are labeled on the marks, because three of the colors are below 3:1 contrast on the surface.
"""

import glob
import json
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ORDER = ["builtin", "ndt_cuda_fix", "ndt_cuda", "cuda_ndt_matcher", "fast_gicp"]
COLOR = {"builtin": "#2a78d6", "ndt_cuda_fix": "#eb6834", "ndt_cuda": "#1baf7a", "cuda_ndt_matcher": "#eda100", "fast_gicp": "#e87ba4"}
LABEL = {
    "builtin": "Autoware NDT (CPU, in-tree ndt_omp)",
    "ndt_cuda_fix": "ndt_cuda (Melike Tanrıkulu), fixed",
    "ndt_cuda": "ndt_cuda (Melike Tanrıkulu), original",
    "cuda_ndt_matcher": "cuda_ndt_matcher (NEWSLabNTU)",
    "fast_gicp": "fast_gicp NDTCuda (Kenji Koide), adapter",
}
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2, "text.color": INK,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8, "grid.linestyle": "-",
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold", "axes.titlelocation": "left",
    "axes.titlecolor": INK, "legend.frameon": False, "lines.linewidth": 1.6,
})


def med(values):
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    return float(np.median(values)) if values else float("nan")


def get(r, path):
    for k in path.split("."):
        if not isinstance(r, dict) or k not in r:
            return None
        r = r[k]
    return r


class Data:
    def __init__(self, results, summary):
        self.results = results
        self.rows = json.load(open(summary))

    def group(self, v, prefix):
        return [r for r in self.rows if r.get("variant") == v and os.path.basename(r["run"]).startswith(prefix) and r.get("ok")]

    def metric(self, v, prefix, path):
        return med([get(r, path) for r in self.group(v, prefix)])

    def driver(self, v, name):
        return json.load(open(os.path.join(self.results, v, name, "driver.json")))


def hbar(ax, names, values, fmt, xlabel, title, log=False):
    y = np.arange(len(names))[::-1]
    ax.barh(y, values, height=0.55, color=[COLOR[n] for n in names], edgecolor=SURFACE, linewidth=1.5)
    ax.set_yticks(y)
    ax.set_yticklabels([LABEL[n] for n in names])
    ax.set_xlabel(xlabel)
    ax.set_title(title)
    ax.grid(axis="y", visible=False)
    if log:
        ax.set_xscale("log")
    vmax = max(v for v in values if v == v)
    for yi, v in zip(y, values):
        ax.text(v * (1.08 if log else 1.0) + (0 if log else vmax * 0.015), yi, fmt(v), va="center", ha="left", color=INK, fontsize=9)
    ax.set_xlim(right=(vmax * 3.5) if log else vmax * 1.22)


def fig_speedup(d, out):
    measures = [
        ("Scan to pose, median", "tiled_r8_run", "tracking.latency_ms_median", 1.0),
        ("Scan to pose, p99", "tiled_r8_run", "tracking.latency_ms_p99", 1.0),
        ("Scan right after a map update", "tiled_r8_run", "map_updates.latency_after_update_ms_median", 1.0),
        ("Initial pose search, time", "tiled_r8_run", "init.seconds", 1.0),
        ("Initial pose search, CPU time", "tiled_r8_run", "init.cpu_s", 1.0),
        ("CPU use at 10 Hz", "tiled_r1_run", "tracking.cpu_cores", 1.0),
    ]
    options = ORDER[1:]
    fig, ax = plt.subplots(figsize=(10, 7.2))
    band = len(options) + 1.2
    yticks, ylabels = [], []
    for i, (label, prefix, path, _) in enumerate(measures):
        base = d.metric("builtin", prefix, path)
        top = (len(measures) - 1 - i) * band
        for j, v in enumerate(options):
            val = d.metric(v, prefix, path)
            ratio = base / val
            y = top + (len(options) - 1 - j)
            ax.barh(y, ratio, left=0, height=0.7, color=COLOR[v], edgecolor=SURFACE, linewidth=1.5,
                    label=LABEL[v] if i == 0 else None)
            ax.text(ratio * 1.06, y, f"{ratio:.1f}x", va="center", ha="left", fontsize=8.5, color=INK)
        yticks.append(top + (len(options) - 1) / 2)
        ylabels.append(label)
    ax.set_xscale("log")
    ax.set_xlim(0.25, 80)
    ax.set_ylim(-1.9, len(measures) * band - 0.8)
    ax.axvline(1.0, color=INK2, linewidth=1.2)
    ax.text(1.03, -1.3, "Autoware NDT = 1x", color=INK2, fontsize=9, va="center")
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels)
    ax.grid(axis="y", visible=False)
    ax.set_xticks([0.25, 0.5, 1, 2, 5, 10, 20, 50])
    ax.set_xticklabels(["0.25x", "0.5x", "1x", "2x", "5x", "10x", "20x", "50x"])
    ax.set_xlabel("Speed-up against Autoware NDT (log scale, right of 1x = faster or less CPU)")
    ax.set_title("How many times faster than Autoware NDT? (tiled map)")
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "speedup.png"), dpi=150)
    plt.close(fig)


def per_scan_latency(drv):
    scans = {s: t for t, s in drv["scans"]}
    return [(t, (t - scans[p[1]]) * 1000.0) for t, *p in [(p[0], *p) for p in drv["poses"]] if t >= drv["resume"] and p[1] in scans]


def fig_latency_cdf(d, out):
    fig, ax = plt.subplots(figsize=(10, 5))
    for v in ORDER:
        lat = []
        for r in d.group(v, "tiled_r8_run"):
            drv = d.driver(v, os.path.basename(r["run"]))
            lat += [l for _, l in per_scan_latency(drv)]
        lat = np.sort(lat)
        cdf = np.arange(1, len(lat) + 1) / len(lat) * 100.0
        ax.plot(lat, cdf, color=COLOR[v], label=LABEL[v], linewidth=1.8)
        p99 = np.percentile(lat, 99)
        ax.plot([p99], [99], marker="o", markersize=6, color=COLOR[v], markeredgecolor=SURFACE, markeredgewidth=1.5)
    ax.set_xscale("log")
    ax.set_xlim(0.3, 25)
    ax.set_xticks([0.5, 1, 2, 5, 10, 20])
    ax.set_xticklabels(["0.5", "1", "2", "5", "10", "20"])
    ax.set_xlabel("Scan to pose (ms, log scale)")
    ax.set_ylabel("Scans answered within this time (%)")
    ax.set_ylim(0, 101)
    ax.axhline(50, color=GRID, linewidth=1)
    ax.text(0.32, 51.5, "median", color=INK2, fontsize=8.5)
    ax.text(0.32, 95.5, "dots: p99", color=INK2, fontsize=8.5)
    ax.set_title("Scan-to-pose latency of every scan (tiled map, 8x, 5 runs each)")
    ax.legend(loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(os.path.join(out, "latency_cdf.png"), dpi=150)
    plt.close(fig)


def map_update_times(d, v, name, drv):
    ev = [u[0] for u in drv.get("map_updates", [])]
    if not ev:
        import re
        pattern = re.compile(r"\[(?:INFO|WARN) (\d+\.\d+)\] \[[^\]]*map_module\]: Map update: \+")
        log = os.path.join(d.results, v, name, "launch.log")
        ev = [float(m.group(1)) for line in open(log, errors="replace") for m in [pattern.search(line)] if m]
    return [t for t in ev if drv["resume"] <= t <= drv["end"]]


def fig_latency_timeline(d, out):
    fig, axes = plt.subplots(len(ORDER), 1, figsize=(10, 9), sharex=True, sharey=True)
    for ax, v in zip(axes, ORDER):
        drv = d.driver(v, "tiled_r8_run1")
        pts = per_scan_latency(drv)
        t0 = drv["resume"]
        for i, u in enumerate(map_update_times(d, v, "tiled_r8_run1", drv)):
            ax.axvline(u - t0, color=INK2, linewidth=1, alpha=0.6)
        ax.plot([t - t0 for t, _ in pts], [l for _, l in pts], color=COLOR[v], linewidth=1.4)
        ax.set_yscale("log")
        ax.set_yticks([0.1, 0.2, 0.5, 1, 2, 5, 10, 20])
        ax.set_yticklabels(["0.1", "0.2", "0.5", "1", "2", "5", "10", "20"])
        ax.set_ylim(0.08, 30)
        ax.text(0.005, 0.92, LABEL[v], transform=ax.transAxes, fontsize=9.5, color=INK, va="top", fontweight="bold")
        ax.set_ylabel("ms")
    axes[0].text(0.995, 0.92, "gray lines: map updates", transform=axes[0].transAxes, fontsize=8.5, color=INK2, va="top", ha="right")
    axes[-1].set_xlabel("Wall time since the replay started (s), 8x replay of the 30 s bag")
    fig.suptitle("Scan-to-pose latency of each scan, one run per option (tiled map, log scale)", x=0.01, ha="left",
                 fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "latency_timeline.png"), dpi=150)
    plt.close(fig)


def fig_resources(d, out):
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.6), sharey=True)
    cpu = [100.0 * d.metric(v, "tiled_r1_run", "tracking.cpu_cores") for v in ORDER]
    gpu = []
    for v in ORDER:
        t = d.group(v, "tiled_r8_trace")
        gpu.append(0.0 if v == "builtin" else (get(t[0], "gpu.windows.tracking.busy_ms") / get(t[0], "tracking.outputs")))
    vram = [d.metric(v, "tiled_r8_run", "memory.vram_mib_max") for v in ORDER]
    hbar(axes[0], ORDER, cpu, lambda x: f"{x:.1f}%", "% of one CPU core", "CPU at 10 Hz")
    hbar(axes[1], ORDER, gpu, lambda x: f"{x:.2f}%", "% of the GPU busy (RTX 3090)", "GPU at 10 Hz")
    hbar(axes[2], ORDER, vram, lambda x: f"{x:.0f} MiB", "MiB (about 250 MiB is the CUDA context)", "Video memory")
    for ax in axes[1:]:
        ax.tick_params(axis="y", length=0)
    fig.suptitle("Resources for real-time localization (tiled map)", x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "resources.png"), dpi=150)
    plt.close(fig)


def fig_init(d, out):
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.4), sharey=True)
    secs = [d.metric(v, "tiled_r8_run", "init.seconds") for v in ORDER]
    cpus = [d.metric(v, "tiled_r8_run", "init.cpu_s") for v in ORDER]
    hbar(axes[0], ORDER, secs, lambda x: f"{x:.2f} s", "seconds", "Initial pose search: time")
    hbar(axes[1], ORDER, cpus, lambda x: f"{x:.2f} CPU-s", "CPU seconds (4 cores busy = 4 CPU-s per s)", "Initial pose search: CPU time")
    axes[1].tick_params(axis="y", length=0)
    fig.suptitle("Initial pose search: 200 particles from the GNSS pose", x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "init.png"), dpi=150)
    plt.close(fig)


def fig_open_loop(d, out):
    ref = {p[1]: p for p in d.driver("builtin", "open_r8_run1")["poses"]}
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.2), gridspec_kw={"width_ratios": [1, 1, 1.5]})
    drv = d.driver("ndt_cuda_fix", "open_r8_run1")
    pairs = [(p, ref[p[1]]) for p in drv["poses"] if p[1] in ref]
    for ax, idx, axis_name, step in ((axes[0], 2, "x", 7.8125), (axes[1], 3, "y", 3.90625)):
        diffs = np.round([1000.0 * (p[idx] - r[idx]) for p, r in pairs], 3)
        values, counts = np.unique(diffs, return_counts=True)
        ax.bar(values, counts, width=step * 0.35, color=COLOR["ndt_cuda_fix"], edgecolor=SURFACE, linewidth=1.5)
        for v, c in zip(values, counts):
            ax.text(v, c + max(counts) * 0.02, str(c), ha="center", va="bottom", fontsize=8.5, color=INK)
        ks = list(range(-3, 4))
        ax.set_xticks([k * step for k in ks])
        ax.set_xticklabels([f"{k * step:+.2f}" if k else "0" for k in ks], fontsize=8)
        ax.set_xlim(-3.6 * step, 3.6 * step)
        ax.set_ylim(0, max(counts) * 1.15)
        ax.grid(axis="x", visible=False)
        ax.set_xlabel(f"{axis_name} difference (mm), float32 step {step:.2f} mm")
        ax.set_ylabel("Scans (labels: count)")
        ax.set_title(f"{axis_name}: only whole float32 steps")
    for v in ORDER[2:]:
        dz = []
        for r in d.group(v, "open_r8_run"):
            drv_v = d.driver(v, os.path.basename(r["run"]))
            dz += [1e6 * abs(p[4] - ref[p[1]][4]) for p in drv_v["poses"] if p[1] in ref]
        dz = np.sort(np.maximum(dz, 0.1))
        label = "ndt_cuda (Melike Tanrıkulu), original and fixed (identical)" if v == "ndt_cuda" else LABEL[v]
        color = COLOR["ndt_cuda_fix"] if v == "ndt_cuda" else COLOR[v]
        axes[2].plot(dz, np.arange(1, len(dz) + 1) / len(dz) * 100.0, color=color, label=label, linewidth=1.8)
    axes[2].set_xscale("log")
    axes[2].set_xlim(0.5, 2e5)
    axes[2].set_xticks([1, 10, 100, 1000, 10000, 100000])
    axes[2].set_xticklabels(["1 µm", "10 µm", "0.1 mm", "1 mm", "1 cm", "10 cm"])
    axes[2].set_xlabel("|z difference| (log scale)")
    axes[2].set_ylabel("Scans within this difference (%)")
    axes[2].set_title("z: the real alignment difference")
    axes[2].legend(loc="upper left", fontsize=8.5)
    fig.suptitle("Open loop, same initial guess for every scan: difference to Autoware NDT (left two: ndt_cuda, Melike Tanrıkulu)",
                 x=0.01, ha="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "open_loop.png"), dpi=150)
    plt.close(fig)


def main():
    results, summary, out = sys.argv[1:4]
    os.makedirs(out, exist_ok=True)
    d = Data(results, summary)
    for f in (fig_speedup, fig_latency_cdf, fig_latency_timeline, fig_resources, fig_init, fig_open_loop):
        f(d, out)
        print("wrote", f.__name__)


if __name__ == "__main__":
    main()
