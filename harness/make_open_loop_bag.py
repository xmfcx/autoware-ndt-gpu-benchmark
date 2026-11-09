#!/usr/bin/env python3
"""Writes the input bag of the open-loop test, statically (no replay).

usage: make_open_loop_bag.py <inputs_bag> <reference_run_dir> <output_bag>

The output has the downsampled scans of <inputs_bag> (same messages, same receive times) and the EKF poses
(/localization/pose_twist_fusion_filter/biased_pose_with_covariance) that <reference_run_dir>/driver.json recorded in a
closed-loop run. NDT uses these poses as its initial guesses. Their receive time is their header stamp: the EKF
publishes each pose at the time in its stamp.
"""

import json
import sys

import rosbag2_py
from geometry_msgs.msg import PoseWithCovarianceStamped
from rclpy.serialization import serialize_message

SCAN = "/localization/util/downsample/pointcloud"
EKF = "/localization/pose_twist_fusion_filter/biased_pose_with_covariance"


def main():
    inputs, reference, output = sys.argv[1:4]
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=inputs, storage_id="mcap"), rosbag2_py.ConverterOptions("cdr", "cdr"))
    topics = {t.name: t for t in reader.get_all_topics_and_types()}
    records = []
    while reader.has_next():
        topic, raw, t = reader.read_next()
        if topic == SCAN:
            records.append((t, SCAN, raw))

    for stamp, frame, x, y, z, qx, qy, qz, qw, cov in json.load(open(f"{reference}/driver.json"))["ekf_biased"]:
        m = PoseWithCovarianceStamped()
        m.header.stamp.sec, m.header.stamp.nanosec = divmod(stamp, 10**9)
        m.header.frame_id = frame
        p, q = m.pose.pose.position, m.pose.pose.orientation
        p.x, p.y, p.z, q.x, q.y, q.z, q.w = x, y, z, qx, qy, qz, qw
        m.pose.covariance = cov
        records.append((stamp, EKF, serialize_message(m)))
    records.sort(key=lambda r: r[0])

    writer = rosbag2_py.SequentialWriter()
    writer.open(rosbag2_py.StorageOptions(uri=output, storage_id="mcap"), rosbag2_py.ConverterOptions("cdr", "cdr"))
    writer.create_topic(topics[SCAN])
    writer.create_topic(rosbag2_py.TopicMetadata(id=0, name=EKF, type="geometry_msgs/msg/PoseWithCovarianceStamped",
                                                 serialization_format="cdr"))
    for t, topic, raw in records:
        writer.write(topic, raw, t)
    del writer
    print(f"{sum(1 for r in records if r[1] == SCAN)} scans, {sum(1 for r in records if r[1] == EKF)} EKF poses")


if __name__ == "__main__":
    main()
