import orjson
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.utilities import GoogleSerperAPIWrapper
from state import AgentState
from config import router_llm, summarizer_llm, main_agent_llm, logger
from rag_engine import rag_engine

# ==========================================
# 3. LangGraph Nodes
# ==========================================

def router_node(state: AgentState):
    """
    router node: determine whether to chat, search, or perform physical actions
    """
    user_input = state["input_text"]
    logger.info(f"[Router] {user_input}")
    
    sys_prompt = """You are a router that determines the user's intent.
    You can only choose from the following four categories:
    1. 'search': The user is asking for general facts, weather, current events, or global knowledge.
    2. 'rag_search': The user is asking about specific diseases, symptoms, medical conditions, or health advice (this will query local medical texts).
    3. 'system_control': The user requests a direct system or hardware command (e.g., switch language to English, adjust volume, stop talking). THIS IS STRICTLY FOR HARDWARE COMMANDS, NOT FOR CHIT-CHAT OR EMOTIONS.
    4. 'agent': Casual conversation, greetings, storytelling, or any other conversational interaction.

    Return format: {"route": "search"} or {"route": "rag_search"} or {"route": "system_control"} or {"route": "agent"}
    """

    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_input)
    ]
    
    # service using openai or llama3
    response = router_llm.invoke(messages)
    try:
        decision = orjson.loads(response.content)
        route = decision.get("route", "agent")
    except Exception:
        # if parse failed, default to chat agent
        route = "agent"
        
    logger.info(f"[Router] route: {route}")
    
    # Reset transient state variables from previous turns 
    # to prevent context leakage across separate dialogue turns in LangGraph Studio.
    return {
        "route_decision": route,
        "tool_raw_xml": "",
        "refined_context": "",
        "final_response": ""
    }

def system_control_node(state: AgentState):
    """
    system control node: determine what system control action to perform
    """
    user_input = state["input_text"]
    logger.info(f"[Action] Inferring system control action for: {user_input}")
    
    sys_prompt = """You are a system control mapper for the QTrobot.
    Map the user's explicit command to the correct system function. 
    Return format MUST be valid JSON, strictly following this structure: 
    {"action_type": "function", "func_name": "...", "func_args": {"...": "..."}}
    
    Available system commands:
    1. Set Language: func_name="setLanguage", func_args={"lang_code": "en-US" | "zh-CN"}
    2. Set Volume: func_name="setVolume", func_args={"level": 50}
    
    If uncertain, default to setting volume to 50.
    """
    
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_input)
    ]
    
    try:
        response = router_llm.invoke(messages)
        # Parse JSON
        decision = orjson.loads(response.content)
        action_json_str = orjson.dumps(decision).decode('utf-8')
        return {"final_response": f"<PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>"}
    except Exception as e:
        logger.error(f"Action mapping failed: {e}")
        # Default fallback
        fallback = '{"action_type": "function", "func_name": "setVolume", "func_args": {"level": 50}}'
        return {"final_response": f"<PHYSICAL_ACTION_REQUEST>{fallback}</PHYSICAL_ACTION_REQUEST>"}

def tool_web_search_node(state: AgentState):
    """
    web search node: perform web search
    """
    user_input = state["input_text"]
    logger.info(f"[Tool] web search: {user_input}")
    
    try:
        search = GoogleSerperAPIWrapper()
        raw_results = search.results(user_input)
        
        # pack search results into xml format
        xml_content = "<xml>\n"
        
        if "answerBox" in raw_results:
             ans_box = raw_results["answerBox"]
             ans = ans_box.get("answer") or ans_box.get("snippet") or ""
             xml_content += f"<answerBox>{ans}</answerBox>\n"
             
        organic_results = raw_results.get("organic", [])[:3]
        for i, res in enumerate(organic_results):
            xml_content += f"<result_{i+1}>\n"
            xml_content += f"<title>{res.get('title', '')}</title>\n"
            xml_content += f"<snippet>{res.get('snippet', '')}</snippet>\n"
            xml_content += f"</result_{i+1}>\n"
            
        xml_content += "</xml>"
        
    except Exception as e:
        logger.error(f"Tavily search failed: {e}")
        xml_content = f"<xml><error>search failed: {str(e)}</error></xml>"
        
    return {"tool_raw_xml": xml_content}

def rag_search_node(state: AgentState):
    """
    RAG search node: query local txt documents via FAISS
    """
    user_input = state["input_text"]
    logger.info(f"[Tool] Local RAG search: {user_input}")
    
    try:
        # Retrieve context from ourFAISS index
        retrieved_text = rag_engine.retrieve_context(user_input, k=3)
        
        # package into xml format so summarizer_node can process it uniformly
        xml_content = "<xml>\n<rag_results>\n"
        if retrieved_text:
            xml_content += retrieved_text
        else:
            xml_content += "No relevant information found in the local knowledge base."
        xml_content += "\n</rag_results>\n</xml>"
        
    except Exception as e:
        logger.error(f"RAG search failed: {e}")
        xml_content = f"<xml><error>RAG search failed: {str(e)}</error></xml>"
        
    return {"tool_raw_xml": xml_content}

def summarizer_node(state: AgentState):
    """
    summarizer node: summarize the search results
    """
    raw_xml = state.get("tool_raw_xml", "")
    user_input = state.get("input_text", "")
    logger.info("[Summarizer] summarize the search results")
    
    prompt = (
        f"The user asked: '{user_input}'.\n"
        f"Based on the following search results in XML, please extract the factual information and provide a direct, concise answer to the user's question.\n"
        f"Please ignore any conversational filler, chatbot error messages, or artificial regional restrictions (e.g., 'I can only provide weather for X region') found in the search results.\n\n"
        f"Search Results XML:\n{raw_xml}"
    )
    response = summarizer_llm.invoke([HumanMessage(content=prompt)])
    refined_context = response.content
    
    logger.info(f"[Summarizer] refined context: {refined_context}")
    return {"refined_context": refined_context}

def main_agent_node(state: AgentState):
    """
    main agent node: generate final response
    """
    user_input = state["input_text"]
    context = state.get("refined_context", "")
    logger.info("[Agent] main LLM is generating response...")
    
    sys_prompt = (
        "You are a warm and friendly QTrobot voice assistant. Please answer the user's question in a short and lively manner.\n"
        "If you want to express emotions or body movements while talking, append a <PHYSICAL_ACTION_REQUEST> block anywhere in your response.\n"
        "You can use multiple actions by returning a JSON array.\n"
        "Available 'emotionShow' actions (func_args={\"emotion\": \"...\"}):\n"
        "- Basic: QT/happy, QT/happy_blinking, QT/sad, QT/cry, QT/angry, QT/surprised, QT/confused, QT/disgusted, QT/shy\n"
        "- Conversational: QT/neutral, QT/neutral_state_blinking, QT/showing_smile, QT/talking, QT/yawn, QT/kiss\n"
        "- Daily habits: QT/brushing_teeth, QT/brushing_teeth_foam, QT/dirty_face, QT/dirty_face_sad, QT/dirty_face_wash\n"
        "- Health: QT/with_a_cold, QT/with_a_cold_cleaning_nose, QT/with_a_cold_sneezing\n"
        "- Relaxation: QT/calming_down, QT/calming_down_exercise_nose, QT/puffing_the_cheeks, QT/scream\n"
        "Available 'gesturePlay' actions (func_args={\"name\": \"...\", \"speed\": 1.0}):\n"
        "- Emotional: QT/happy, QT/sad, QT/angry, QT/surprise, QT/shy, QT/cry\n"
        "- Social: QT/hi, QT/hello, QT/bye, QT/kiss, QT/hug, QT/clapping, QT/dance\n"
        "- Conversational: QT/nod, QT/yes, QT/shake_head, QT/no, QT/yawn, QT/up, QT/down, QT/breathing\n"
        "- Pointing: QT/point_left, QT/point_right, QT/point_up, QT/point_down, QT/point_forward, QT/point_you, QT/show, QT/show_tablet\n\n"
        "Format Example:\n"
        "That sounds wonderful! <PHYSICAL_ACTION_REQUEST>[{\"action_type\": \"function\", \"func_name\": \"emotionShow\", \"func_args\": {\"emotion\": \"QT/happy\"}}, {\"action_type\": \"function\", \"func_name\": \"gesturePlay\", \"func_args\": {\"name\": \"QT/clapping\", \"speed\": 1.0}}]</PHYSICAL_ACTION_REQUEST>"
    )
    if context:
        sys_prompt += f"\n\nReference external knowledge: {context}"
        
    memory_summary = state.get("memory_summary", "")
    if memory_summary:
        sys_prompt += f"\n\nPrevious conversation memory summary: {memory_summary}"
        
    lc_messages = [
        SystemMessage(content=sys_prompt)
    ]
    
    # Directly inject recent chat history into the prompt context
    history = state.get("chat_history", [])
    if history:
        for msg in history:
            if msg.get("role") == "user":
                lc_messages.append(HumanMessage(content=msg.get("content", "")))
            else:
                from langchain_core.messages import AIMessage
                lc_messages.append(AIMessage(content=msg.get("content", "")))
                
    lc_messages.append(HumanMessage(content=user_input))
    
    response = main_agent_llm.invoke(lc_messages)
    reply_text = response.content
    
    new_history = history + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": reply_text}
    ]
    
    return {"final_response": reply_text, "chat_history": new_history}
