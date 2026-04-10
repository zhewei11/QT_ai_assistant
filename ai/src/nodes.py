import orjson
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.utilities import GoogleSerperAPIWrapper
from state import AgentState
from config import router_llm, summarizer_llm, main_agent_llm, logger

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
    You can only choose from the following three categories:
    1. 'search': The user is asking for facts, weather, current events, or knowledge that requires external verification.
    2. 'physically_act': The user requests the robot to perform actions (wave, smile) or adjust settings (switch language, adjust volume).
    3. 'agent': Casual conversation, greetings, or other conversations that do not fall into the first two categories.

    Return format: {"route": "search"} or {"route": "agent"}
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

def physical_action_node(state: AgentState):
    """
    physical action node: determine what ROS action to perform
    """
    logger.info("[Action] ROS action")
    return {"final_response": "<PHYSICAL_ACTION_REQUEST>"}

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
    
    sys_prompt = "You are a warm and friendly QTrobot voice assistant. Please answer the user's question in a short and lively manner."
    if context:
        sys_prompt += f"\n\nReference external knowledge: {context}"
        
    lc_messages = [
        SystemMessage(content=sys_prompt)
    ]
    
    # Directly inject recent chat history (e.g., last 6 messages = 3 turns) into the prompt context
    # This ensures the exact wording (like previous jokes or explanations) is retained.
    history = state.get("chat_history", [])
    if history:
        for msg in history[-6:]:
            if msg.get("role") == "user":
                lc_messages.append(HumanMessage(content=msg.get("content", "")))
            else:
                from langchain_core.messages import AIMessage
                lc_messages.append(AIMessage(content=msg.get("content", "")))
                
    lc_messages.append(HumanMessage(content=user_input))
    
    response = main_agent_llm.invoke(lc_messages)
    reply_text = response.content
    
    return {"final_response": reply_text, "chat_history": [{"role": "user", "content": user_input}, {"role": "assistant", "content": reply_text}]}
