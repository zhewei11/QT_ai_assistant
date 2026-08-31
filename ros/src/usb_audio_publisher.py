#!/usr/bin/env python3
"""Publish ALSA microphone audio as audio_common_msgs/AudioData.

This is intended for USB microphones on QTrobot. It captures raw mono
S16_LE PCM with arecord and publishes chunks that the Riva ASR node can
subscribe to.
"""

import subprocess
import threading

import rospy
from audio_common_msgs.msg import AudioData


def main():
    rospy.init_node("usb_audio_publisher", anonymous=False)

    device = rospy.get_param("~device", "plughw:1,0")
    audio_topic = rospy.get_param("~audio_topic", "/qt_ai_assistant/external_mic_audio")
    sample_rate = int(rospy.get_param("~sample_rate", 16000))
    channels = int(rospy.get_param("~channels", 1))
    chunk_samples = int(rospy.get_param("~chunk_samples", 512))
    sample_width_bytes = 2
    chunk_bytes = max(1, chunk_samples * channels * sample_width_bytes)

    publisher = rospy.Publisher(audio_topic, AudioData, queue_size=20)
    command = [
        "arecord",
        "-D",
        device,
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        str(channels),
        "-t",
        "raw",
    ]

    rospy.loginfo(
        "[USB Mic] device=%s topic=%s sample_rate=%s channels=%s chunk_samples=%s",
        device,
        audio_topic,
        sample_rate,
        channels,
        chunk_samples,
    )

    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )

    def log_stderr():
        while not rospy.is_shutdown() and process.poll() is None:
            line = process.stderr.readline()
            if line:
                rospy.logwarn("[USB Mic] %s", line.decode("utf-8", errors="replace").strip())

    threading.Thread(target=log_stderr, name="usb_audio_stderr", daemon=True).start()

    pending = bytearray()

    try:
        while not rospy.is_shutdown() and process.poll() is None:
            data = process.stdout.read(chunk_bytes)
            if not data:
                break
            pending.extend(data)
            while len(pending) >= chunk_bytes:
                chunk = bytes(pending[:chunk_bytes])
                del pending[:chunk_bytes]
                publisher.publish(AudioData(data=chunk))
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        rospy.loginfo("[USB Mic] stopped.")


if __name__ == "__main__":
    main()
