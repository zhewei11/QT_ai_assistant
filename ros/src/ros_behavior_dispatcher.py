#!/usr/bin/env python3
# Copyright (c) 2024 LuxAI S.A.
# 
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT

import rospy
import zmq
import json
import math
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from std_msgs.msg import String, Bool

# Implemented robust imports assuming qt_robot_interface is available in the workspace
try:
    from qt_robot_interface.srv import behavior_talk_text
except ImportError as e:
    rospy.logwarn(f"Mocking behavior_talk_text. Error: {e}")
    behavior_talk_text = None

try:
    from qt_robot_interface.srv import speech_config
except ImportError as e:
    rospy.logwarn(f"Mocking speech_config. Error: {e}")
    speech_config = None

try:
    from qt_robot_interface.srv import emotion_show
except ImportError as e:
    rospy.logwarn(f"Mocking emotion_show. Error: {e}")
    emotion_show = None

try:
    from qt_robot_interface.srv import setting_setVolume
except ImportError as e:
    rospy.logwarn(f"Mocking setting_setVolume. Error: {e}")
    setting_setVolume = None

try:
    from qt_gesture_controller.srv import gesture_play
except ImportError as e:
    rospy.logwarn(f"Mocking gesture_play. Error: {e}")
    gesture_play = None

class ROSBehaviorDispatcher:
    CONTROL_WHILE_ANSWER_PAUSED = {
        "resumeAnswering",
        "pauseAnswering",
        "setLanguage",
        "setVolume",
        "pauseMicrophone",
        "resumeMicrophone",
        "showECG",
        "measureECG",
    }
    LANGUAGE_MAP = {
        # QTrobot TTS uses zh-MA for Mandarin; Riva ASR uses zh-CN.
        # The AI layer still uses zh-TW internally to mean Traditional Chinese output.
        "zh": ("zh-MA", "zh-CN"),
        "zh-ma": ("zh-MA", "zh-CN"),
        "zh_ma": ("zh-MA", "zh-CN"),
        "zh-cn": ("zh-MA", "zh-CN"),
        "zh_cn": ("zh-MA", "zh-CN"),
        "zh-tw": ("zh-MA", "zh-CN"),
        "zh_tw": ("zh-MA", "zh-CN"),
        "chinese": ("zh-MA", "zh-CN"),
        "en": ("en-US", "en-US"),
        "en-us": ("en-US", "en-US"),
        "en_us": ("en-US", "en-US"),
        "english": ("en-US", "en-US"),
    }
    GESTURE_ALIASES = {
        "QT/hello": "QT/hi",
        "hello": "QT/hi",
        "hi": "QT/hi",
        "wave": "QT/hi",
        "QT/wave": "QT/hi",
        "bye": "QT/bye",
        "bye-bye": "QT/bye-bye",
        "happy": "QT/happy",
        "sad": "QT/sad",
        "angry": "QT/angry",
        "surprise": "QT/surprise",
        "surprised": "QT/surprise",
        "kiss": "QT/kiss",
        "clapping": "QT/clapping",
        "yawn": "QT/yawn",
        "show": "QT/show_tablet",
        "show_tablet": "QT/show_tablet",
        "show_QT": "QT/show_QT",
        "point_front": "QT/point_front",
        "QT/show": "QT/show_tablet",
        "QT/point_forward": "QT/point_front",
        "QT/point_left": "QT/show_left",
        "QT/point_right": "QT/show_right",
        "QT/point_up": "QT/one-arm-up",
        "QT/point_down": "QT/show_tablet",
        "QT/point_you": "QT/point_front",
        "nod": "QT/happy",
        "QT/nod": "QT/happy",
        "yes": "QT/happy",
        "QT/yes": "QT/happy",
        "shake_head": "QT/sad",
        "QT/shake_head": "QT/sad",
        "no": "QT/sad",
        "QT/no": "QT/sad",
        "shy": "QT/happy",
        "QT/shy": "QT/happy",
        "QT/cry": "QT/sad",
        "QT/hug": "QT/kiss",
        "dance": "QT/clapping",
        "QT/dance": "QT/clapping",
        "up": "QT/one-arm-up",
        "QT/up": "QT/one-arm-up",
        "down": "QT/show_tablet",
        "QT/down": "QT/show_tablet",
        "breathing": "QT/breathing_exercise",
        "QT/breathing": "QT/breathing_exercise",
        "breathing_exercise": "QT/breathing_exercise",
        "point_forward": "QT/point_front",
        "show_left": "QT/show_left",
        "show_right": "QT/show_right",
        "swipe_left": "QT/swipe_left",
        "swipe_right": "QT/swipe_right",
        "one-arm-up": "QT/one-arm-up",
        "neutral": "QT/neutral",
        "bored": "QT/bored",
        "challenge": "QT/challenge",
        "personal-distance": "QT/personal-distance",
        "hand-front-hold": "QT/hand-front-hold",
        "touch-head": "QT/touch-head",
        "touch-head-back": "QT/touch-head-back",
        "drink": "QT/drink",
        "sneezing": "QT/sneezing",
        "send_kiss": "QT/send_kiss",
        "monkey": "QT/monkey",
        "peekaboo": "QT/peekaboo",
        "peekaboo-back": "QT/peekaboo-back",
        "stretching": "QT/stretching",
        "up_left": "QT/up_left",
        "up_right": "QT/up_right",
        "train": "QT/train",
        "Show-face": "QT/Show-face",
    }
    EMOTION_ALIASES = {
        "happy": "QT/happy",
        "smile": "QT/showing_smile",
        "neutral": "QT/neutral",
    }

    def __init__(self, zmq_port="tcp://*:5556"):
        # Create Publishers/Services Proxies mapping to real robot actuators
        rospy.loginfo("Initializing ROS Proxies...")
        
        self.talkText = rospy.ServiceProxy('/qt_robot/behavior/talkText', behavior_talk_text) if behavior_talk_text else lambda x: rospy.loginfo(f"[MOCK] Talking: {x}")
        self.speechConfig = rospy.ServiceProxy('/qt_robot/speech/config', speech_config) if speech_config else lambda l, p, s: rospy.loginfo(f"[MOCK] Lang: {l}")
        self.emotionShow = rospy.ServiceProxy('/qt_robot/emotion/show', emotion_show) if emotion_show else lambda e: rospy.loginfo(f"[MOCK] Emotion: {e}")
        self.settingVolume = rospy.ServiceProxy('/qt_robot/setting/setVolume', setting_setVolume) if setting_setVolume else lambda v: rospy.loginfo(f"[MOCK] Volume: {v}")
        self.gesturePlay = rospy.ServiceProxy('/qt_robot/gesture/play', gesture_play) if gesture_play else lambda n, s: rospy.loginfo(f"[MOCK] Gesture: {n} speed: {s}")

        # Publisher to notify Riva of language changes
        self.lang_pub = rospy.Publisher('/qt_ai_assistant/language_config', String, queue_size=10, latch=True)
        self.mic_pause_pub = rospy.Publisher('/qt_ai_assistant/mic_pause', Bool, queue_size=10)
        self.mic_resume_delay = rospy.get_param("~mic_resume_delay", 0.8)
        self.mic_pause_lead_time = rospy.get_param("~mic_pause_lead_time", 0.1)
        self.post_tts_ready_delay = rospy.get_param("~post_tts_ready_delay", 0.25)
        self.multimodal_sync_start = bool(rospy.get_param("~multimodal_sync_start", True))
        self.default_language = rospy.get_param("~default_language", "en-US")
        self.default_tts_pitch = int(rospy.get_param("~default_tts_pitch", 100))
        self.default_tts_speed = int(rospy.get_param("~default_tts_speed", 118))
        self.default_volume_level = int(rospy.get_param("~default_volume_level", 80))
        self.current_tts_speed = self.default_tts_speed
        self.user_mic_pause_default_seconds = float(rospy.get_param("~user_mic_pause_default_seconds", 10.0))
        self.pause_mic_during_ecg = os.environ.get("ECG_PAUSE_MIC_DURING_MEASURE", "true").lower() == "true"
        self.close_ecg_dashboard_after_measure = os.environ.get("ECG_CLOSE_DASHBOARD_AFTER_MEASURE", "true").lower() == "true"

        # ZeroMQ PULL Socket Configuration
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PULL)
        self.socket.bind(zmq_port)
        self.ecg_measurement_process = None
        self.ecg_kiosk_process = None
        self.latest_request_id = 0
        self.answer_paused = False
        self.answer_pause_lock = threading.Lock()
        self.mic_pause_reasons = set()
        self.mic_pause_lock = threading.Lock()
        self.user_mic_pause_timer = None
        rospy.loginfo(f"ROSBehaviorDispatcher listening on {zmq_port} ... awaiting AI AI_Assistant instructions.")
        self._set_language(self.default_language)
        self._set_volume(self.default_volume_level)

    def _publish_mic_pause_state(self):
        paused = bool(self.mic_pause_reasons)
        self.mic_pause_pub.publish(Bool(data=paused))
        rospy.loginfo(f"[Mic] paused={paused} reasons={sorted(self.mic_pause_reasons) or ['none']}")

    def _add_mic_pause(self, reason):
        with self.mic_pause_lock:
            self.mic_pause_reasons.add(reason)
            self._publish_mic_pause_state()

    def _remove_mic_pause(self, reason):
        with self.mic_pause_lock:
            self.mic_pause_reasons.discard(reason)
            self._publish_mic_pause_state()

    def _set_volume(self, level):
        level = max(0, min(100, int(level)))
        mapped_level = int(24 * math.log(level) - 10) if level > 0 else 0
        rospy.loginfo(f"[Volume] setting QTrobot volume level={level} mapped={mapped_level}")
        self.settingVolume(mapped_level)

    def _pause_microphone_for_user(self, duration_seconds=None):
        duration = self.user_mic_pause_default_seconds if duration_seconds in (None, "") else float(duration_seconds)
        duration = max(1.0, min(duration, 120.0))
        if self.user_mic_pause_timer:
            self.user_mic_pause_timer.cancel()
        self._add_mic_pause("user_control")
        rospy.loginfo(f"[Mic] user requested pause duration={duration:.1f}s")
        self.user_mic_pause_timer = threading.Timer(duration, self._resume_microphone_from_user_control)
        self.user_mic_pause_timer.daemon = True
        self.user_mic_pause_timer.start()

    def _resume_microphone_from_user_control(self):
        if self.user_mic_pause_timer:
            self.user_mic_pause_timer.cancel()
            self.user_mic_pause_timer = None
        self._remove_mic_pause("user_control")
        rospy.loginfo("[Mic] user microphone pause released.")

    def _pause_answering(self):
        with self.answer_pause_lock:
            self.answer_paused = True
        rospy.loginfo("[Answer Control] output paused; microphone remains active.")

    def _resume_answering(self):
        with self.answer_pause_lock:
            self.answer_paused = False
        rospy.loginfo("[Answer Control] output resumed.")

    def _is_answering_paused(self):
        with self.answer_pause_lock:
            return self.answer_paused

    def _run_async_service(self, label, callback, *args, start_event=None):
        def runner():
            try:
                if start_event is not None:
                    start_event.wait()
                rospy.loginfo(f"[Action Dispatch] {label} args={args}")
                result = callback(*args)
                rospy.loginfo(f"[Action Dispatch] {label} result={result}")
            except Exception as e:
                rospy.logerr(f"Error executing async {label}: {e}")

        thread = threading.Thread(target=runner, name=f"{label}_worker", daemon=True)
        thread.start()
        return thread

    def _call_emotion_show(self, emotion):
        rospy.wait_for_service('/qt_robot/emotion/show', timeout=2)
        return self.emotionShow(emotion)

    def _call_gesture_play(self, name, speed):
        rospy.wait_for_service('/qt_robot/gesture/play', timeout=2)
        return self.gesturePlay(name, speed)

    def _wait_for_service_ready(self, service_name, timeout=1.5):
        try:
            rospy.wait_for_service(service_name, timeout=timeout)
            return True
        except Exception as e:
            rospy.logwarn(f"[Multimodal Sync] service not ready before synchronized start: {service_name} ({e})")
            return False

    def _prepare_multimodal_services(self, speech, action_calls):
        service_names = []
        if speech:
            service_names.append('/qt_robot/behavior/talkText')
        for func_name, _args in action_calls:
            if func_name == "emotionShow":
                service_names.append('/qt_robot/emotion/show')
            elif func_name == "gesturePlay":
                service_names.append('/qt_robot/gesture/play')

        for service_name in dict.fromkeys(service_names):
            self._wait_for_service_ready(service_name)

    def _estimate_tts_duration(self, text):
        cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        latin_words = len(re.findall(r"[A-Za-z0-9]+", text))
        other_chars = max(0, len(text) - cjk_chars)
        estimated = (cjk_chars * 0.28) + (latin_words * 0.35) + (other_chars * 0.04)
        speed_factor = max(0.6, min(self.current_tts_speed / 100.0, 1.8))
        estimated = estimated / speed_factor
        return min(max(estimated, 1.2), 30.0)

    def _talk_without_mic_feedback(self, text):
        self._add_mic_pause("tts")
        rospy.sleep(self.mic_pause_lead_time)
        started_at = time.monotonic()
        try:
            self.talkText(text)
            remaining = self._estimate_tts_duration(text) - (time.monotonic() - started_at)
            if remaining > 0:
                rospy.sleep(remaining)
            rospy.sleep(self.mic_resume_delay)
        finally:
            self._remove_mic_pause("tts")
            if self.post_tts_ready_delay > 0:
                rospy.sleep(self.post_tts_ready_delay)

    def _talk_after_start_event(self, text, start_event):
        started_at = None
        try:
            start_event.wait()
            rospy.loginfo("[TTS Dispatch] talkText synchronized start")
            started_at = time.monotonic()
            self.talkText(text)
            remaining = self._estimate_tts_duration(text) - (time.monotonic() - started_at)
            if remaining > 0:
                rospy.sleep(remaining)
            rospy.sleep(self.mic_resume_delay)
        except Exception as e:
            rospy.logerr(f"Error executing synchronized TTS: {e}")
        finally:
            self._remove_mic_pause("tts")
            if self.post_tts_ready_delay > 0:
                rospy.sleep(self.post_tts_ready_delay)

    def _run_synchronized_multimodal(self, speech, action_calls):
        if not speech:
            for func_name, args in action_calls:
                self._dispatch_function(func_name, args)
            return

        start_event = threading.Event()
        self._add_mic_pause("tts")
        rospy.sleep(self.mic_pause_lead_time)
        self._prepare_multimodal_services(speech, action_calls)
        for func_name, args in action_calls:
            if func_name == "emotionShow":
                emotion = self._normalize_emotion_name(args.get("emotion", "QT/neutral"))
                self._run_async_service(
                    "emotionShow",
                    self._call_emotion_show,
                    emotion,
                    start_event=start_event,
                )
            elif func_name == "gesturePlay":
                gesture_name = self._normalize_gesture_name(args.get("name", ""))
                self._run_async_service(
                    "gesturePlay",
                    self._call_gesture_play,
                    gesture_name,
                    args.get("speed", 1.0),
                    start_event=start_event,
                )
            else:
                self._dispatch_function(func_name, args)

        tts_thread = threading.Thread(
            target=self._talk_after_start_event,
            args=(speech, start_event),
            name="tts_worker",
            daemon=True,
        )
        tts_thread.start()
        rospy.loginfo("[Multimodal Sync] starting speech, expression, and gesture together")
        start_event.set()
        tts_thread.join()

    def _resolve_language_codes(self, requested_lang):
        key = str(requested_lang or "zh-TW").strip().lower()
        key = key.replace(" ", "").replace(".", "-")
        if key in self.LANGUAGE_MAP:
            return self.LANGUAGE_MAP[key]

        if key.startswith("zh"):
            return self.LANGUAGE_MAP["zh"]
        if key.startswith("en"):
            return self.LANGUAGE_MAP["en"]

        rospy.logwarn(f"Unsupported language code '{requested_lang}', falling back to zh-TW / zh-CN")
        return self.LANGUAGE_MAP["zh"]

    def _set_language(self, requested_lang, pitch=None, speed=None):
        tts_lang, asr_lang = self._resolve_language_codes(requested_lang)
        pitch = self.default_tts_pitch if pitch in (None, "", 100, "100") else int(pitch)
        speed = self.default_tts_speed if speed in (None, "", 100, "100") else int(speed)
        speed = max(60, min(speed, 200))
        try:
            rospy.wait_for_service('/qt_robot/speech/config', timeout=3)
            ret = self.speechConfig(tts_lang, pitch, speed)
            self.current_tts_speed = speed
            self.lang_pub.publish(asr_lang)
            rospy.sleep(0.2)
            rospy.loginfo(f"Successfully updated TTS to {tts_lang} and Riva ASR to {asr_lang}: {ret}")
            return ret
        except Exception as e:
            rospy.logwarn(f"Failed to set language to {requested_lang}: {e}")
            return None

    def _normalize_gesture_name(self, name):
        original = str(name or "").strip()
        normalized = self.GESTURE_ALIASES.get(original, original)
        if original and normalized != original:
            rospy.loginfo(f"[Action Normalize] gesture {original} -> {normalized}")
        return normalized

    def _normalize_emotion_name(self, emotion):
        original = str(emotion or "").strip()
        normalized = self.EMOTION_ALIASES.get(original, original)
        if original and normalized != original:
            rospy.loginfo(f"[Action Normalize] emotion {original} -> {normalized}")
        return normalized

    def _is_stale_request(self, payload):
        request_id = int(payload.get("request_id", 0) or 0)
        if request_id and request_id < self.latest_request_id:
            rospy.logwarn(f"Dropping stale request {request_id}; latest is {self.latest_request_id}")
            return True
        if request_id:
            self.latest_request_id = request_id
        return False

    def _dispatch_function(self, func_name, args):
        if func_name == "emotionShow":
            emotion = self._normalize_emotion_name(args.get("emotion", "QT/neutral"))
            self._run_async_service(
                "emotionShow",
                self._call_emotion_show,
                emotion,
            )
        elif func_name == "gesturePlay":
            gesture_name = self._normalize_gesture_name(args.get("name", ""))
            self._run_async_service(
                "gesturePlay",
                self._call_gesture_play,
                gesture_name,
                args.get("speed", 1.0),
            )
        elif func_name == "setLanguage":
            # App-level zh-TW is mapped to QTrobot TTS zh-MA and Riva ASR zh-CN.
            self._set_language(
                args.get("lang_code", "en-US"),
                args.get("pitch", 100),
                args.get("speed", 100),
            )
        elif func_name == "setVolume":
            level = args.get("level", 50)
            self._set_volume(level)
        elif func_name == "pauseMicrophone":
            self._pause_microphone_for_user(args.get("duration_seconds"))
        elif func_name == "resumeMicrophone":
            self._resume_microphone_from_user_control()
        elif func_name == "pauseAnswering":
            self._pause_answering()
        elif func_name == "resumeAnswering":
            self._resume_answering()
        elif func_name == "showECG":
            workspace_dir = Path(__file__).resolve().parents[2]
            kiosk_script = workspace_dir / "scripts" / "open_ecg_kiosk.sh"
            env = os.environ.copy()
            env["ECG_DASHBOARD_URL"] = args.get(
                "url",
                env.get("ECG_DASHBOARD_URL", "https://ecg-monitor-bf64d.web.app"),
            )
            rospy.loginfo("=" * 48)
            rospy.loginfo("[ECG kiosk] showECG requested")
            rospy.loginfo(f"[ECG kiosk] url={env['ECG_DASHBOARD_URL']}")
            rospy.loginfo(f"[ECG kiosk] QT_FACE_HOST={env.get('QT_FACE_HOST', '(unset)')}")
            rospy.loginfo(f"[ECG kiosk] QT_FACE_DISPLAY={env.get('QT_FACE_DISPLAY', ':0')}")
            self.ecg_kiosk_process = subprocess.Popen(["bash", str(kiosk_script)], env=env)
            rospy.loginfo(f"[ECG kiosk] process_pid={self.ecg_kiosk_process.pid}")
            rospy.loginfo("=" * 48)
        elif func_name == "measureECG":
            self._start_ecg_measurement(args)
        else:
            rospy.logwarn(f"Unknown function requested: {func_name}")

    def _start_ecg_measurement(self, args):
        if self.ecg_measurement_process and self.ecg_measurement_process.poll() is None:
            rospy.logwarn("ECG measurement is already running; ignoring duplicate request.")
            return

        workspace_dir = Path(__file__).resolve().parents[2]
        session_script = workspace_dir / "ecg" / "src" / "integration" / "ecg_session.py"
        result_file = Path(os.environ.get("ECG_RESULT_FILE", workspace_dir / "runtime" / "ecg_latest.json"))
        configured_python = os.environ.get("ECG_PYTHON", "")
        venv_python = workspace_dir / "ecg" / ".venv" / "bin" / "python"
        python_executable = configured_python or (str(venv_python) if venv_python.exists() else "python3")
        duration = max(10, min(int(args.get("duration_seconds", 60)), 300))
        dashboard_url = os.environ.get("ECG_DASHBOARD_URL", "https://ecg-monitor-bf64d.web.app")
        face_memory_file = os.environ.get("FACE_MEMORY_FILE", str(workspace_dir / "runtime" / "face_memory.json"))

        self.ecg_kiosk_process = subprocess.Popen(
            ["bash", str(workspace_dir / "scripts" / "open_ecg_kiosk.sh")],
            env=os.environ.copy(),
        )
        command = [
            python_executable,
            str(session_script),
            "--duration",
            str(duration),
            "--output",
            str(result_file),
        ]
        try:
            nice_level = int(os.environ.get("ECG_PROCESS_NICE", "5"))
        except ValueError:
            nice_level = 5
        nice_level = max(0, min(nice_level, 19))
        if nice_level:
            command = ["nice", "-n", str(nice_level)] + command
        rospy.loginfo("=" * 48)
        rospy.loginfo("[ECG measurement] measureECG requested")
        rospy.loginfo(f"[ECG measurement] dashboard_url={dashboard_url}")
        rospy.loginfo(f"[ECG measurement] kiosk_pid={self.ecg_kiosk_process.pid}")
        rospy.loginfo(f"[ECG measurement] python={python_executable}")
        rospy.loginfo(f"[ECG measurement] script={session_script}")
        rospy.loginfo(f"[ECG measurement] duration={duration}s")
        rospy.loginfo(f"[ECG measurement] result_file={result_file}")
        rospy.loginfo(f"[ECG measurement] face_memory_file={face_memory_file}")
        rospy.loginfo(f"[ECG measurement] nice_level={nice_level}")
        rospy.loginfo("=" * 48)
        self.ecg_measurement_process = subprocess.Popen(command, env=os.environ.copy())
        rospy.loginfo(f"[ECG measurement] process_pid={self.ecg_measurement_process.pid}")
        if self.pause_mic_during_ecg:
            self._add_mic_pause("ecg")
            rospy.loginfo("[ECG measurement] Microphone paused during ECG measurement.")
        self._monitor_ecg_measurement(self.ecg_measurement_process, workspace_dir)

    def _monitor_ecg_measurement(self, process, workspace_dir):
        def runner():
            return_code = None
            try:
                return_code = process.wait()
                rospy.loginfo(f"[ECG measurement] process finished return_code={return_code}")
            except Exception as e:
                rospy.logerr(f"[ECG measurement] monitor failed: {e}")
            finally:
                if self.pause_mic_during_ecg:
                    self._remove_mic_pause("ecg")
                    rospy.loginfo("[ECG measurement] Microphone resumed after ECG measurement.")
                if self.close_ecg_dashboard_after_measure:
                    close_script = workspace_dir / "scripts" / "close_ecg_kiosk.sh"
                    if close_script.exists():
                        rospy.loginfo("[ECG kiosk] Closing dashboard after ECG measurement.")
                        try:
                            subprocess.Popen(["bash", str(close_script)], env=os.environ.copy())
                        except Exception as e:
                            rospy.logerr(f"[ECG kiosk] Failed to close dashboard: {e}")
                    else:
                        rospy.logwarn(f"[ECG kiosk] close script not found: {close_script}")
                rospy.loginfo("[ECG measurement] Ready for the next conversation.")

        thread = threading.Thread(target=runner, name="ecg_measurement_monitor", daemon=True)
        thread.start()

    def _dispatch_multimodal(self, payload):
        if self._is_stale_request(payload):
            return

        trace = payload.get("trace", {})
        ai_latency = trace.get("ai_latency", {}) if isinstance(trace, dict) else {}

        speech = payload.get("speech") or payload.get("text", "")
        emotions = []
        gestures = []
        action_calls = []
        for action_data in payload.get("actions", []):
            func_name = action_data.get("func_name", action_data.get("function_name", ""))
            args = action_data.get("func_args", action_data.get("function_args", {}))
            if func_name == "emotionShow":
                emotions.append(self._normalize_emotion_name(args.get("emotion", "")))
            elif func_name == "gesturePlay":
                gestures.append(self._normalize_gesture_name(args.get("name", "")))
            if func_name:
                action_calls.append((func_name, args))

        if self._is_answering_paused():
            allowed_calls = [
                (func_name, args)
                for func_name, args in action_calls
                if func_name in self.CONTROL_WHILE_ANSWER_PAUSED
            ]
            if not allowed_calls:
                rospy.loginfo("=" * 48)
                rospy.loginfo(f"[最後輸出 #{payload.get('request_id', '-')}]")
                rospy.loginfo("[Answer Control] 目前暫停回答，已略過語音、表情與動作輸出。")
                rospy.loginfo("[提示] 麥克風仍開啟；可以說「恢復回答」。")
                rospy.loginfo("=" * 48)
                return
            speech = "" if not any(func_name == "resumeAnswering" for func_name, _args in allowed_calls) else speech
            emotions = []
            gestures = []
            action_calls = allowed_calls

        rospy.loginfo("=" * 48)
        rospy.loginfo(f"[最後輸出 #{payload.get('request_id', '-')}]")
        if trace:
            rospy.loginfo(
                "[延遲] "
                f"接收={trace.get('receive_ms')}ms | "
                f"Graph={trace.get('graph_ms')}ms | "
                f"解析={trace.get('parse_ms')}ms | "
                f"AI總計={trace.get('total_ai_ms')}ms"
            )
            if ai_latency:
                latency_parts = []
                for key in (
                    "router_ms",
                    "router_llm_ms",
                    "tool_search_ms",
                    "serper_ms",
                    "rag_search_ms",
                    "rag_retrieve_ms",
                    "summarizer_ms",
                    "summarizer_llm_ms",
                    "medical_education_llm_ms",
                    "main_agent_ms",
                    "main_agent_llm_ms",
                    "system_control_ms",
                    "system_control_llm_ms",
                    "self_introduction_ms",
                ):
                    value = ai_latency.get(key)
                    if value is not None:
                        latency_parts.append(f"{key[:-3]}={value}ms")
                rospy.loginfo(f"[AI細分] {' | '.join(latency_parts)}")
        rospy.loginfo(f"說話: {speech or '(無)'}")
        rospy.loginfo(f"表情: {', '.join(filter(None, emotions)) or '(無)'}")
        rospy.loginfo(f"動作: {', '.join(filter(None, gestures)) or '(無)'}")
        if self.multimodal_sync_start and (speech or action_calls):
            self._run_synchronized_multimodal(speech, action_calls)
        elif action_calls:
            for func_name, args in action_calls:
                self._dispatch_function(func_name, args)
            if speech:
                self._talk_without_mic_feedback(speech)
        elif speech:
            self._talk_without_mic_feedback(speech)
        rospy.loginfo("[提示] 目前可以繼續跟我對話了。")
        rospy.loginfo("=" * 48)

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
        rospy.logdebug(f"Instructed to perform: {payload}")
        action = payload.get("action")

        if self._is_stale_request(payload):
            return
        
        if action == "multimodal":
            self._dispatch_multimodal(payload)

        elif action == "talk":
            text = payload.get("text", "")
            if text:
                self._talk_without_mic_feedback(text)
                
        elif action == "function":
            func_name = payload.get("function_name")
            args = payload.get("function_args", {})
            try:
                self._dispatch_function(func_name, args)
            except Exception as e:
                rospy.logerr(f"Error executing function {func_name}: {e}")

if __name__ == "__main__":
    rospy.init_node("ros_behavior_dispatcher", anonymous=False)
    
    # Port 5556 acts as the sink where AI behavior instructions drop in
    dispatcher = ROSBehaviorDispatcher(zmq_port="tcp://*:5556")
    try:
        dispatcher.spin()
    except rospy.ROSInterruptException:
        pass
    finally:
        dispatcher.socket.close()
        dispatcher.context.term()
