#!/usr/bin/env python3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import logger
from bridge import ZMQBridge
from graph import build_graph

# for LangGraph Studio (langgraph dev, only on mac)
app = build_graph()

# ==========================================
# 6. system startup loop
# ==========================================
if __name__ == "__main__":
    is_test_mode = "--test" in sys.argv
    
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY not found, please check ai/config/.env")
    
    bridge = ZMQBridge(pull_port=5555, push_port=5556, test_mode=is_test_mode)
    
    logger.info("LangGraph AI brain is running!")
    
    # initialize state memory
    current_state = {
        "input_text": "",
        "chat_history": [],
        "memory_summary": "",
        "route_decision": "",
        "tool_raw_xml": "",
        "refined_context": "",
        "final_response": ""
    }
    
    try:
        while True:
            # 1. intercept voice input
            incoming_data = bridge.wait_for_input()
            text = incoming_data.get("text", "")
            
            if not text:
                continue
                
            # 2. clear expired variables and send to brain
            # note: keep chat_history and memory_summary, clear other states
            current_state["input_text"] = text
            current_state["tool_raw_xml"] = ""
            current_state["refined_context"] = ""
            current_state["final_response"] = ""
            
            logger.info("="*40)
            logger.info(f"Processing dialogue: {text}")
            
            # execute state machine (state machine will print logs in order)
            final_state = app.invoke(current_state)
            
            # update state memory (to keep chat history and summary)
            current_state["chat_history"] = final_state.get("chat_history", current_state["chat_history"])
            current_state["memory_summary"] = final_state.get("memory_summary", current_state["memory_summary"])
            
            # 3. handle state machine decisions and forward to ROS
            response_text = final_state.get("final_response", "")
            
            import re
            import json
            
            # Find all <PHYSICAL_ACTION_REQUEST> blocks
            pattern = r"<PHYSICAL_ACTION_REQUEST>(.*?)</PHYSICAL_ACTION_REQUEST>"
            action_blocks = re.findall(pattern, response_text, re.DOTALL)
            
            # Strip the blocks from the text to get the spoken content
            spoken_text = re.sub(pattern, "", response_text, flags=re.DOTALL).strip()
            
            # Process any action blocks
            for json_str in action_blocks:
                try:
                    action_payload = json.loads(json_str)
                    if isinstance(action_payload, dict):
                        action_payload = [action_payload]
                        
                    for action_data in action_payload:
                        action = action_data.get("action_type", "function")
                        func_name = action_data.get("func_name", "")
                        func_args = action_data.get("func_args", {})
                        if func_name:
                            logger.info(f"[Action Extracted] {func_name} | args: {func_args}")
                            bridge.send_action(action=action, func_name=func_name, func_args=func_args)
                except Exception as e:
                    logger.error(f"Failed to parse action JSON: {e}")
                    
            # Talk the remaining clean text
            if spoken_text:
                bridge.send_action(action="talk", text=spoken_text)
                
    except KeyboardInterrupt:
        logger.info("\nAI brain is shutting down...")
    finally:
        if not is_test_mode:
            bridge.receiver.close()
            bridge.sender.close()
            bridge.context.term()
