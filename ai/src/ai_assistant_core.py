#!/usr/bin/env python3
import zmq
import orjson
import logging
import os
import sys
from typing import TypedDict, Annotated, Sequence, Optional
import operator
from dotenv import load_dotenv

from langgraph.graph import StateGraph, START, END
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langchain_community.tools.tavily_search import TavilySearchResults

# ==========================================
# 0. 基礎設定與環境變數
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AI_Brain")

# 讀取 config/.env 檔案
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', '.env')
load_dotenv(config_path)

# 若有 TAVILYT_API_KEY 的打字錯誤，順便幫忙修正
if os.getenv("TAVILYT_API_KEY"):
    os.environ["TAVILY_API_KEY"] = os.getenv("TAVILYT_API_KEY")

# 初始化 LLM 實例
# (這裡全部先使用 OpenAI 示範，未來你可以把 router_llm 換成 langchain_ollama 的 Llama3)
router_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)      # 路由器：需要高度冷靜與特定格式輸出
summarizer_llm = ChatOpenAI(model="gpt-4o", temperature=0)  # 統整器：只需精煉事實，不需要溫度
main_agent_llm = ChatOpenAI(model="gpt-4o", temperature=0.7)# 主模型：需要負責活潑自然的對話

# ==========================================
# 1. 通訊橋樑 (ZeroMQ)
# ==========================================
class ZMQBridge:
    def __init__(self, pull_port=5555, push_port=5556, test_mode=False):
        self.test_mode = test_mode
        if not test_mode:
            self.context = zmq.Context()
            self.receiver = self.context.socket(zmq.PULL)
            self.receiver.bind(f"tcp://*:{pull_port}")
            
            self.sender = self.context.socket(zmq.PUSH)
            self.sender.connect(f"tcp://127.0.0.1:{push_port}")
            logger.info(f"ZMQ Bridge 已啟動 (PULL={pull_port}, PUSH={push_port})")

    def wait_for_input(self):
        if self.test_mode:
            # Mac 測試模式：直接從終端機輸入代替麥克風
            print("\n" + "="*40)
            text = input("🎤 [Mac 測試模式] 請輸入您想對機器人說的話: ")
            return {"source": "mac_terminal", "text": text, "language": "zh-CN"}
        else:
            msg = self.receiver.recv()
            return orjson.loads(msg)

    def send_action(self, action: str, text: str = "", func_name: str = "", func_args: dict = None):
        payload = {"action": action, "text": text}
        if action == "function":
            payload.update({"function_name": func_name, "function_args": func_args or {}})
            
        if self.test_mode:
            logger.info(f"📤 [Mac 測試模式] 假裝推送指令到實體: {payload}")
        else:
            self.sender.send(orjson.dumps(payload))
            logger.info(f"📤 已推送指令至機器人身體: {payload}")


# ==========================================
# 2. LangGraph 狀態定義 (State)
# ==========================================
class AgentState(TypedDict):
    input_text: str                          # 使用者當前說的話
    chat_history: Annotated[list, operator.add] # 歷史對話紀錄
    route_decision: str                      # 路由指標 (agent, search, or physically_act)
    tool_raw_xml: str                        # 內部工具撈取出的原始知識 (XML形式)
    refined_context: str                     # Summarizer 壓縮後的純淨知識
    final_response: str                      # 準備送給 ROS 說出的話

# ==========================================
# 3. LangGraph 節點架構 (Nodes)
# ==========================================

def router_node(state: AgentState):
    """
    (A) 路由器節點：判斷要對話、搜尋、還是執行實體行為
    採用 Structured Output 來強制 LLM 回傳 JSON 格式的決策
    """
    user_input = state["input_text"]
    logger.info(f"🧭 [Router] 正在評估: {user_input}")
    
    sys_prompt = """你是一個大腦路由分類器，請根據使用者的話判斷他的意圖。
你只能從以下三個類別選一個：
1. 'search'：使用者在詢問事實、天氣、時事或需要外部查證的知識。
2. 'physically_act'：使用者要求機器人做動作(揮手、笑)或調整設定(切換語言、調音量)。
3. 'agent'：單純閒聊、打招呼或前兩者之外的其他對話。

回傳範例： {"route": "search"} 或 {"route": "agent"}
請只回傳合法的 JSON。"""

    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_input)
    ]
    
    # 這裡可以接駁 Llama3 或是 GPT-4o-mini
    response = router_llm.invoke(messages)
    try:
        decision = orjson.loads(response.content)
        route = decision.get("route", "agent")
    except Exception:
        # 如果解析失敗，預設導向聊天 Agent
        route = "agent"
        
    logger.info(f"🧭 [Router] 決定走向: {route}")
    return {"route_decision": route}

def physical_action_node(state: AgentState):
    """
    (B) 實體行為指令節點：判斷具體要做什麼 ROS 動作
    """
    logger.info("🦾 [Action] 判斷為實體行為，準備發送 ROS 指令")
    # 這邊因為要在 Node 外呼叫 ZMQBridge，實務上我們可以把指令寫在 state 中，交給外部執行
    # 這裡我們利用 LLM 簡單抽出參數
    return {"final_response": "<PHYSICAL_ACTION_REQUEST>"}

def tool_web_search_node(state: AgentState):
    """
    (C) 內部知識擴充節點 (真實 Web Search)
    """
    user_input = state["input_text"]
    logger.info(f"🔍 [Tool] 執行外部知識檢索: {user_input}")
    
    try:
        # 使用 LangChain 的 Tavily 工具
        search = TavilySearchResults(max_results=3)
        results = search.invoke({"query": user_input})
        
        # 將搜尋結果打包為生硬的 XML
        xml_content = "<xml>\n"
        if isinstance(results, list):
            for i, res in enumerate(results):
                xml_content += f"<result_{i+1}>\n"
                xml_content += f"<content>{res.get('content', '')}</content>\n"
                xml_content += f"</result_{i+1}>\n"
        else:
            xml_content += f"<content>{str(results)}</content>\n"
        xml_content += "</xml>"
        
    except Exception as e:
        logger.error(f"Tavily 搜尋失敗: {e}")
        xml_content = f"<xml><error>搜尋失敗: {str(e)}</error></xml>"
        
    return {"tool_raw_xml": xml_content}

def summarizer_node(state: AgentState):
    """
    (D) 知識壓縮節點 (Summarizer)：過濾生硬的 XML
    """
    raw_xml = state.get("tool_raw_xml", "")
    logger.info("🗜️ [Summarizer] 壓縮上下文避免主模型幻覺...")
    
    prompt = f"請勿加上個人意見，將以下 XML 資料用一句話總結其核心知識：\n{raw_xml}"
    response = summarizer_llm.invoke([HumanMessage(content=prompt)])
    refined_context = response.content
    
    logger.info(f"🗜️ [Summarizer] 提煉結果: {refined_context}")
    return {"refined_context": refined_context}

def main_agent_node(state: AgentState):
    """
    (E) 終端主模型節點
    """
    user_input = state["input_text"]
    context = state.get("refined_context", "")
    logger.info("🧠 [Agent] 主 LLM 綜合思考中產生回覆...")
    
    sys_prompt = "你是一個熱情、體貼的 QTrobot 語音助理。請用簡短、活潑口吻的一句話回答使用者。"
    if context:
        sys_prompt += f"\n\n參考外部知識：{context}"
        
    messages = state.get("chat_history", [])[-4:] # 取出最後四句歷史對話
    messages.insert(0, {"role": "system", "content": sys_prompt})
    messages.append({"role": "user", "content": user_input})
    
    # 轉換成 LangChain Message 格式
    lc_messages = []
    for msg in messages:
        if msg["role"] == "system": lc_messages.append(SystemMessage(content=msg["content"]))
        elif msg["role"] == "user": lc_messages.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant": lc_messages.append(AIMessage(content=msg["content"]))
    
    response = main_agent_llm.invoke(lc_messages)
    reply_text = response.content
    
    return {"final_response": reply_text, "chat_history": [{"role": "user", "content": user_input}, {"role": "assistant", "content": reply_text}]}


# ==========================================
# 4. 路徑條件判斷 (Edges)
# ==========================================
def route_after_router(state: AgentState) -> str:
    decision = state.get("route_decision", "agent")
    if decision == "search": return "tool_search"
    if decision == "physically_act": return "physical_action"
    return "main_agent"


# ==========================================
# 5. LangGraph 圖譜組裝
# ==========================================
def build_graph():
    workflow = StateGraph(AgentState)
    
    # 加入節點
    workflow.add_node("router", router_node)
    workflow.add_node("physical_action", physical_action_node)
    workflow.add_node("tool_search", tool_web_search_node)
    workflow.add_node("summarizer", summarizer_node)
    workflow.add_node("main_agent", main_agent_node)
    
    # 定義連接圖 (Edges)
    workflow.add_edge(START, "router")
    
    # 根據 Router 結果決定去哪
    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {
            "tool_search": "tool_search",
            "physical_action": "physical_action",
            "main_agent": "main_agent"
        }
    )
    
    # 如果走知識檢索路線，就去找 Summarizer 再去 主 Agent
    workflow.add_edge("tool_search", "summarizer")
    workflow.add_edge("summarizer", "main_agent")
    
    # 如果是終點
    workflow.add_edge("main_agent", END)
    workflow.add_edge("physical_action", END)
    
    return workflow.compile()

# 為配合 LangGraph Studio (langgraph dev)，將編譯好的圖宣告於模組層級
app = build_graph()

# ==========================================
# 6. 系統啟動循環
# ==========================================
if __name__ == "__main__":
    # 若在 Mac 上單獨執行，可加上 '--test' 參數進入無 ZMQ 測試模式
    is_test_mode = "--test" in sys.argv
    
    if not os.environ.get("OPENAI_API_KEY"):
        logger.warning("未偵測到 OPENAI_API_KEY，請確認 ai/config/.env 是否已正確填寫！")
    
    bridge = ZMQBridge(pull_port=5555, push_port=5556, test_mode=is_test_mode)
    
    logger.info("🤖 LangGraph AI 大腦已編譯並啟動！")
    
    # 初始化一個空的狀態記憶
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
            # 1. 攔截語音輸入
            incoming_data = bridge.wait_for_input()
            text = incoming_data.get("text", "")
            
            if not text:
                continue
                
            # 2. 清理過期變數並送入大腦思考
            # 注意：這裡保留 chat_history，其他狀態先清空重置
            current_state["input_text"] = text
            current_state["tool_raw_xml"] = ""
            current_state["refined_context"] = ""
            current_state["final_response"] = ""
            
            logger.info("="*40)
            logger.info(f"🗣️ 開始處理對話: {text}")
            
            # 執行狀態機 (狀態機會依序印出日誌)
            final_state = app.invoke(current_state)
            
            # 將最新狀態寫回 current_state (為了保留聊天記憶)
            current_state["chat_history"] = final_state.get("chat_history", current_state["chat_history"])
            
            # 3. 處理狀態機發出的決策，並轉發給 ROS
            response_text = final_state.get("final_response", "")
            
            if response_text == "<PHYSICAL_ACTION_REQUEST>":
                # 這裡為了簡單示範，我們直接把所有動作需求轉為笑臉
                bridge.send_action(action="function", func_name="emotionShow", func_args={"emotion": "QT/happy"})
            elif response_text:
                # 一般開口講話
                bridge.send_action(action="talk", text=response_text)
                
    except KeyboardInterrupt:
        logger.info("\nAI 大腦關閉中...")
    finally:
        if not is_test_mode:
            bridge.receiver.close()
            bridge.sender.close()
            bridge.context.term()
