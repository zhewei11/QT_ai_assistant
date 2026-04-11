from langgraph.graph import StateGraph, START, END
from state import AgentState
from memory import memory_compress_node
from nodes import (
    router_node,
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
    return "main_agent"

# ==========================================
# 5. build graph
# ==========================================
def build_graph():
    workflow = StateGraph(AgentState)
    
    # add nodes
    workflow.add_node("memory_compress", memory_compress_node)
    workflow.add_node("router", router_node)
    workflow.add_node("system_control", system_control_node)
    workflow.add_node("tool_search", tool_web_search_node)
    workflow.add_node("rag_search", rag_search_node)
    workflow.add_node("summarizer", summarizer_node)
    workflow.add_node("main_agent", main_agent_node)
    
    # define edges
    workflow.add_edge(START, "memory_compress")
    workflow.add_edge("memory_compress", "router")
    
    # according to router result, decide where to go
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "tool_search": "tool_search",
            "rag_search": "rag_search",
            "system_control": "system_control",
            "main_agent": "main_agent"
        }
    )
    
    # if tool search or rag search route, then go to summarizer and then main agent
    workflow.add_edge("tool_search", "summarizer")
    workflow.add_edge("rag_search", "summarizer")
    workflow.add_edge("summarizer", "main_agent")
    
    # if main agent or physical action, then go to end
    workflow.add_edge("main_agent", END)
    workflow.add_edge("system_control", END)
    
    return workflow.compile()
