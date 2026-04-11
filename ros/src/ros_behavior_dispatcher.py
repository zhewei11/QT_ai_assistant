#!/usr/bin/env python3
# Copyright (c) 2024 LuxAI S.A.
# 
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

import rospy
import zmq
import json
import math
from std_msgs.msg import String

# Implemented robust imports assuming qt_robot_interface is available in the workspace
try:
    from qt_robot_interface.srv import behavior_talk_text, speech_config, emotion_show, setting_setVolume, gesture_play
except ImportError:
    rospy.logwarn("qt_robot_interface not found. Mocking the proxy services for development.")
    behavior_talk_text = None
    speech_config = None
    emotion_show = None
    setting_setVolume = None
    gesture_play = None

class ROSBehaviorDispatcher:
    def __init__(self, zmq_port="tcp://*:5556"):
        # Create Publishers/Services Proxies mapping to real robot actuators
        rospy.loginfo("Initializing ROS Proxies...")
        
        self.talkText = rospy.ServiceProxy('/qt_robot/behavior/talkText', behavior_talk_text) if behavior_talk_text else lambda x: rospy.loginfo(f"[MOCK] Talking: {x}")
        self.speechConfig = rospy.ServiceProxy('/qt_robot/speech/config', speech_config) if speech_config else lambda l, p, s: rospy.loginfo(f"[MOCK] Lang: {l}")
        self.emotionShow = rospy.ServiceProxy('/qt_robot/emotion/show', emotion_show) if emotion_show else lambda e: rospy.loginfo(f"[MOCK] Emotion: {e}")
        self.settingVolume = rospy.ServiceProxy('/qt_robot/setting/setVolume', setting_setVolume) if setting_setVolume else lambda v: rospy.loginfo(f"[MOCK] Volume: {v}")
        self.gesturePlay = rospy.ServiceProxy('/qt_robot/gesture/play', gesture_play) if gesture_play else lambda n, s: rospy.loginfo(f"[MOCK] Gesture: {n} speed: {s}")

        # Publisher to notify Riva of language changes
        self.lang_pub = rospy.Publisher('/qt_ai_assistant/language_config', String, queue_size=10)

        # ZeroMQ PULL Socket Configuration
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PULL)
        self.socket.bind(zmq_port)
        self.ecg_process = None  
        rospy.loginfo(f"ROSBehaviorDispatcher listening on {zmq_port} ... awaiting AI AI_Assistant instructions.")

    def spin(self):
        while not rospy.is_shutdown():
            try:
                # Wait for messages from Python 3.11 LangGraph (non-blocking)
                message = self.socket.recv_string(flags=zmq.NOBLOCK)
                try:
                    payload = json.loads(message)
                    self.dispatch(payload)
                except json.JSONDecodeError:
                    rospy.logerr(f"Received invalid JSON: {message}")
            except zmq.Again:
                rospy.sleep(0.05) # Sleep briefly if no message is present in queue
            except Exception as e:
                rospy.logerr(f"ZMQ Error: {e}")
                
    def dispatch(self, payload):
        """
        Parses incoming payload and dispatches to appropriate ROS node.
        Example Payload:
        {
            "action": "talk" | "function",
            "text": "Hello world",
            "function_name": "emotionShow",
            "function_args": {"emotion": "QT/happy"} 
        }
        """
        rospy.loginfo(f"Instructed to perform: {payload}")
        action = payload.get("action")
        
        if action == "talk":
            text = payload.get("text", "")
            if text:
                self.talkText(text)
                
        elif action == "function":
            func_name = payload.get("function_name")
            args = payload.get("function_args", {})
            try:
                if func_name == "emotionShow":
                    self.emotionShow(args.get("emotion", "QT/neutral"))
                elif func_name == "gesturePlay":
                    self.gesturePlay(args.get("name", ""), args.get("speed", 1.0))
                elif func_name == "setLanguage":
                    # Args: {"lang_code": "en-US", "pitch": 100, "speed": 100}
                    lang_code = args.get("lang_code", "zh-CN")
                    self.speechConfig(lang_code, args.get("pitch", 100), args.get("speed", 100))
                    # switch ASR language
                    self.lang_pub.publish(lang_code)
                    rospy.loginfo(f" Successfully updated TTS and notified Riva ASR to use language: {lang_code}")
                elif func_name == "setVolume":
                    level = args.get("level", 50)
                    mapped_level = int(24 * math.log(level) - 10) if level > 0 else 0
                    self.settingVolume(mapped_level)
                elif func_name == "showECG":
                    import subprocess
                    import os
                    
                    if self.ecg_process is not None and self.ecg_process.poll() is None:
                        rospy.logwarn("ECG UI is already running! Ignoring duplicate request to save memory.")
                        return 
                        
                    rospy.loginfo("Launching ECG UI on physical display...")
                    env = os.environ.copy()
                    env["DISPLAY"] = ":0"
                    
                    # TODO: renew the path of the ecg script
                    ecg_script_path = args.get("script_path", "/home/qtrobot/ecg/ecg_real_gui_pyqtgraph.py")
                    
                    # store the process to monitor
                    self.ecg_process = subprocess.Popen(["python3", ecg_script_path], env=env)
                else:
                    rospy.logwarn(f"Unknown function requested: {func_name}")
            except Exception as e:
                rospy.logerr(f"Error executing function {func_name}: {e}")

if __name__ == "__main__":
    rospy.init_node("ros_behavior_dispatcher", anonymous=True)
    
    # Port 5556 acts as the sink where AI behavior instructions drop in
    dispatcher = ROSBehaviorDispatcher(zmq_port="tcp://*:5556")
    try:
        dispatcher.spin()
    except rospy.ROSInterruptException:
        pass
    finally:
        dispatcher.socket.close()
        dispatcher.context.term()
