# Data

The benchmark uses Autoware's sample map and sample rosbag, the data of the Autoware [rosbag replay simulation](https://autowarefoundation.github.io/autoware-documentation/main/simulation/rosbag-replay-simulation/). The release `data-v1` of this repository has the files, and `scripts/download_data.sh` downloads and checks them.

## Files

| File | Size | Content |
| --- | --- | --- |
| `benchmark-inputs-v1.tar.gz` | 13.7 MB | The recorded inputs of the benchmark and the sample map in 20 m tiles |
| `sample-map-rosbag.zip` | 3.1 MB | Autoware's sample map: point cloud map (326867 points), lanelet2 map, map projection |
| `sample-rosbag.zip` | 202 MB | Autoware's sample rosbag: 30 s of raw Velodyne packets (3 lidars), IMU, GNSS and vehicle status |

`sample-map-rosbag.zip` and `sample-rosbag.zip` are copies of the files that Autoware's [demo_artifacts](https://github.com/autowarefoundation/autoware/tree/main/ansible/roles/demo_artifacts) Ansible role downloads from `autoware-files.s3.us-west-2.amazonaws.com`. They have the same SHA-256 checksums. `scripts/download_data.sh --from-autoware` downloads them from Autoware's server instead of this repository.

The SHA-256 checksums are in `config/data.sha256`:

```text
b99227646280d1d7dc336ffce91a0db8e0c22b28839f65f4ff9d6bb9d6a992e9  benchmark-inputs-v1.tar.gz
07e2da0b0bf12e2324f7083c2ce5556fb8044c50cef1da6428ab9084c3903bc8  sample-map-rosbag.zip
5f9d36353393b3d249212153c19049822b1298db56512aa045b4f7f6fc37cf88  sample-rosbag.zip
```

## The benchmark inputs

The sample rosbag has only raw sensor data. The scan matcher needs the downsampled scan, and the EKF needs the twist from `gyro_odometer`. Autoware nodes compute these from the raw data, so one full Autoware replay made them once (`scripts/make_inputs.sh`). None of them depends on the scan matcher, so every option gets the same inputs.

| Path in `data/` | Content | Messages |
| --- | --- | --- |
| `inputs/bag` | `/localization/util/downsample/pointcloud` (downsampled scan, about 750 points, frame `base_link`) | 299 |
| | `/localization/twist_estimator/twist_with_covariance` (twist from `gyro_odometer`) | 831 |
| | `/sensing/gnss/pose_with_covariance` (GNSS pose for the initial pose search) | 30 |
| | `/localization/pose_estimator/pose_with_covariance` (poses of Autoware NDT in that replay, not replayed) | 239 |
| `inputs_open/bag` | The downsampled scans, and the EKF poses (`biased_pose_with_covariance`) of one closed-loop run of Autoware NDT, as the initial guesses of the open-loop test | 299 and 1457 |
| `maps/sample-map-rosbag` | The sample map as one file (from `sample-map-rosbag.zip`) | |
| `maps/sample-map-rosbag-tiled` | The same points in 279 tiles of 20 m, with `pointcloud_map_metadata.yaml` (`harness/split_map.py`) | |

The receive time of every message in the input bags is in the time of the original bag, so the bags replay with `ros2 bag play --clock` and need no other clock. Downsampled scans arrive about 200 ms after their header time stamp, which is the delay of Autoware's sensing pipeline in that replay.

## License

The repository has no license statement for Autoware's sample data. The files here are unchanged copies of Autoware's published files, and the inputs are derived from them. If you are the owner of the data and want a change, open an issue.
