#!/usr/bin/env python3
"""GPU time of one process from an Nsight Systems trace.

usage: gpu_trace.py <run_dir>   (reads <run_dir>/gpu_trace.nsys-rep and the ndt_pid in info.txt)

Writes <run_dir>/gpu.json with the busy time of the GPU for the process (union of its kernel, memcpy and memset
intervals, so overlapping work on several streams counts once), the kernel count and the trace length.
"""

import json
import os
import sqlite3
import subprocess
import sys


def union_length(intervals):
    total, end = 0, None
    start = None
    for s, e in sorted(intervals):
        if end is None or s > end:
            if end is not None:
                total += end - start
            start, end = s, e
        else:
            end = max(end, e)
    if end is not None:
        total += end - start
    return total


def main():
    run = sys.argv[1]
    rep = os.path.join(run, "gpu_trace.nsys-rep")
    db = os.path.join(run, "gpu_trace.sqlite")
    if not os.path.exists(db):
        subprocess.run(["nsys", "export", "--type=sqlite", "--force-overwrite=true", "-o", db, rep], check=True, capture_output=True)
    pid = None
    for line in open(os.path.join(run, "info.txt")):
        if line.startswith("ndt_pid="):
            pid = int(line.split("=")[1])
    con = sqlite3.connect(db)
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    intervals, kernels, copies = [], 0, 0
    per_pid = {}
    t_min, t_max = None, None
    for table in ("CUPTI_ACTIVITY_KIND_KERNEL", "CUPTI_ACTIVITY_KIND_MEMCPY", "CUPTI_ACTIVITY_KIND_MEMSET"):
        if table not in tables:
            continue
        for start, end, gpid in con.execute(f"select start, end, globalPid from {table}"):
            p = (gpid >> 24) & 0xFFFFFF
            per_pid.setdefault(p, []).append((start, end))
            t_min = start if t_min is None else min(t_min, start)
            t_max = end if t_max is None else max(t_max, end)
            if p == pid:
                intervals.append((start, end))
                if table == "CUPTI_ACTIVITY_KIND_KERNEL":
                    kernels += 1
                else:
                    copies += 1
    # trace length: the collection window (nsys start/stop around the replay)
    length_ns = None
    if "ANALYSIS_DETAILS" in tables:
        row = con.execute("select duration from ANALYSIS_DETAILS").fetchone()
        length_ns = row[0] if row else None
    busy = union_length(intervals)
    # Trace times are ns since the session start. Split the busy time into the driver's windows (wall clock).
    session_start = con.execute("select utcEpochNs from TARGET_INFO_SESSION_START_TIME").fetchone()[0]
    windows = {}
    driver = os.path.join(run, "driver.json")
    if os.path.exists(driver):
        d = json.load(open(driver))
        if d.get("ok"):
            for name, (w0, w1) in {"init": (d["init"]["t0"], d["init"]["t1"]), "tracking": (d["resume"], d["end"])}.items():
                a, b = int(w0 * 1e9) - session_start, int(w1 * 1e9) - session_start
                clipped = [(max(s0, a), min(e0, b)) for s0, e0 in intervals if e0 > a and s0 < b]
                windows[name] = {"busy_ms": union_length(clipped) / 1e6, "window_s": w1 - w0}
    out = {
        "ndt_pid": pid,
        "busy_ms": busy / 1e6,
        "windows": windows,
        "kernels": kernels,
        "copies_and_memsets": copies,
        "trace_s": (length_ns / 1e9) if length_ns else None,
        "other_pids_busy_ms": {str(p): union_length(iv) / 1e6 for p, iv in per_pid.items() if p != pid},
    }
    with open(os.path.join(run, "gpu.json"), "w") as f:
        json.dump(out, f, indent=1)
    print(json.dumps(out))


if __name__ == "__main__":
    main()
