#!/usr/bin/env python3
import json
import os
import re
import sys
import threading
import time
from itertools import count

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import AI_TERMINAL_DEBUG, logger
from bridge import ZMQBridge
from ecg_context import load_ecg_measurement
from graph import build_graph
from memory import memory_compress_node

# for LangGraph Studio (langgraph dev, only on mac)
app = build_graph()
request_counter = count(1)
display_lock = threading.Lock()

ANSWER_RESUME_PATTERNS = [
    r"(恢復|開始|可以|繼續).*(回答|回覆|回應|說話)",
    r"(回答|回覆|回應|說話).*(恢復|開始|打開|開啟|繼續)",
    r"(resume|start|enable).*(answering|responding|response|replying|speaking)",
]

ANSWER_CONTROL_NORMALIZATION = str.maketrans({
    "复": "復",
    "开": "開",
    "启": "啟",
})


def display(message=""):
    with display_lock:
        print(message, flush=True)


def action_summary(actions):
    emotions = []
    gestures = []
    others = []
    for action in actions:
        func_name = action.get("func_name", "")
        func_args = action.get("func_args", {})
        if func_name == "emotionShow":
            emotions.append(func_args.get("emotion", ""))
        elif func_name == "gesturePlay":
            gestures.append(func_args.get("name", ""))
        elif func_name:
            others.append(f"{func_name}({func_args})")
    return emotions, gestures, others


def format_ai_latency(ai_latency):
    if not isinstance(ai_latency, dict) or not ai_latency:
        return ""

    preferred_keys = [
        "router_ms",
        "router_llm_ms",
        "tool_search_ms",
        "serper_ms",
        "rag_search_ms",
        "rag_retrieve_ms",
        "summarizer_ms",
        "summarizer_llm_ms",
        "medical_education_llm_ms",
        "medical_education_ms",
        "medical_personal_ms",
        "main_agent_ms",
        "main_agent_llm_ms",
        "system_control_ms",
        "system_control_llm_ms",
    ]
    parts = []
    for key in preferred_keys:
        value = ai_latency.get(key)
        if value is not None:
            label = key.removesuffix("_ms")
            parts.append(f"{label}={value}ms")

    details = []
    for key in ("router_method", "summarizer_method", "main_agent_method", "system_control_method"):
        value = ai_latency.get(key)
        if value:
            details.append(f"{key.removesuffix('_method')}={value}")

    if details:
        parts.append(" | ".join(details))
    return " | ".join(parts)


def display_received(request_id, text, language):
    display("")
    display("=" * 48)
    display(f"[收到語音文字 #{request_id}]")
    if AI_TERMINAL_DEBUG != "quiet":
        display(f"語言: {language or 'unknown'}")
    display(f"文字: {text}")
    display("[狀態] AI agent 開始處理...")


def display_final(request_id, route, spoken_text, actions, trace):
    emotions, gestures, others = action_summary(actions)
    ai_latency_text = format_ai_latency(trace.get("ai_latency"))
    display(f"[狀態] 完成 route={route or 'unknown'}")
    display(
        "[延遲] "
        f"接收={trace.get('receive_ms')}ms | "
        f"Graph={trace.get('graph_ms')}ms | "
        f"解析={trace.get('parse_ms')}ms | "
        f"AI總計={trace.get('total_ai_ms')}ms"
    )
    if ai_latency_text and AI_TERMINAL_DEBUG != "quiet":
        display(f"[AI細分] {ai_latency_text}")
    display("[最後輸出]")
    display(f"說話: {spoken_text or '(無)'}")
    display(f"表情: {', '.join(filter(None, emotions)) or '(無)'}")
    display(f"動作: {', '.join(filter(None, gestures)) or '(無)'}")
    if others:
        display(f"其他指令: {', '.join(others)}")
    display("[狀態] 回應已送交機器人執行。")
    display("=" * 48)


def display_stale(request_id, latest_request_id):
    display(f"[狀態] 已收到更新的語音，略過舊回應 #{request_id}，目前最新是 #{latest_request_id}。")


def display_answer_paused(request_id):
    display("[狀態] 目前是暫停回答模式，已接收文字但不輸出回應。")
    display("[提示] 麥克風仍開啟；需要恢復時請說：恢復回答。")
    display("=" * 48)


def is_answer_resume_command(text: str) -> bool:
    normalized = (text or "").translate(ANSWER_CONTROL_NORMALIZATION)
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in ANSWER_RESUME_PATTERNS)


def default_physical_actions(text: str):
    normalized = text.lower()
    if any(word in text for word in ("你好", "嗨", "哈囉", "早安", "午安", "晚安")) or any(word in normalized for word in ("hello", "hi", "hey")):
        return [
            {"action_type": "function", "func_name": "emotionShow", "func_args": {"emotion": "QT/happy"}},
            {"action_type": "function", "func_name": "gesturePlay", "func_args": {"name": "QT/hi", "speed": 1.0}},
        ]
    if any(word in text for word in ("謝謝", "感謝", "太好了", "開心")) or any(word in normalized for word in ("thanks", "thank you", "great", "happy")):
        return [
            {"action_type": "function", "func_name": "emotionShow", "func_args": {"emotion": "QT/happy_blinking"}},
            {"action_type": "function", "func_name": "gesturePlay", "func_args": {"name": "QT/clapping", "speed": 1.0}},
        ]
    return [
        {"action_type": "function", "func_name": "emotionShow", "func_args": {"emotion": "QT/showing_smile"}},
        {"action_type": "function", "func_name": "gesturePlay", "func_args": {"name": "QT/happy", "speed": 1.0}},
    ]


def normalize_action_payload(action_data):
    return {
        "action": action_data.get("action_type", action_data.get("action", "function")),
        "func_name": action_data.get("func_name", action_data.get("function_name", "")),
        "func_args": action_data.get("func_args", action_data.get("function_args", {})),
    }


def extract_response_parts(response_text: str, fallback_input: str):
    pattern = r"<PHYSICAL_ACTION_REQUEST>(.*?)</PHYSICAL_ACTION_REQUEST>"
    action_blocks = re.findall(pattern, response_text or "", re.DOTALL)
    spoken_text = re.sub(pattern, "", response_text or "", flags=re.DOTALL).strip()
    actions = []

    for json_str in action_blocks:
        try:
            action_payload = json.loads(json_str)
            if isinstance(action_payload, dict):
                action_payload = [action_payload]

            for action_data in action_payload:
                normalized_action = normalize_action_payload(action_data)
                if normalized_action["func_name"]:
                    actions.append(normalized_action)
        except Exception as e:
            logger.error(f"Failed to parse action JSON: {e}")

    if spoken_text and not actions:
        actions = [normalize_action_payload(action_data) for action_data in default_physical_actions(fallback_input)]

    return spoken_text, actions


def build_multimodal_payload(request_id, text, actions, trace):
    return {
        "action": "multimodal",
        "request_id": request_id,
        "speech": text,
        "actions": actions,
        "trace": trace,
    }


def apply_internal_answer_control(actions, current_state, state_lock):
    external_actions = []
    answer_control = None
    for action in actions:
        func_name = action.get("func_name", "")
        if func_name == "pauseAnswering":
            answer_control = "pause"
            continue
        if func_name == "resumeAnswering":
            answer_control = "resume"
            continue
        external_actions.append(action)

    if answer_control:
        with state_lock:
            current_state["_answer_paused"] = answer_control == "pause"
        logger.info(f"[Answer Control] paused={answer_control == 'pause'}")
    return external_actions, answer_control


def normalize_input_language(language: str):
    normalized = str(language or "").strip().lower().replace("_", "-")
    if normalized.startswith("en"):
        return "en-US"
    if normalized.startswith("zh"):
        return "zh-TW"
    return None


def language_action_args(language: str):
    if language == "en-US":
        return {"lang_code": "en-US", "pitch": 100, "speed": 100}
    if language == "zh-TW":
        return {"lang_code": "zh-TW", "pitch": 100, "speed": 100}
    return None


def compress_memory_async(current_state, state_lock):
    with state_lock:
        history = current_state.get("chat_history", [])
        if len(history) < 5 or current_state.get("_memory_compressing"):
            return

        snapshot = {
            "chat_history": list(history),
            "memory_summary": current_state.get("memory_summary", ""),
        }
        history_version = current_state.get("_history_version", 0)
        current_state["_memory_compressing"] = True

    def worker():
        try:
            updates = memory_compress_node(snapshot)
            with state_lock:
                if updates.get("memory_summary"):
                    current_state["memory_summary"] = updates["memory_summary"]
                if (
                    "chat_history" in updates
                    and current_state.get("_history_version", 0) == history_version
                ):
                    current_state["chat_history"] = updates["chat_history"]
        finally:
            with state_lock:
                current_state["_memory_compressing"] = False

    threading.Thread(target=worker, name="memory_compress_worker", daemon=True).start()

# ==========================================
# 6. system startup loop
# ==========================================
if __name__ == "__main__":
    is_test_mode = "--test" in sys.argv
    
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not found, please check ai/config/.env")
    
    bridge = ZMQBridge(pull_port=5555, push_port=5556, test_mode=is_test_mode)
    
    display("AI brain 已啟動，等待語音輸入。")
    display(
        "AI debug: "
        f"terminal={AI_TERMINAL_DEBUG}, "
        f"log={os.environ.get('AI_LOG_LEVEL', 'WARNING')}, "
        f"library_log={os.environ.get('AI_LIBRARY_LOG_LEVEL', 'WARNING')}"
    )
    
    # initialize state memory
    current_state = {
        "input_text": "",
        "chat_history": [],
        "memory_summary": "",
        "route_decision": "",
        "tool_raw_xml": "",
        "rag_evidence_status": "",
        "rag_max_relevance": 0.0,
        "rag_source_count": 0,
        "medical_risk_level": "",
        "refined_context": "",
        "final_response": "",
        "language": "en-US",
        "ai_latency": {},
        "ecg_measurement": load_ecg_measurement(),
        "_memory_compressing": False,
        "_history_version": 0,
        "_latest_request_id": 0,
        "_answer_paused": False,
    }
    state_lock = threading.Lock()

    def process_turn(incoming_data, request_id, turn_started_at, received_at):
        text = incoming_data.get("text", "")
        if not text:
            return

        display_received(request_id, text, incoming_data.get("language", ""))

        input_language = normalize_input_language(incoming_data.get("language", ""))
        with state_lock:
            current_state["_latest_request_id"] = request_id
            if input_language:
                previous_language = current_state.get("language", "en-US")
                current_state["language"] = input_language
                logger.info(f"[Language] Using ASR input language for response generation: {input_language}")
                if input_language != previous_language:
                    func_args = language_action_args(input_language)
                    if func_args:
                        logger.info(f"[Language] Syncing TTS language to ASR input language: {input_language}")
                        bridge.send_action(action="function", func_name="setLanguage", func_args=func_args)

            if current_state.get("_answer_paused") and not is_answer_resume_command(text):
                display_answer_paused(request_id)
                return

            current_state["input_text"] = text
            current_state["tool_raw_xml"] = ""
            current_state["rag_evidence_status"] = ""
            current_state["rag_max_relevance"] = 0.0
            current_state["rag_source_count"] = 0
            current_state["medical_risk_level"] = ""
            current_state["refined_context"] = ""
            current_state["final_response"] = ""
            current_state["ai_latency"] = {}
            current_state["ecg_measurement"] = load_ecg_measurement()
            state_snapshot = dict(current_state)
            state_snapshot["chat_history"] = list(current_state.get("chat_history", []))
            state_snapshot["ai_latency"] = {}

        logger.info("="*40)
        logger.info(f"Processing dialogue #{request_id}: {text}")

        graph_started_at = time.monotonic()
        final_state = app.invoke(state_snapshot)
        graph_finished_at = time.monotonic()

        with state_lock:
            if request_id != current_state.get("_latest_request_id"):
                logger.warning(f"[Request] Discarding stale AI response #{request_id}; latest is #{current_state.get('_latest_request_id')}")
                display_stale(request_id, current_state.get("_latest_request_id"))
                return
            current_state["chat_history"] = final_state.get("chat_history", current_state["chat_history"])
            current_state["_history_version"] += 1
            current_state["language"] = final_state.get("language", current_state["language"])

        response_text = final_state.get("final_response", "")
        parse_started_at = time.monotonic()
        spoken_text, actions = extract_response_parts(response_text, text)
        actions, answer_control = apply_internal_answer_control(actions, current_state, state_lock)
        parse_finished_at = time.monotonic()

        trace = {
            "request_id": request_id,
            "source": incoming_data.get("source", ""),
            "asr_language": incoming_data.get("language", ""),
            "route": final_state.get("route_decision", ""),
            "receive_ms": round((received_at - turn_started_at) * 1000, 1),
            "graph_ms": round((graph_finished_at - graph_started_at) * 1000, 1),
            "parse_ms": round((parse_finished_at - parse_started_at) * 1000, 1),
            "total_ai_ms": round((parse_finished_at - received_at) * 1000, 1),
            "ai_latency": final_state.get("ai_latency", {}),
        }

        if spoken_text or actions:
            payload = build_multimodal_payload(request_id, spoken_text, actions, trace)
            bridge.send_payload(payload)
            logger.info(
                "[Latency] request=%s route=%s graph_ms=%sms total_ai_ms=%sms",
                request_id,
                trace.get("route", ""),
                trace.get("graph_ms"),
                trace.get("total_ai_ms"),
            )
            display_final(request_id, final_state.get("route_decision", ""), spoken_text, actions, trace)
        elif answer_control:
            display_final(request_id, final_state.get("route_decision", ""), spoken_text, actions, trace)

        compress_memory_async(current_state, state_lock)

    try:
        while True:
            turn_started_at = time.monotonic()
            request_id = next(request_counter)
            # 1. intercept voice input
            incoming_data = bridge.wait_for_input()
            received_at = time.monotonic()
            threading.Thread(
                target=process_turn,
                args=(incoming_data, request_id, turn_started_at, received_at),
                name=f"ai_turn_{request_id}",
                daemon=True,
            ).start()

    except KeyboardInterrupt:
        logger.info("\nAI brain is shutting down...")
    finally:
        bridge.close()
