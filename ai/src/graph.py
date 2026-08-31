from langgraph.graph import StateGraph, START, END
from state import AgentState
from nodes import (
    router_node,
    ecg_result_node,
    medical_safety_node,
    medical_personal_node,
    medical_education_node,
    system_control_node,
    tool_web_search_node,
    rag_search_node,
    summarizer_node,
    main_agent_node
)

# ==========================================
# 4. route after router (Edges)
# ==========================================
def route_after_router(state: AgentState) -> str:
    decision = state.get("route_decision", "agent")
    if decision == "search": return "tool_search"
    if decision == "rag_search": return "rag_search"
    if decision == "system_control": return "system_control"
    if decision == "ecg_result": return "ecg_result"
    if decision == "medical_safety": return "medical_safety"
    if decision == "medical_personal": return "medical_personal"
    if decision == "medical_education": return "medical_education"
    return "main_agent"

# ==========================================
# 5. build graph
# ==========================================
def build_graph():
    workflow = StateGraph(AgentState)
    
    # add nodes
    workflow.add_node("router", router_node)
    workflow.add_node("ecg_result", ecg_result_node)
    workflow.add_node("medical_safety", medical_safety_node)
    workflow.add_node("medical_personal", medical_personal_node)
    workflow.add_node("medical_education", medical_education_node)
    workflow.add_node("system_control", system_control_node)
    workflow.add_node("tool_search", tool_web_search_node)
    workflow.add_node("rag_search", rag_search_node)
    workflow.add_node("summarizer", summarizer_node)
    workflow.add_node("main_agent", main_agent_node)
    
    # define edges
    workflow.add_edge(START, "router")
    
    # according to router result, decide where to go
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "tool_search": "tool_search",
            "rag_search": "rag_search",
            "system_control": "system_control",
            "ecg_result": "ecg_result",
            "medical_safety": "medical_safety",
            "medical_personal": "medical_personal",
            "medical_education": "medical_education",
            "main_agent": "main_agent"
        }
    )
    
    # if tool search or rag search route, then go to summarizer and then main agent
    workflow.add_edge("tool_search", "summarizer")
    workflow.add_edge("rag_search", "summarizer")
    workflow.add_edge("summarizer", "main_agent")
    
    # if main agent or physical action, then go to end
    workflow.add_edge("ecg_result", END)
    workflow.add_edge("medical_safety", END)
    workflow.add_edge("medical_personal", END)
    workflow.add_edge("medical_education", END)
    workflow.add_edge("main_agent", END)
    workflow.add_edge("system_control", END)
    
    return workflow.compile()
