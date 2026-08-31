from state import AgentState
from config import summarizer_llm, logger
from langchain_core.messages import HumanMessage
import re


MEMORY_TRIGGER_PATTERNS = [
    r"記住",
    r"請記得",
    r"remember",
    r"my name is",
    r"我的名字",
    r"我叫",
    r"我是",
    r"我喜歡",
    r"我不喜歡",
    r"我偏好",
    r"我的.*(偏好|習慣|目標|工作|家人|症狀|疾病|病史|藥|過敏)",
    r"我有.*(高血壓|糖尿病|心臟|心律|過敏|胸痛|頭暈|症狀|病史)",
    r"i like",
    r"i prefer",
    r"i am",
    r"i have",
    r"my .*(preference|habit|goal|job|family|symptom|condition|medication|allergy)",
]

LOW_VALUE_PATTERNS = [
    r"^(你好|嗨|哈囉|早安|午安|晚安)[！!。,.，\s]*$",
    r"^(hello|hi|hey)\b[!.,\s]*$",
    r"(天氣|weather|temperature|氣溫|下雨|forecast)",
    r"(幾點|現在時間|today|今天日期|date|time)",
    r"(換.*(語音|語言)|調.*音量|音量|做動作|揮手|點頭|跳舞|表情)",
]

ACTION_BLOCK_RE = re.compile(r"<PHYSICAL_ACTION_REQUEST>.*?</PHYSICAL_ACTION_REQUEST>", re.DOTALL)


def _strip_action_blocks(text):
    return ACTION_BLOCK_RE.sub("", text or "").strip()


def _matches_any(text, patterns):
    normalized = (text or "").strip().lower()
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)


def _is_memorable_turn(user_text, assistant_text):
    user_text = _strip_action_blocks(user_text)
    assistant_text = _strip_action_blocks(assistant_text)

    if not user_text:
        return False
    if _matches_any(user_text, LOW_VALUE_PATTERNS):
        return False
    if _matches_any(user_text, MEMORY_TRIGGER_PATTERNS):
        return True

    # Longer reflective or medical/personal context can still be worth retaining.
    if len(user_text) >= 40 and _matches_any(
        user_text,
        [
            r"(因為|所以|最近|通常|每次|長期|以前|目前|希望|擔心)",
            r"(健康|症狀|醫師|藥物|運動|睡眠|壓力|飲食)",
            r"(because|usually|recently|currently|hope|worry|health|symptom|doctor|medicine|exercise|sleep|diet)",
        ],
    ):
        return True

    return False


def _collect_memorable_turns(history):
    memorable_turns = []
    idx = 0
    while idx < len(history):
        msg = history[idx]
        if msg.get("role") != "user":
            idx += 1
            continue

        user_text = msg.get("content", "")
        assistant_text = ""
        if idx + 1 < len(history) and history[idx + 1].get("role") == "assistant":
            assistant_text = history[idx + 1].get("content", "")

        if _is_memorable_turn(user_text, assistant_text):
            memorable_turns.append((user_text, assistant_text))
        idx += 2

    return memorable_turns

def memory_compress_node(state: AgentState):
    """
    memory_compress_node: compresses dialogue history when it exceeds a threshold
    """
    history = state.get("chat_history", [])
    
    # Compress when the history grows past a few turns.
    if len(history) < 5:
        return {}
        
    logger.info("[Memory] Dialogue history exceeds threshold. Compressing memory...")
    
    old_summary = state.get("memory_summary", "")
    memorable_turns = _collect_memorable_turns(history)
    if not memorable_turns:
        logger.info("[Memory] No memorable turns found; keeping recent context only.")
        return {"chat_history": history[-2:]}

    prompt = f"Previous summary: {old_summary}\n\nRecent conversation:\n"
    
    for user_text, assistant_text in memorable_turns:
        prompt += f"user: {_strip_action_blocks(user_text)}\n"
        if assistant_text:
            prompt += f"assistant: {_strip_action_blocks(assistant_text)}\n"
        
    prompt += (
        "\nUpdate the long-term memory for this voice assistant. Keep only durable information: "
        "the user's identity, preferences, recurring needs, goals, important personal context, "
        "and stable health-related facts they explicitly shared. Exclude greetings, weather/current-event questions, "
        "one-off commands, robot action tags, and temporary small talk. If the previous summary already contains a fact, "
        "deduplicate it. Write a concise summary."
    )
    
    try:
        response = summarizer_llm.invoke([HumanMessage(content=prompt)])
        new_summary = response.content
        logger.info(f"[Memory] Compressed memory summary: {new_summary}")
        
        # Keep the latest 2 messages to maintain immediate dialogue flow
        return {"memory_summary": new_summary, "chat_history": history[-2:]}
    except Exception as e:
        logger.error(f"[Memory] Compression failed: {e}")
        return {}
