#!/usr/bin/env python3
"""Metrics of benchmark runs (driver.json + resources.csv + optional gpu.json).

usage: analyze.py <out.json> <reference_run_dir> <run_dir> [run_dir ...]
"""

import csv
import json
import math
import os
import sys

import numpy as np


def rotation_deg(q1, q2):
    """Angle of the rotation between two quaternions (x, y, z, w). Robust for small angles: 2 atan2(|v|, |w|) of the
    relative quaternion, after normalization (acos of the dot product loses precision near 1)."""
    def norm(q):
        n = math.sqrt(sum(c * c for c in q))
        return [c / n for c in q]
    x1, y1, z1, w1 = norm(q1)
    x2, y2, z2, w2 = norm(q2)
    # q_rel = conj(q2) * q1
    w = w2 * w1 + x2 * x1 + y2 * y1 + z2 * z1
    x = w2 * x1 - x2 * w1 - y2 * z1 + z2 * y1
    y = w2 * y1 + x2 * z1 - y2 * w1 - z2 * x1
    z = w2 * z1 - x2 * y1 + y2 * x1 - z2 * w1
    return math.degrees(2.0 * math.atan2(math.sqrt(x * x + y * y + z * z), abs(w)))


def pct(v, q):
    return float(np.percentile(v, q)) if len(v) else float("nan")


def load_resources(run):
    rows = []
    with open(os.path.join(run, "resources.csv")) as f:
        for r in csv.DictReader(f):
            rows.append({k: float(v) for k, v in r.items()})
    return rows


def window(rows, t0, t1):
    """Use of the scan matcher between wall times t0 and t1 (s), interpolating the cumulative CPU time."""
    ts = np.array([r["t"] for r in rows])
    cpu = np.array([r["proc_cpu_s"] for r in rows])
    busy = np.array([r["machine_busy_s"] for r in rows])
    inside = [r for r in rows if t0 <= r["t"] <= t1]
    c0, c1 = np.interp([t0, t1], ts, cpu)
    b0, b1 = np.interp([t0, t1], ts, busy)
    out = {"seconds": t1 - t0, "cpu_s": float(c1 - c0), "cpu_cores": float((c1 - c0) / (t1 - t0)),
           "machine_cores": float((b1 - b0) / (t1 - t0))}
    if len(inside) >= 2:
        rates = [(y["proc_cpu_s"] - x["proc_cpu_s"]) / (y["t"] - x["t"]) for x, y in zip(inside, inside[1:])]
        out["cpu_cores_peak"] = max(rates)
        out["gpu_power_w_mean"] = float(np.mean([r["gpu_power_w"] for r in inside]))
    return out


def analyze(run, reference):
    d = json.load(open(os.path.join(run, "driver.json")))
    info = open(os.path.join(run, "info.txt")).read()
    rate = float(info.split("rate=")[1].split()[0])
    res = {"run": run, "variant": run.rstrip("/").split("/")[-2], "rate": rate, "ok": d.get("ok", False),
           "map": info.split("map=")[1].split()[0] if "map=" in info else "single"}
    if not d.get("ok"):
        res["error"] = d.get("error")
        return res
    rows = load_resources(run)
    t_resume, t_end = d["resume"], d["end"]

    scans = {s: t for t, s in d["scans"]}
    tracked_scans = [t for t, s in d["scans"] if t >= t_resume]
    poses = [p for p in d["poses"] if p[0] >= t_resume]
    lat = [(t - scans[s]) * 1000.0 for t, s, *_ in poses if s in scans]
    exe = [v for t, _, v in d["exe"] if t >= t_resume]
    it = [v for t, _, v in d["iter"] if t >= t_resume]
    tp = [v for t, _, v in d["tp"] if t >= t_resume]
    nvtl = [v for t, _, v in d["nvtl"] if t >= t_resume]

    res["open_loop"] = bool(d.get("open_loop"))
    if d.get("init"):
        res["init"] = {"seconds": d["init"]["seconds"], **window(rows, d["init"]["t0"], d["init"]["t1"])}
    track = window(rows, t_resume, t_end)
    res["tracking"] = {
        "scans": len(tracked_scans), "poses": len(poses), "outputs": len(exe),
        "latency_ms_median": pct(lat, 50), "latency_ms_p95": pct(lat, 95), "latency_ms_p99": pct(lat, 99),
        "latency_ms_max": max(lat) if lat else float("nan"),
        "exe_ms_median": pct(exe, 50), "exe_ms_p95": pct(exe, 95), "exe_ms_max": max(exe) if exe else float("nan"),
        "iterations_mean": float(np.mean(it)) if it else float("nan"),
        "tp_median": pct(tp, 50), "nvtl_median": pct(nvtl, 50), "nvtl_min": min(nvtl) if nvtl else float("nan"),
        # CPU time of the scan matcher per scan it answered, and the CPU it would need at 10 Hz in real time
        "cpu_ms_per_scan": 1000.0 * track["cpu_s"] / max(1, len(exe)),
        **{k: v for k, v in track.items()},
    }
    res["tracking"]["cpu_cores_at_10hz"] = res["tracking"]["cpu_ms_per_scan"] * 10 / 1000.0
    # Map updates during tracking, and the latency of the first scan answered after each one
    events = d.get("map_updates", [])
    if not events and os.path.exists(os.path.join(run, "launch.log")):
        # cuda_ndt_matcher does not fill Autoware's map_update_status diagnostics. Its log has a line per update
        # ("Map update: +N tiles (...), -M tiles, took X ms") with a wall-clock time stamp.
        import re
        pattern = re.compile(r"\[(?:INFO|WARN) (\d+\.\d+)\] \[[^\]]*map_module\]: Map update: \+(\d+) tiles .*took ([0-9.]+)ms")
        for line in open(os.path.join(run, "launch.log"), errors="replace"):
            m = pattern.search(line)
            if m:
                events.append((float(m.group(1)), float(m.group(3)), -1, int(m.group(2))))
    ups = [u for u in events if t_resume <= u[0] <= t_end]
    pose_times = sorted((t, (t - scans[s]) * 1000.0) for t, s, *_ in poses if s in scans)
    after = []
    for u in ups:
        nxt = next((l for t, l in pose_times if t >= u[0]), None)
        if nxt is not None:
            after.append(nxt)
    res["map_updates"] = {"count": len(ups), "exec_ms_median": pct([u[1] for u in ups], 50),
                          "tiles_added_total": sum(max(0, u[3]) for u in ups),
                          "latency_after_update_ms_max": max(after) if after else float("nan"),
                          "latency_after_update_ms_median": pct(after, 50)}
    res["memory"] = {"rss_mib_max": max(r["proc_rss_mib"] for r in rows), "vram_mib_max": max(r["proc_vram_mib"] for r in rows),
                     "threads_max": max(r["proc_threads"] for r in rows)}

    gpu = os.path.join(run, "gpu.json")
    if os.path.exists(gpu):
        res["gpu"] = json.load(open(gpu))

    if reference and os.path.abspath(reference) != os.path.abspath(run):
        rd = json.load(open(os.path.join(reference, "driver.json")))
        ref = {p[1]: p for p in rd["poses"]}
        dp, dyaw, drot = [], [], []
        for p in poses:
            r = ref.get(p[1])
            if r is None:
                continue
            dp.append(1000.0 * math.dist(p[2:5], r[2:5]))
            dyaw.append(abs(math.degrees(math.atan2(math.sin(p[5] - r[5]), math.cos(p[5] - r[5])))))
            if len(p) >= 10 and len(r) >= 10:
                drot.append(rotation_deg(p[6:10], r[6:10]))
        # Autoware's NDT keeps the pose as a float matrix in map coordinates: x and y can only differ in float32
        # steps (7.8 mm at x = 89571 m, 3.9 mm at y = 42301 m). z is near 0, so its difference shows the alignment itself.
        xy_same, dz = 0, []
        for p in poses:
            r = ref.get(p[1])
            if r is None:
                continue
            xy_same += int(np.float32(p[2]) == np.float32(r[2]) and np.float32(p[3]) == np.float32(r[3]))
            dz.append(1e6 * abs(p[4] - r[4]))
        res["vs_reference"] = {"xy_same_float_share": xy_same / len(dz) if dz else float("nan"),
                               "z_um_median": pct(dz, 50), "z_um_p95": pct(dz, 95), "z_um_max": max(dz) if dz else float("nan"),
                               "matched": len(dp), "mm_median": pct(dp, 50), "mm_p95": pct(dp, 95),
                               "mm_max": max(dp) if dp else float("nan"), "yaw_deg_max": max(dyaw) if dyaw else float("nan"),
                               "um_median": pct(dp, 50) * 1000.0, "um_p95": pct(dp, 95) * 1000.0,
                               "um_max": (max(dp) * 1000.0) if dp else float("nan"),
                               "rot_deg_median": pct(drot, 50), "rot_deg_max": max(drot) if drot else float("nan"),
                               "rot_deg_p95": pct(drot, 95)}
        # Same initial guess (open loop): compare the iteration counts and the scores scan by scan
        if res["open_loop"]:
            def by_stamp(key, data):
                return {s_: v for _, s_, v in data[key]}
            it_mine = {s_: v for _, s_, v in d["iter"]}
            it_ref = {s_: v for _, s_, v in rd["iter"]}
            same, other = [], []
            for p in poses:
                r = ref.get(p[1])
                if r is None or p[1] not in it_mine or p[1] not in it_ref:
                    continue
                (same if it_mine[p[1]] == it_ref[p[1]] else other).append(1e6 * math.dist(p[2:5], r[2:5]))
            res["vs_reference"].update({
                "same_iter_scans": len(same), "same_iter_um_median": pct(same, 50), "same_iter_um_p95": pct(same, 95),
                "same_iter_um_max": max(same) if same else float("nan"),
                "diff_iter_scans": len(other), "diff_iter_um_median": pct(other, 50), "diff_iter_um_max": max(other) if other else float("nan")})
            for key in ("iter", "tp", "nvtl"):
                mine, theirs = by_stamp(key, d), by_stamp(key, rd)
                common = [s_ for s_ in mine if s_ in theirs]
                diffs = [abs(mine[s_] - theirs[s_]) for s_ in common]
                if key == "iter":
                    res["vs_reference"]["iterations_equal_share"] = (sum(1 for x in diffs if x == 0) / len(diffs)) if diffs else float("nan")
                else:
                    res["vs_reference"][f"{key}_absdiff_median"] = pct(diffs, 50)
                    res["vs_reference"][f"{key}_absdiff_max"] = max(diffs) if diffs else float("nan")
    return res


def main():
    out, reference, runs = sys.argv[1], sys.argv[2], sys.argv[3:]
    results = []
    for run in runs:
        try:
            results.append(analyze(run, reference))
        except Exception as e:
            results.append({"run": run, "ok": False, "error": repr(e)})
    json.dump(results, open(out, "w"), indent=1)


if __name__ == "__main__":
    main()
