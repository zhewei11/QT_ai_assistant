import operator
from typing import TypedDict, Annotated

# ==========================================
# 2. LangGraph State
# ==========================================
class AgentState(TypedDict):
    input_text: str                          # user input
    chat_history: Annotated[list, operator.add] # chat history
    route_decision: str                      # route decision (agent, search, or physically_act)
    tool_raw_xml: str                        # raw knowledge from tool (XML format)
    refined_context: str                     # refined knowledge from summarizer
    final_response: str                      # final response to ROS
