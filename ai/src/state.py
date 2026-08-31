import operator
from typing import TypedDict, Annotated

# ==========================================
# 2. LangGraph State
# ==========================================
class AgentState(TypedDict):
    input_text: str                          # user input
    chat_history: list                       # chat history (no operator.add, manual overwrite)
    memory_summary: str                      # long-term memory generic summary
    route_decision: str                      # route decision (agent, search, or physically_act)
    tool_raw_xml: str                        # raw knowledge from tool (XML format)
    rag_evidence_status: str                 # none, weak, or sufficient
    rag_max_relevance: float                 # max local FAISS relevance score
    rag_source_count: int                    # total retrieved source count
    medical_risk_level: str                  # education, personal, or high for medical requests
    refined_context: str                     # refined knowledge from summarizer
    final_response: str                      # final response to ROS
    language: str                            # current language ('zh-TW' or 'en-US')
    ai_latency: dict                         # per-node AI latency diagnostics
    ecg_measurement: dict                    # latest 60-second ECG session snapshot
