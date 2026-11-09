#!/usr/bin/env python3
"""Splits a binary PCD map into square tiles for Autoware's dynamic map loading, with pointcloud_map_metadata.yaml.

usage: split_map.py <input.pcd> <output_map_dir> [tile_size_m]
Writes <output_map_dir>/pointcloud_map/<x>_<y>.pcd and <output_map_dir>/pointcloud_map_metadata.yaml.
"""

import math
import os
import sys

import numpy as np


def read_pcd(path):
    with open(path, "rb") as f:
        header = {}
        while True:
            line = f.readline().decode("ascii").strip()
            if line.startswith("#"):
                continue
            key, *values = line.split()
            header[key] = values
            if key == "DATA":
                break
        if header["DATA"][0] != "binary":
            raise ValueError("only binary PCD is supported")
        fields, sizes, types, counts = header["FIELDS"], header["SIZE"], header["TYPE"], header["COUNT"]
        dtype = []
        for name, size, typ, count in zip(fields, sizes, types, counts):
            kind = {"F": "f", "U": "u", "I": "i"}[typ]
            name = name if name != "_" else f"pad{len(dtype)}"
            dtype.append((name, f"<{kind}{size}", (int(count),)) if int(count) > 1 else (name, f"<{kind}{size}"))
        n = int(header["POINTS"][0])
        data = np.frombuffer(f.read(), dtype=np.dtype(dtype), count=n)
    return np.stack([data["x"], data["y"], data["z"]], axis=1).astype(np.float32)


def write_pcd(path, xyz):
    header = (
        "# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS x y z\nSIZE 4 4 4\nTYPE F F F\nCOUNT 1 1 1\n"
        f"WIDTH {len(xyz)}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {len(xyz)}\nDATA binary\n"
    )
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(np.ascontiguousarray(xyz, dtype="<f4").tobytes())


def main():
    src, out = sys.argv[1], sys.argv[2]
    size = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0
    xyz = read_pcd(src)
    tiles_dir = os.path.join(out, "pointcloud_map")
    os.makedirs(tiles_dir, exist_ok=True)
    ix = np.floor(xyz[:, 0] / size).astype(np.int64)
    iy = np.floor(xyz[:, 1] / size).astype(np.int64)
    keys = ix * 1_000_003 + iy
    order = np.argsort(keys, kind="stable")
    keys, ix, iy, xyz = keys[order], ix[order], iy[order], xyz[order]
    starts = np.flatnonzero(np.r_[True, keys[1:] != keys[:-1]])
    ends = np.r_[starts[1:], len(keys)]
    lines = [f"x_resolution: {size}", f"y_resolution: {size}"]
    for s, e in zip(starts, ends):
        x0, y0 = int(ix[s] * size), int(iy[s] * size)
        name = f"{x0}_{y0}.pcd"
        write_pcd(os.path.join(tiles_dir, name), xyz[s:e])
        lines.append(f"{name}: [{x0}, {y0}]")
    with open(os.path.join(out, "pointcloud_map_metadata.yaml"), "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{len(xyz)} points, {len(starts)} tiles of {size} m")


if __name__ == "__main__":
    main()
