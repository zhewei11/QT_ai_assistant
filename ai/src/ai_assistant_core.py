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
            # note: keep chat_history, clear other states
            current_state["input_text"] = text
            current_state["tool_raw_xml"] = ""
            current_state["refined_context"] = ""
            current_state["final_response"] = ""
            
            logger.info("="*40)
            logger.info(f"Processing dialogue: {text}")
            
            # execute state machine (state machine will print logs in order)
            final_state = app.invoke(current_state)
            
            # update state memory (to keep chat history)
            current_state["chat_history"] = final_state.get("chat_history", current_state["chat_history"])
            
            # 3. handle state machine decisions and forward to ROS
            response_text = final_state.get("final_response", "")
            
            if response_text == "<PHYSICAL_ACTION_REQUEST>":
                # here for simple demonstration, we directly convert all action requests to smile
                bridge.send_action(action="function", func_name="emotionShow", func_args={"emotion": "QT/happy"})
            elif response_text:
                # normal talking
                bridge.send_action(action="talk", text=response_text)
                
    except KeyboardInterrupt:
        logger.info("\nAI brain is shutting down...")
    finally:
        if not is_test_mode:
            bridge.receiver.close()
            bridge.sender.close()
            bridge.context.term()
