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
    1. 'search': The user is asking for general facts, weather, current events, technology news, or any non-medical global knowledge.
    2. 'rag_search': The user is asking about health and medical topics. This includes:
       - Diseases or conditions (e.g. heart disease, diabetes, arrhythmia, PVC, AFib)
       - Symptoms and their causes (e.g. palpitations, chest pain, dizziness)
       - Medications, treatments, or medical procedures
       - Preventive healthcare and lifestyle advice (e.g. diet for heart health, exercise recommendations)
       - Medical terminology explained in plain language (e.g. "what is tachycardia?")
       - Any patient education or wellness question
       This route queries authoritative sources (MedlinePlus) for accurate medical information.
    3. 'system_control': The user requests a direct system or hardware command (e.g., switch language to English, adjust volume, stop talking). THIS IS STRICTLY FOR HARDWARE COMMANDS, NOT FOR CHIT-CHAT OR EMOTIONS.
    4. 'agent': Casual conversation, greetings, storytelling, or any other conversational interaction unrelated to health or hardware.

    When in doubt between 'search' and 'rag_search', choose 'rag_search' for any health-related question.
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
    
    # Reset transient state variables while preserving persistent ones like language
    return {
        "route_decision": route,
        "tool_raw_xml": "",
        "refined_context": "",
        "final_response": "",
        "language": state.get("language", "zh-TW")
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
    1. Set Language: func_name="setLanguage", func_args={"lang_code": "en_US" | "zh_MA"}
    2. Set Volume: func_name="setVolume", func_args={"level": 50}
    
    If uncertain, default to setting volume to 50.
    """
    
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_input)
    ]
    
    try:
        response = router_llm.invoke(messages)
        decision = orjson.loads(response.content)
        
        # Sync internal state if language is changed
        new_lang = state.get("language", "zh-TW")
        if decision.get("func_name") == "setLanguage":
            lang_code = decision.get("func_args", {}).get("lang_code")
            if "en" in str(lang_code):
                new_lang = "en-US"
            elif "zh" in str(lang_code):
                new_lang = "zh-TW"

        action_json_str = orjson.dumps(decision).decode('utf-8')
        return {
            "final_response": f"<PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
            "language": new_lang
        }
    except Exception as e:
        logger.error(f"Action mapping failed: {e}")
        fallback = '{"action_type": "function", "func_name": "setVolume", "func_args": {"level": 50}}'
        return {
            "final_response": f"<PHYSICAL_ACTION_REQUEST>{fallback}</PHYSICAL_ACTION_REQUEST>",
            "language": state.get("language", "zh-TW")
        }

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
        # Retrieve context from our mixed RAG engine (Local FAISS + MedlinePlus)
        xml_content = rag_engine.retrieve_context(user_input, k=3)
        
        if not xml_content:
            xml_content = "No relevant information found in local knowledge or MedlinePlus."
        
    except Exception as e:
        logger.error(f"Error in rag_search_node: {e}")
        xml_content = f"Error during RAG search: {e}"

    return {"tool_raw_xml": xml_content}

def summarizer_node(state: AgentState):
    """
    Summarizes the RAG search results from both TSOC local knowledge 
    and MedlinePlus to provide a unified, authoritative answer.
    """
    raw_xml = state.get("tool_raw_xml", "")
    user_input = state.get("input_text", "")

    if not raw_xml or "No relevant information" in raw_xml:
        logger.warning("[Summarizer] No context provided to summarizer.")
        return {"refined_context": "抱歉，目前知識庫中沒有相關資訊可以回答您的問題。建議諮詢專業醫師。"}

    # Determine output language
    target_lang = state.get("language", "zh-TW")
    lang_name = "TRADITIONAL CHINESE (zh-TW)" if target_lang == "zh-TW" else "ENGLISH"

    prompt = (
        f"User question: '{user_input}'\n\n"
        "Below are the retrieved medical knowledge sources (including Taiwan Society of Cardiology (TSOC) guidelines and MedlinePlus authoritative information):\n"
        f"{raw_xml}\n\n"
        f"Please provide a VERY SHORT, professional response IN {lang_name}:\n"
        f"1. THE RESPONSE MUST BE IN {lang_name} and EXTREMELY BRIEF (under 3 sentences / 50 words).\n"
        "2. Prioritize information from TSOC guidelines and attribute it clearly.\n"
        "3. Use MedlinePlus data to supplement details where appropriate.\n"
        "4. Structure the answer normally but keep it strictly narrative.\n"
        "5. USE A NARRATIVE, DESCRIPTIVE STYLE. Avoid bullet points.\n"
        "6. DO NOT say the word 'QTrobot' or 'QT' in your speech.\n"
        "7. Be accurate and do not hallucinate."
    )

    logger.info(f"[Summarizer] Processing RAG context (length: {len(raw_xml)})...")
    response = summarizer_llm.invoke([HumanMessage(content=prompt)])
    refined_context = response.content
    logger.info(f"[Summarizer] Refined response generated: {len(refined_context)} chars.")

    return {"refined_context": refined_context}

def main_agent_node(state: AgentState):
    """
    main agent node: generate final response
    """
    user_input = state["input_text"]
    context = state.get("refined_context", "")
    logger.info("[Agent] main LLM is generating response...")
    
    # Determine output language
    target_lang = state.get("language", "zh-TW")
    lang_name = "TRADITIONAL CHINESE (zh-TW)" if target_lang == "zh-TW" else "ENGLISH"

    sys_prompt = (
        f"You are a warm and friendly voice assistant. Answer the user's question in a VERY SHORT, CONCISE, and NARRATIVE style IN {lang_name}.\n"
        f"CRITICAL: YOUR ENTIRE RESPONSE MUST BE EXTREMELY BRIEF (under 2 sentences / 40 words) and IN {lang_name}.\n"
        "CRITICAL: DO NOT say the word 'QTrobot' or 'QT' in your speech, as it will trigger a hardware echo. Always refer to yourself simply as 'AI' or '我'.\n"
        "CRITICAL: AVOID using bullet points, numbered lists, or '1, 2, 3' sequences in your speech. Speak in cohesive, natural paragraphs as if you are talking to a friend.\n"
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
        f"Format Example (ALWAYS IN {lang_name}):\n"
        "你好！今天感覺怎麼樣？ <PHYSICAL_ACTION_REQUEST>[{\"action_type\": \"function\", \"func_name\": \"emotionShow\", \"func_args\": {\"emotion\": \"QT/happy\"}}]</PHYSICAL_ACTION_REQUEST>"
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
