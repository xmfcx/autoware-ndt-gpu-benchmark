#!/usr/bin/env python3
"""Samples the resource use of one process (all its threads) and of the machine until stopped.

usage: sampler.py <pid> <output.csv> [period_seconds]

Columns:
  t                wall clock time (s)
  proc_cpu_s       CPU time used by the process so far (user + system, all threads), seconds
  proc_rss_mib     resident memory of the process
  proc_threads     number of threads
  proc_vram_mib    video memory used by the process (nvidia-smi), 0 if none
  machine_busy_s   busy CPU time of the whole machine so far, seconds (all cores)
  gpu_util         whole-GPU utilization percent (nvidia-smi, coarse)
  gpu_power_w      board power draw (W)
"""

import csv
import os
import signal
import subprocess
import sys
import time

TICKS = os.sysconf("SC_CLK_TCK")
PAGE = os.sysconf("SC_PAGE_SIZE")


def proc_stat(pid):
    with open(f"/proc/{pid}/stat") as f:
        fields = f.read().rsplit(")", 1)[1].split()
    cpu = (int(fields[11]) + int(fields[12])) / TICKS
    rss = int(fields[21]) * PAGE / 2**20
    threads = int(fields[17])
    return cpu, rss, threads


def machine_busy():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:9]]
    return (sum(v) - v[3] - v[4]) / TICKS


def gpu_query(pid):
    out = subprocess.run(
        ["nvidia-smi", "--query-gpu=utilization.gpu,power.draw", "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout.strip().splitlines()[0]
    util, power = [float(x) for x in out.split(",")]
    apps = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
        capture_output=True, text=True).stdout
    vram = 0.0
    for line in apps.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0] == str(pid):
            vram = float(parts[1])
    return util, power, vram


def main():
    pid = int(sys.argv[1])
    out = sys.argv[2]
    period = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
    running = [True]
    signal.signal(signal.SIGTERM, lambda *_: running.clear())
    signal.signal(signal.SIGINT, lambda *_: running.clear())
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t", "proc_cpu_s", "proc_rss_mib", "proc_threads", "proc_vram_mib", "machine_busy_s", "gpu_util", "gpu_power_w"])
        while running and os.path.exists(f"/proc/{pid}"):
            t = time.time()
            try:
                cpu, rss, threads = proc_stat(pid)
            except OSError:
                break
            util, power, vram = gpu_query(pid)
            w.writerow([f"{t:.3f}", f"{cpu:.3f}", f"{rss:.1f}", threads, f"{vram:.0f}", f"{machine_busy():.2f}", f"{util:.0f}", f"{power:.1f}"])
            f.flush()
            time.sleep(max(0.0, period - (time.time() - t)))


if __name__ == "__main__":
    main()
