#!/usr/bin/env python3
"""Drives one benchmark run and records what the scan matcher produces, with wall-clock receive times.

The input bag player must run with --start-paused and --clock. Steps:
  1. Step the player (play_next) until the GNSS pose and a scan arrived, so the pose initializer and NDT have inputs.
  2. Call /localization/initialize (GNSS, as Autoware's pose_initialization_requester does) and time it. This runs
     NDT's initial pose search (ndt_align_srv) and then initializes the EKF and activates NDT.
  3. Resume the player and record the outputs until the input bag ends.

usage: driver.py <out.json> [--max-seconds N] [--open-loop]

--open-loop: the graph has no EKF and no pose initializer. The bag also plays the recorded EKF poses (NDT's initial
guesses). The driver activates NDT with its trigger_node service and replays the bag, without an initial pose search.
"""

import json
import math
import sys
import time

import rclpy
from autoware_internal_debug_msgs.msg import Float32Stamped, Int32Stamped
from autoware_localization_msgs.srv import InitializeLocalization
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data, QoSProfile
from rosbag2_interfaces.srv import PlayNext, Resume
from std_srvs.srv import SetBool
from diagnostic_msgs.msg import DiagnosticArray
from sensor_msgs.msg import PointCloud2

NS = "/localization/pose_estimator"


def stamp_ns(s):
    return s.sec * 10**9 + s.nanosec


class Driver(Node):
    def __init__(self):
        super().__init__("ndt_bench_driver")
        self.data = {"scans": [], "poses": [], "exe": [], "iter": [], "tp": [], "nvtl": [], "gnss": 0, "map_updates": [], "ekf_biased": []}
        qos = QoSProfile(depth=100)
        self.create_subscription(PointCloud2, "/localization/util/downsample/pointcloud",
                                 lambda m: self.data["scans"].append((time.time(), stamp_ns(m.header.stamp))), qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, "/sensing/gnss/pose_with_covariance",
                                 lambda m: self.data.__setitem__("gnss", self.data["gnss"] + 1), qos_profile_sensor_data)
        self.create_subscription(PoseWithCovarianceStamped, f"{NS}/pose_with_covariance", self.on_pose, qos)
        self.create_subscription(Float32Stamped, f"{NS}/exe_time_ms", lambda m: self.value("exe", m), qos)
        self.create_subscription(Int32Stamped, f"{NS}/iteration_num", lambda m: self.value("iter", m), qos)
        self.create_subscription(Float32Stamped, f"{NS}/transform_probability", lambda m: self.value("tp", m), qos)
        self.create_subscription(Float32Stamped, f"{NS}/nearest_voxel_transformation_likelihood", lambda m: self.value("nvtl", m), qos)
        self.create_subscription(DiagnosticArray, "/diagnostics", self.on_diagnostics, qos)
        self.create_subscription(PoseWithCovarianceStamped, "/localization/pose_twist_fusion_filter/biased_pose_with_covariance",
                                 self.on_ekf, QoSProfile(depth=1000))
        self.play_next = self.create_client(PlayNext, "/rosbag2_player/play_next")
        self.resume = self.create_client(Resume, "/rosbag2_player/resume")
        self.initialize = self.create_client(InitializeLocalization, "/localization/initialize")
        self.trigger = self.create_client(SetBool, "/localization/pose_estimator/trigger_node")

    def on_ekf(self, m):
        p, q = m.pose.pose.position, m.pose.pose.orientation
        self.data["ekf_biased"].append((stamp_ns(m.header.stamp), m.header.frame_id, p.x, p.y, p.z, q.x, q.y, q.z, q.w,
                                        list(m.pose.covariance)))

    def on_diagnostics(self, m):
        # NDT's map_update_status: one entry per map update that changed the loaded tiles
        for st in m.status:
            if not st.name.endswith("map_update_status"):
                continue
            kv = {v.key: v.value for v in st.values}
            if kv.get("is_updated_map", "").lower() == "true":
                self.data["map_updates"].append((time.time(), float(kv.get("map_update_execution_time", "nan")),
                                                 int(float(kv.get("maps_size_after", "-1"))), int(float(kv.get("maps_to_add_size", "-1")))))

    def value(self, key, m):
        self.data[key].append((time.time(), stamp_ns(m.stamp), float(m.data)))

    def on_pose(self, m):
        p = m.pose.pose
        q = p.orientation
        yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
        # t, stamp, x, y, z, yaw, qx, qy, qz, qw
        self.data["poses"].append((time.time(), stamp_ns(m.header.stamp), p.position.x, p.position.y, p.position.z, yaw, q.x, q.y, q.z, q.w))

    def call(self, client, request, timeout):
        future = client.call_async(request)
        rclpy.spin_until_future_complete(self, future, timeout_sec=timeout)
        return future.result()


def closed_loop_init(node, result):
    """Steps the player until GNSS and a scan arrived, then times /localization/initialize (initial pose search)."""
    from autoware_internal_localization_msgs.srv import PoseWithCovarianceStamped as AlignSrv
    from autoware_map_msgs.srv import GetDifferentialPointCloudMap, GetPartialPointCloudMap
    # The initializer, NDT's align service and the map loader's services must all exist before initializing.
    extra = [node.create_client(AlignSrv, "/localization/pose_estimator/ndt_align_srv"),
             node.create_client(GetDifferentialPointCloudMap, "/map/get_differential_pointcloud_map"),
             node.create_client(GetPartialPointCloudMap, "/map/get_partial_pointcloud_map")]
    for client in [node.play_next, node.resume, node.initialize] + extra:
        if not client.wait_for_service(timeout_sec=60.0):
            raise RuntimeError(f"service {client.srv_name} not available")

    steps = 0
    while (node.data["gnss"] == 0 or not node.data["scans"]) and steps < 2000:
        node.call(node.play_next, PlayNext.Request(), 5.0)
        rclpy.spin_once(node, timeout_sec=0.0)
        steps += 1
    for _ in range(20):
        rclpy.spin_once(node, timeout_sec=0.01)
    result["play_next_steps"] = steps

    # Retry if a node was not ready yet (a failure that returns quickly). Only the successful call is timed.
    for attempt in range(5):
        t0 = time.time()
        response = node.call(node.initialize, InitializeLocalization.Request(), 120.0)
        t1 = time.time()
        if response and response.status.success:
            break
        time.sleep(0.5)
    result["init_attempts"] = attempt + 1
    result["init"] = {"t0": t0, "t1": t1, "seconds": t1 - t0, "success": bool(response and response.status.success),
                      "message": response.status.message if response else "timeout"}
    if not result["init"]["success"]:
        raise RuntimeError(f"initialization failed: {result['init']['message']}")


def open_loop_start(node, result):
    """Activates NDT directly: the bag plays the recorded EKF poses, so no initialization is needed."""
    from autoware_map_msgs.srv import GetDifferentialPointCloudMap
    loader = node.create_client(GetDifferentialPointCloudMap, "/map/get_differential_pointcloud_map")
    for client in (node.resume, node.trigger, loader):
        if not client.wait_for_service(timeout_sec=60.0):
            raise RuntimeError(f"service {client.srv_name} not available")
    response = node.call(node.trigger, SetBool.Request(data=True), 10.0)
    if not (response and response.success):
        raise RuntimeError("trigger_node failed")
    result["init"] = None


def main():
    out = sys.argv[1]
    max_seconds = float(sys.argv[sys.argv.index("--max-seconds") + 1]) if "--max-seconds" in sys.argv else 60.0
    open_loop = "--open-loop" in sys.argv
    rclpy.init()
    node = Driver()
    result = {"ok": False, "open_loop": open_loop}
    try:
        if open_loop:
            open_loop_start(node, result)
        else:
            closed_loop_init(node, result)

        # Tracking: resume the player and record until no scan arrived for 0.5 s
        node.call(node.resume, Resume.Request(), 5.0)
        result["resume"] = time.time()
        last_scan = time.time()
        n = len(node.data["scans"])
        while time.time() - result["resume"] < max_seconds:
            rclpy.spin_once(node, timeout_sec=0.05)
            if len(node.data["scans"]) != n:
                n = len(node.data["scans"])
                last_scan = time.time()
            elif time.time() - last_scan > 0.5:
                break
        t_end = time.time()  # outputs of the last scans
        while time.time() - t_end < 0.3:
            rclpy.spin_once(node, timeout_sec=0.05)
        result["end"] = time.time()
        result["ok"] = True
    except Exception as e:  # report and still save what was received
        result["error"] = str(e)
    result.update(node.data)
    with open(out, "w") as f:
        json.dump(result, f)
    node.destroy_node()
    rclpy.shutdown()
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
