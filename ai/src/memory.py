from state import AgentState
from config import summarizer_llm, logger
from langchain_core.messages import HumanMessage

def memory_compress_node(state: AgentState):
    """
    memory_compress_node: compresses dialogue history when it exceeds a threshold
    """
    history = state.get("chat_history", [])
    
    # We compress when the history length goes over 10 messages (5 turns)
    if len(history) < 5:
        return {}
        
    logger.info("[Memory] Dialogue history exceeds threshold. Compressing memory...")
    
    old_summary = state.get("memory_summary", "")
    prompt = f"Previous summary: {old_summary}\n\nRecent conversation:\n"
    
    for msg in history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        prompt += f"{role}: {content}\n"
        
    prompt += "\nPlease summarize the above conversation into a concise context for the AI assistant. Focus on key information and user preferences."
    
    try:
        response = summarizer_llm.invoke([HumanMessage(content=prompt)])
        new_summary = response.content
        logger.info(f"[Memory] Compressed memory summary: {new_summary}")
        
        # Keep the latest 2 messages to maintain immediate dialogue flow
        return {"memory_summary": new_summary, "chat_history": history[-2:]}
    except Exception as e:
        logger.error(f"[Memory] Compression failed: {e}")
        return {}
