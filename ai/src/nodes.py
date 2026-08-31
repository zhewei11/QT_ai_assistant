import orjson
import re
import time
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_community.utilities import GoogleSerperAPIWrapper
from state import AgentState
from config import router_llm, summarizer_llm, medical_education_llm, main_agent_llm, logger
from ecg_context import format_ecg_context
from rag_engine import rag_engine


ANSWER_CACHE_TTL_SECONDS = 3600
ANSWER_CACHE: dict[str, tuple[float, str]] = {}
VERIFIED_GESTURE_NAMES = [
    "QT/swipe_right",
    "QT/clapping",
    "QT/one-arm-up",
    "QT/hi",
    "QT/point_front",
    "QT/neutral",
    "QT/angry",
    "QT/up_right",
    "QT/show_tablet",
    "QT/show_QT",
    "QT/kiss",
    "QT/peekaboo",
    "QT/train",
    "QT/Show-face",
    "QT/bored",
    "QT/challenge",
    "QT/breathing_exercise",
    "QT/personal-distance",
    "QT/sad",
    "QT/happy",
    "QT/show_right",
    "QT/bye-bye",
    "QT/yawn",
    "QT/hand-front-hold",
    "QT/touch-head",
    "QT/bye",
    "QT/drink",
    "QT/show_left",
    "QT/sneezing",
    "QT/send_kiss",
    "QT/surprise",
    "QT/monkey",
    "QT/peekaboo-back",
    "QT/touch-head-back",
    "QT/stretching",
    "QT/up_left",
    "QT/swipe_left",
]
VERIFIED_GESTURE_PROMPT = ", ".join(VERIFIED_GESTURE_NAMES)

LANGUAGE_COMMAND_PATTERNS = [
    r"切換.*(英文|英語|english)|改成.*(英文|英語|english)|換成.*(英文|英語|english)|說英文|用英文|switch.*english|change.*english",
    r"切換.*(中文|國語|華語|chinese)|改成.*(中文|國語|華語|chinese)|換成.*(中文|國語|華語|chinese)|說中文|用中文|switch.*chinese|change.*chinese",
]

ANSWER_PAUSE_COMMAND_PATTERNS = [
    r"(暫停|停止|不要|先不要).*(回答|回覆|回應|說話)",
    r"(回答|回覆|回應|說話).*(暫停|停止|關閉)",
    r"(pause|stop|disable).*(answering|responding|response|replying|speaking)",
]

ANSWER_RESUME_COMMAND_PATTERNS = [
    r"(恢復|開始|可以|繼續).*(回答|回覆|回應|說話)",
    r"(回答|回覆|回應|說話).*(恢復|開始|打開|開啟|繼續)",
    r"(resume|start|enable).*(answering|responding|response|replying|speaking)",
]

MIC_PAUSE_COMMAND_PATTERNS = [
    r"(暫停|停止|關閉|不要).*(收音|麥克風|聽我|聽到|錄音)",
    r"(收音|麥克風|錄音).*(暫停|停止|關閉)",
    r"(pause|stop|mute|disable).*(microphone|mic|listening|audio input)",
]

MIC_RESUME_COMMAND_PATTERNS = [
    r"(恢復|開始|打開|開啟).*(收音|麥克風|聽我|聽到|錄音)",
    r"(收音|麥克風|錄音).*(恢復|開始|打開|開啟)",
    r"(resume|start|unmute|enable).*(microphone|mic|listening|audio input)",
]

ECG_MEASUREMENT_COMMAND_PATTERNS = [
    r"(再|重新|重).*(測|量).*(心電|心跳|心率)|再測一次|再量一次",
    r"(開始|進行|做|作|連測).*(心電圖|心電|ECG|EKG).*(測量|量測|檢測|測試|檢查)?",
    r"(我要|想要|需要|幫我|請).*(測量|量測|檢測|測試|檢查|測|量|做|作|連測).*(心電圖|心電|心跳|心率|ECG|EKG)",
    r"(我要|想要|需要|幫我|請).*(心電圖|心電|ECG|EKG).*(測量|量測|檢測|測試|檢查|測|量|做|作|連測)",
    r"(measure|record|run|start).*(ECG|heart rate|heartbeat|easy).*(again|measurement|test)?",
    r"(repeat|redo).*(ECG|heart rate).*(measurement|test)?",
]

ECG_MEASUREMENT_TERMS = [
    "測量",
    "测量",
    "量測",
    "量测",
    "檢測",
    "检测",
    "測試",
    "测试",
    "檢查",
    "检查",
    "測",
    "测",
    "量",
    "做",
    "作",
    "連測",
    "连测",
    "measure",
    "record",
    "start",
    "run",
]

ECG_TARGET_TERMS = [
    "心電圖",
    "心电图",
    "心電",
    "心电",
    "心跳",
    "心率",
    "ecg",
    "ekg",
    "heart rate",
]

COMMAND_NORMALIZATION_TABLE = str.maketrans({
    "帮": "幫",
    "请": "請",
    "测": "測",
    "电": "電",
    "图": "圖",
    "检": "檢",
    "连": "連",
    "刚": "剛",
    "结": "結",
    "过": "過",
    "脏": "臟",
    "难": "難",
    "气": "氣",
    "现": "現",
    "显": "顯",
    "数": "數",
    "据": "據",
    "报": "報",
    "觉": "覺",
    "吗": "嗎",
    "该": "該",
    "么": "麼",
    "后": "後",
    "点": "點",
    "绞": "絞",
    "闷": "悶",
    "暂": "暫",
    "关": "關",
    "闭": "閉",
    "麦": "麥",
    "风": "風",
    "听": "聽",
    "录": "錄",
    "开": "開",
    "启": "啟",
    "复": "復",
    "继": "繼",
    "续": "續",
})

GREETING_PATTERNS = [
    r"^(你好|嗨|哈囉|早安|午安|晚安)[！!。,.，\s]*$",
    r"^(hello|hi|hey)\b[!.,\s]*$",
]

JOKE_PATTERNS = [
    r"笑話|冷笑話|講.*笑|說.*笑|逗我笑|好笑的故事",
    r"\b(joke|jokes|funny joke|tell me a joke)\b",
]

WEATHER_OR_FACT_PATTERNS = [
    r"天氣|weather|temperature|氣溫|下雨|forecast",
    r"幾點|現在時間|今天日期|date|time",
]

MEDICAL_KEYWORD_PATTERNS = [
    r"心臟|心跳|心率|心律|心電|血壓|糖尿病|胸痛|胸悶|呼吸困難|頭暈|昏倒|症狀|疾病|藥|醫師|醫療|健康",
    r"heart|cardiac|ECG|BPM|HRV|RMSSD|pNN50|blood pressure|diabetes|chest pain|symptom|disease|medicine|doctor|health",
]

HIGH_RISK_MEDICAL_PATTERNS = [
    r"胸痛|胸悶|胸口悶|呼吸困難|喘不過氣|昏倒|昏厥|失去意識",
    r"(心臟|胸口|胸部).*(痛|絞痛|悶|不舒服)",
    r"(很喘|喘得厲害|喘.*(心臟|胸口|胸部).*不舒服|(心臟|胸口|胸部).*不舒服.*喘)",
    r"單側無力|臉歪|口齒不清|說話不清|劇烈頭痛|中風",
    r"心肌梗塞|心臟病發|突然.*心悸|嚴重.*心悸",
    r"自殺|想死|傷害自己",
    r"chest pain|shortness of breath|fainting|loss of consciousness",
    r"one-sided weakness|face drooping|slurred speech|stroke|heart attack",
    r"suicide|kill myself|harm myself",
]

PERSONAL_MEDICAL_PATTERNS = [
    r"我.*(痛|不舒服|症狀|發燒|咳嗽|頭暈|胸悶|心悸|喘|麻|無力|吃藥|用藥|該怎麼辦)",
    r"我的.*(症狀|血壓|心跳|心率|檢查|報告|藥|病|疼痛)",
    r"(我|我的).*(是不是|會不會|要不要|可不可以|能不能|怎麼辦|嚴重嗎)",
    r"(最近|現在|剛剛|今天).*(痛|不舒服|頭暈|胸悶|心悸|喘|發燒)",
    r"\b(i|my)\b.*(pain|symptom|fever|dizzy|dizziness|chest|palpitation|medicine|medication|should i|what should i do)",
]

EDUCATIONAL_MEDICAL_PATTERNS = [
    r"什麼是|為什麼|原因|介紹|解釋|科普|差別|如何運作|機制",
    r"what is|why|explain|introduction|overview|difference|how does|mechanism",
]

ECG_RESULT_PATTERNS = [
    r"^\s*(請|幫我|麻煩)?\s*(查看|顯示|看看|看一下|說明|讀取|告訴我)?\s*(剛才|剛剛|目前|最新|這次)?\s*(的)?\s*(量測|測量|檢測|測試)?\s*(結果|數據|數值|報告|紀錄)\s*(是多少|怎麼樣|如何)?[，。！？,.!?\s]*$",
    r"^\s*(show|display|read|tell me)?\s*(the\s*)?(latest|recent|current)?\s*(measurement\s*)?(result|results|data|report)\s*$",
    r"(顯示|查看|看看|讀取|說明|告訴我|報告).*(心電圖|心電|ECG|EKG).*(結果|數據|數值|報告|紀錄)",
    r"(心電圖|心電|ECG|EKG).*(量測|測量|檢測|測試|檢查)?.*(結果|數據|數值|報告|紀錄)",
    r"(我|我的|目前|現在|剛才|剛剛|這次).*(心跳|心率|心電圖|心電|BPM|HRV|RMSSD|pNN50|R波|測量|量測|檢測).*(多少|結果|數值|怎麼樣|如何|狀況|狀態)",
    r"(心跳|心率|心電圖|心電|BPM|HRV|RMSSD|pNN50|R波|測量|檢測).*(多少|結果|數值|怎麼樣|如何)",
    r"(我|這個人|目前這個人).*(有沒有|是否|是不是).*(測過|量過).*(心電|心跳|心率|ECG)",
    r"(my|current|latest|recent).*(heart rate|ECG|BPM|HRV|RMSSD|pNN50|R[- ]?peak|measurement|result)",
    r"(have i|has this person).*(measured|recorded).*(ECG|heart rate)",
    r"rsvp\s*wave.*(result|measurement|結果|數值)",
]


def _is_high_risk_medical(text: str) -> bool:
    normalized = _normalize_command_text(text).lower()
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in HIGH_RISK_MEDICAL_PATTERNS)


def _classify_medical_risk(text: str) -> str:
    normalized = _normalize_command_text(text)
    if _is_high_risk_medical(normalized):
        return "high"
    if _matches_any(normalized, PERSONAL_MEDICAL_PATTERNS):
        return "personal"
    if _matches_any(normalized, EDUCATIONAL_MEDICAL_PATTERNS):
        return "education"
    return "education"


def _is_language_command(text: str) -> bool:
    normalized = text or ""
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in LANGUAGE_COMMAND_PATTERNS)


def _normalize_command_text(text: str) -> str:
    return (text or "").translate(COMMAND_NORMALIZATION_TABLE)


def _is_answer_pause_command(text: str) -> bool:
    normalized = _normalize_command_text(text)
    return _matches_any(normalized, ANSWER_PAUSE_COMMAND_PATTERNS)


def _is_answer_resume_command(text: str) -> bool:
    normalized = _normalize_command_text(text)
    return _matches_any(normalized, ANSWER_RESUME_COMMAND_PATTERNS)


def _is_mic_pause_command(text: str) -> bool:
    normalized = _normalize_command_text(text)
    return _matches_any(normalized, MIC_PAUSE_COMMAND_PATTERNS)


def _is_mic_resume_command(text: str) -> bool:
    normalized = _normalize_command_text(text)
    return _matches_any(normalized, MIC_RESUME_COMMAND_PATTERNS)


def _extract_mic_pause_seconds(text: str, default_seconds: int = 10) -> int:
    normalized = _normalize_command_text(text)
    match = re.search(r"(\d+)\s*(秒|seconds?|s)(?:\b|$)", normalized, re.IGNORECASE)
    if match:
        return max(1, min(int(match.group(1)), 120))
    return default_seconds


def _is_ecg_measurement_command(text: str) -> bool:
    normalized_text = _normalize_command_text(text)
    if _is_ecg_result_question(normalized_text):
        return False
    if _matches_any(normalized_text, ECG_MEASUREMENT_COMMAND_PATTERNS):
        return True
    normalized = re.sub(r"[\s，。！？、,.!?：:；;「」\"'()（）\[\]{}]", "", normalized_text).lower()
    has_measure_action = any(term in normalized for term in ECG_MEASUREMENT_TERMS)
    has_ecg_target = any(term.replace(" ", "") in normalized for term in ECG_TARGET_TERMS)
    return has_measure_action and has_ecg_target


def _matches_any(text: str, patterns: list[str]) -> bool:
    normalized = text or ""
    return any(re.search(pattern, normalized, re.IGNORECASE) for pattern in patterns)


def _is_ecg_result_question(text: str) -> bool:
    return _matches_any(_normalize_command_text(text), ECG_RESULT_PATTERNS)


def _ecg_measurement_response(language: str, measurement: dict) -> str:
    status = measurement.get("status")
    status_responses = {
        "waiting_device": {
            "zh-TW": "目前正在等待手機與心電裝置建立藍牙連線，六十秒倒數尚未開始。",
            "en-US": "The system is waiting for the phone to connect to the ECG device; the 60-second timer has not started.",
        },
        "waiting_signal": {
            "zh-TW": "目前已收到心電資料，正在確認 ECG 品質、R 波與 RR 間期；確認穩定後才會開始六十秒倒數。",
            "en-US": "ECG data is arriving and the system is validating signal quality, R peaks, and R-R intervals; the 60-second timer will start afterward.",
        },
        "measuring": {
            "zh-TW": "目前正在進行六十秒心電量測，請保持裝置接觸並維持靜止。",
            "en-US": "The 60-second ECG measurement is in progress. Please keep the device in contact and remain still.",
        },
        "signal_timeout": {
            "zh-TW": "這次沒有在等待時間內確認穩定 ECG 訊號，請確認藍牙連線與電極接觸後重新量測。",
            "en-US": "No stable ECG signal was confirmed before timeout. Check Bluetooth and electrode contact, then measure again.",
        },
        "stream_lost": {
            "zh-TW": "量測期間心電資料流中斷，這次結果不會用於判讀，請確認連線後重新量測。",
            "en-US": "The ECG stream stopped during measurement, so this session will not be interpreted. Reconnect and measure again.",
        },
        "no_current_face": {
            "zh-TW": "目前沒有穩定偵測到你的人臉，所以我不會套用其他人的心電紀錄。請面向機器人後再詢問，或直接說要開始量測心電圖。",
            "en-US": "I do not currently see a stable face slot, so I will not reuse another person's ECG record. Please face the robot or ask to start an ECG measurement.",
        },
        "no_person_measurement": {
            "zh-TW": "目前這個人臉槽還沒有心電量測紀錄。你可以直接說開始量測心電圖，我會在確認穩定 ECG 訊號後開始六十秒量測。",
            "en-US": "The current face slot has no ECG measurement yet. You can ask me to start ECG measurement; the 60-second timer begins after a stable ECG signal is confirmed.",
        },
        "person_measurement_stale": {
            "zh-TW": "目前這個人曾經有心電量測紀錄，但資料已超過有效時間。我建議重新量測一次再回答目前狀態。",
            "en-US": "The current face slot has an ECG record, but it is stale. Please repeat the measurement before using it for the current status.",
        },
    }
    if status in status_responses:
        return status_responses[status].get(language, status_responses[status]["zh-TW"])

    metrics = measurement.get("metrics") or {}
    analysis = measurement.get("arrhythmia_analysis") or {}
    quality = analysis.get("signal_quality") or {}
    labels = analysis.get("rhythm_labels") or []
    scores = analysis.get("screening_scores") or {}
    bpm = metrics.get("bpm")
    rmssd = metrics.get("rmssd_ms")
    pnn50 = metrics.get("pnn50_percent")
    irregularity = metrics.get("arrhythmia_indicator_percent")
    model_arrhythmia = measurement.get("model_arrhythmia") or {}

    label_names_zh = {
        "regular_rhythm_pattern": "規則心律型態",
        "irregular_rhythm_pattern": "不規則心律型態",
        "possible_af_pattern": "疑似心房顫動型態",
        "frequent_premature_pattern": "頻繁早期搏動型態",
        "tachycardia_pattern": "心搏過速型態",
        "bradycardia_pattern": "心搏過緩型態",
    }
    label_names_en = {
        "regular_rhythm_pattern": "regular rhythm pattern",
        "irregular_rhythm_pattern": "irregular rhythm pattern",
        "possible_af_pattern": "possible AF-like pattern",
        "frequent_premature_pattern": "frequent premature-beat pattern",
        "tachycardia_pattern": "tachycardia pattern",
        "bradycardia_pattern": "bradycardia pattern",
    }

    def ybc_confidence_text(target_labels=None) -> str:
        confidence = model_arrhythmia.get("mean_confidence") or {}
        if not isinstance(confidence, dict) or not confidence:
            return ""
        labels_to_use = target_labels or ["N"]
        values = [
            float(confidence[label])
            for label in labels_to_use
            if label in confidence and isinstance(confidence[label], (int, float))
        ]
        if not values:
            return ""
        return f"{sum(values) / len(values) * 100:.1f}%"

    if language == "en-US":
        rhythm_text = ", ".join(label_names_en.get(label, label) for label in labels) or "unclassified rhythm"
        if quality.get("label") == "poor" or measurement.get("status") == "low_quality":
            return "The ECG signal was too noisy to screen reliably. Please repeat the measurement with stable contact."
        response = f"Latest ECG: {bpm} BPM, {rhythm_text}, irregularity score {scores.get('irregular_rhythm', 0)}. "
        if model_arrhythmia.get("status") == "complete":
            abnormal_percent = model_arrhythmia.get("abnormal_beat_percent", 0)
            if model_arrhythmia.get("arrhythmia_detected"):
                labels_text = ", ".join(model_arrhythmia.get("abnormal_labels") or [])
                response += f"The YBC beat model flagged {abnormal_percent}% abnormal beats"
                response += f" ({labels_text})" if labels_text else ""
                confidence_text = ybc_confidence_text(model_arrhythmia.get("abnormal_labels") or [])
                response += f", with average model confidence {confidence_text}" if confidence_text else ""
                response += ". "
            else:
                confidence_text = ybc_confidence_text(["N"])
                response += f"The YBC beat model did not flag clear abnormal beats ({abnormal_percent}%)"
                response += f"; normal-beat average confidence was {confidence_text}" if confidence_text else ""
                response += ". "
        return response + "This is a screening result, not a diagnosis."

    rhythm_text = "、".join(label_names_zh.get(label, label) for label in labels) or "無法分類"
    if quality.get("label") == "poor" or measurement.get("status") == "low_quality":
        return "這次心電訊號品質不足，無法可靠篩檢，請確認電極接觸後重新量測。"
    response = f"剛剛心電篩檢心率 {bpm} BPM，節律顯示{rhythm_text}，不規則篩檢分數 {scores.get('irregular_rhythm', 0)}。"
    if model_arrhythmia.get("status") == "complete":
        abnormal_percent = model_arrhythmia.get("abnormal_beat_percent", 0)
        if model_arrhythmia.get("arrhythmia_detected"):
            labels_text = "、".join(model_arrhythmia.get("abnormal_labels") or [])
            response += f"YBC 模型篩檢偵測到疑似異常搏動 {abnormal_percent}%"
            response += f"（{labels_text}）" if labels_text else ""
            confidence_text = ybc_confidence_text(model_arrhythmia.get("abnormal_labels") or [])
            response += f"，平均模型信心值 {confidence_text}" if confidence_text else ""
            response += "。"
        else:
            confidence_text = ybc_confidence_text(["N"])
            response += f"YBC 模型未偵測到明顯異常搏動（{abnormal_percent}%）"
            response += f"，正常搏動平均信心值 {confidence_text}" if confidence_text else ""
            response += "。"
    return response + "這只是篩檢結果，不是診斷。"


def _latency_snapshot(state: AgentState) -> dict:
    return dict(state.get("ai_latency") or {})


def _with_latency(state: AgentState, updates: dict, node_name: str, started_at: float, **extra) -> dict:
    latency = _latency_snapshot(state)
    latency[f"{node_name}_ms"] = round((time.monotonic() - started_at) * 1000, 1)
    latency.update(extra)
    updates["ai_latency"] = latency
    return updates


def _map_language_command(text: str):
    normalized = text or ""
    if re.search(
        r"英文|英語|english|en[-_ ]?us",
        normalized,
        re.IGNORECASE,
    ):
        return {
            "action_type": "function",
            "func_name": "setLanguage",
            "func_args": {"lang_code": "en-US", "pitch": 100, "speed": 100},
        }, "en-US"

    if re.search(
        r"中文|國語|華語|chinese|zh[-_ ]?(ma|cn|tw)",
        normalized,
        re.IGNORECASE,
    ):
        return {
            "action_type": "function",
            "func_name": "setLanguage",
            "func_args": {"lang_code": "zh-TW", "pitch": 100, "speed": 100},
        }, "zh-TW"

    return None, None


def _safe_medical_response(language: str, risk_level: str, evidence_status: str) -> str:
    if language == "en-US":
        if risk_level == "high":
            return (
                "Your symptoms may be urgent. Please seek emergency care now or call local emergency services; "
                "I cannot diagnose this safely by conversation."
            )
        if evidence_status == "none":
            return "I do not have enough reliable medical evidence to answer safely. Please ask a healthcare professional."
        return "The retrieved medical evidence is too weak for a safe answer. Please rephrase the question or consult a clinician."

    if risk_level == "high":
        return "你描述的狀況可能需要緊急處理，請立刻聯絡當地急救或就醫；我無法用對話安全地診斷。"
    if evidence_status == "none":
        return "目前沒有足夠可靠的醫療資料可以安全回答，建議詢問專業醫療人員。"
    return "目前檢索到的醫療證據不足，無法安全回答；請換個方式描述問題，或諮詢醫療人員。"


def _personal_medical_response(language: str) -> str:
    if language == "en-US":
        return (
            "I can explain general health information, but I cannot diagnose your personal condition. "
            "If symptoms are ongoing, worsening, or worrying, please contact a healthcare professional."
        )
    return (
        "我可以說明一般健康資訊，但不能判斷你的個人診斷。"
        "如果症狀持續、變嚴重或讓你擔心，請詢問醫療專業人員。"
    )


def _medical_education_template(language: str, question: str):
    normalized = _normalize_command_text(question).lower()
    is_en = language == "en-US"

    templates = [
        (
            r"心律不整|心律失常|arrhythmia|irregular heartbeat",
            (
                "Arrhythmia means the heartbeat rhythm is too fast, too slow, or irregular. It is a broad screening concept; symptoms like chest pain, fainting, or shortness of breath need medical care."
                if is_en
                else "心律不整是指心跳節律太快、太慢或不規則，是一個廣泛概念；若合併胸痛、昏倒或喘不過氣，應盡快就醫。"
            ),
        ),
        (
            r"心房顫動|房顫|afib|atrial fibrillation",
            (
                "Atrial fibrillation is an irregular rhythm from the upper heart chambers. It can increase stroke risk, so suspected AFib should be reviewed by a clinician with ECG evidence."
                if is_en
                else "心房顫動是來自心房的心律不規則，可能增加中風風險；若懷疑有房顫，需要由醫療人員搭配心電圖判讀。"
            ),
        ),
        (
            r"心電圖|心电图|ecg|ekg",
            (
                "An ECG records the heart's electrical activity through electrodes. It helps screen heart rate and rhythm, but a formal interpretation still requires clinical review."
                if is_en
                else "心電圖是用電極記錄心臟電活動，可觀察心率與節律；但正式判讀仍需要醫療專業人員確認。"
            ),
        ),
        (
            r"r\s*peak|r波",
            (
                "The R peak is the tall spike in a typical ECG heartbeat complex. It is often used to estimate heart rate and R-R interval variability."
                if is_en
                else "R 波峰是典型心電圖每次心搏中較明顯的尖峰，常用來估算心率與 RR 間期變化。"
            ),
        ),
        (
            r"hrv|rmssd|pnn50|心率變異|心率变异",
            (
                "HRV describes variation between heartbeats. RMSSD and pNN50 are common short-term HRV measures, but they are not diagnoses by themselves."
                if is_en
                else "HRV 是心跳間距的變化；RMSSD 與 pNN50 是常見短期 HRV 指標，但單獨不能當作疾病診斷。"
            ),
        ),
        (
            r"心搏過速|心跳過快|tachycardia",
            (
                "Tachycardia means an unusually fast heart rate, often described as over 100 beats per minute at rest in adults. Context, symptoms, and ECG matter."
                if is_en
                else "心搏過速通常指成人安靜時心率偏快，常見定義是每分鐘超過 100 下；仍需搭配情境、症狀與心電圖判斷。"
            ),
        ),
        (
            r"心搏過緩|心跳過慢|bradycardia",
            (
                "Bradycardia means a slow heart rate, often below 60 beats per minute in adults. It can be normal in sleep or athletes, but symptoms need evaluation."
                if is_en
                else "心搏過緩通常指成人心率偏慢，常見定義是每分鐘低於 60 下；睡眠或運動員可能正常，但若有症狀需評估。"
            ),
        ),
        (
            r"血壓|高血壓|hypertension|blood pressure",
            (
                "Blood pressure reflects the force of blood against artery walls. Persistently high readings should be discussed with a healthcare professional."
                if is_en
                else "血壓是血液推動血管壁的壓力；若多次量測都偏高，應與醫療人員討論。"
            ),
        ),
        (
            r"糖尿病|血糖|diabetes|glucose",
            (
                "Diabetes is a condition where blood glucose regulation is abnormal. Diagnosis depends on validated blood tests, not symptoms alone."
                if is_en
                else "糖尿病是血糖調節異常的疾病；診斷需要正式血液檢查，不能只靠症狀判斷。"
            ),
        ),
    ]

    for pattern, response in templates:
        if re.search(pattern, normalized, re.IGNORECASE):
            return response
    return None


def _educational_general_response(language: str, question: str) -> str:
    template = _medical_education_template(language, question)
    if template:
        return template

    lang_name = "ENGLISH" if language == "en-US" else "TRADITIONAL CHINESE (zh-TW)"
    prompt = (
        f"Question: {question}\n\n"
        f"Answer in {lang_name}. This is LOW-RISK medical education only.\n"
        "Give a brief, voice-ready explanation under 2 sentences / 45 words.\n"
        "Do not diagnose the user, do not recommend medication, tests, treatment, dosage, or personalized actions.\n"
        "Do not cite a specific guideline unless it was explicitly provided. "
        "Do not imply certainty for an individual's condition. Mention professional care only if the question includes symptoms or personal concern."
    )
    started_at = time.monotonic()
    response = medical_education_llm.invoke([HumanMessage(content=prompt)])
    logger.info(f"[Latency] medical_education_general_llm_ms={round((time.monotonic() - started_at) * 1000, 1)}")
    return response.content.strip()


def _answer_cache_key(state: AgentState):
    return "|".join([
        str(state.get("language", "")),
        str(state.get("route_decision", "")),
        str(state.get("input_text", "")).strip().lower(),
        str(state.get("rag_evidence_status", "")),
        str(state.get("rag_source_count", "")),
        str((state.get("ecg_measurement") or {}).get("measured_at", "")),
    ])


def _get_answer_cache(key: str):
    cached = ANSWER_CACHE.get(key)
    if not cached:
        return None
    created_at, value = cached
    if time.time() - created_at > ANSWER_CACHE_TTL_SECONDS:
        ANSWER_CACHE.pop(key, None)
        return None
    logger.info("[Answer Cache] Hit.")
    return value


def _set_answer_cache(key: str, value: str):
    ANSWER_CACHE[key] = (time.time(), value)


def _split_claims(text: str):
    parts = re.split(r"[。！？.!?]\s*", text or "")
    return [part.strip() for part in parts if part.strip()]


def _claim_supported_by_context(claim: str, context: str):
    if len(claim) < 8:
        return True
    cjk_terms = re.findall(r"[\u4e00-\u9fff]{2,}", claim)
    latin_terms = re.findall(r"[A-Za-z][A-Za-z-]{3,}", claim.lower())
    terms = cjk_terms + latin_terms
    if not terms:
        return True

    context_lower = (context or "").lower()
    hits = sum(1 for term in terms if term.lower() in context_lower)
    return hits / max(len(terms), 1) >= 0.35


def _verify_medical_answer(answer: str, context: str):
    claims = _split_claims(answer)
    if not claims:
        return False
    unsupported = [claim for claim in claims if not _claim_supported_by_context(claim, context)]
    if unsupported:
        logger.warning(f"[Medical Guard] Unsupported claims blocked: {unsupported}")
        return False
    return True

# ==========================================
# 3. LangGraph Nodes
# ==========================================

def router_node(state: AgentState):
    """
    router node: determine whether to chat, search, or perform physical actions
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    logger.info(f"[Router] {user_input}")

    if _is_language_command(user_input):
        logger.info("[Router] route: system_control (language keyword match)")
        return _with_latency(state, {
            "route_decision": "system_control",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:language")

    if _is_answer_pause_command(user_input) or _is_answer_resume_command(user_input):
        logger.info("[Router] route: system_control (answer control keyword match)")
        return _with_latency(state, {
            "route_decision": "system_control",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:answer_control")

    if _is_mic_pause_command(user_input) or _is_mic_resume_command(user_input):
        logger.info("[Router] route: system_control (microphone keyword match)")
        return _with_latency(state, {
            "route_decision": "system_control",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:microphone")

    if _is_high_risk_medical(user_input):
        logger.info("[Router] route: medical_safety (high-risk symptom keyword match)")
        return _with_latency(state, {
            "route_decision": "medical_safety",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "high",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:medical_high_risk")

    if _is_ecg_result_question(user_input):
        logger.info("[Router] route: ecg_result (ECG result keyword match)")
        return _with_latency(state, {
            "route_decision": "ecg_result",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:ecg_result")

    if _is_ecg_measurement_command(user_input):
        logger.info("[Router] route: system_control (ECG measurement keyword match)")
        return _with_latency(state, {
            "route_decision": "system_control",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:ecg_measurement")

    if _matches_any(user_input, GREETING_PATTERNS):
        logger.info("[Router] route: agent (greeting keyword match)")
        return _with_latency(state, {
            "route_decision": "agent",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:greeting")

    if _matches_any(user_input, JOKE_PATTERNS):
        logger.info("[Router] route: rag_search (joke keyword match)")
        return _with_latency(state, {
            "route_decision": "rag_search",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:joke")

    if _matches_any(_normalize_command_text(user_input), MEDICAL_KEYWORD_PATTERNS):
        risk_level = _classify_medical_risk(user_input)
        route = "medical_personal" if risk_level == "personal" else "medical_education"
        logger.info(f"[Router] route: {route} (medical keyword match, risk={risk_level})")
        return _with_latency(state, {
            "route_decision": route,
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": risk_level,
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method=f"keyword:medical_{risk_level}")

    if _matches_any(user_input, WEATHER_OR_FACT_PATTERNS):
        logger.info("[Router] route: search (fact/weather keyword match)")
        return _with_latency(state, {
            "route_decision": "search",
            "tool_raw_xml": "",
            "rag_evidence_status": "",
            "rag_max_relevance": 0.0,
            "rag_source_count": 0,
            "medical_risk_level": "",
            "refined_context": "",
            "final_response": "",
            "language": state.get("language", "zh-TW")
        }, "router", node_started_at, router_method="keyword:fact")
    
    sys_prompt = """You are a router that determines the user's intent.
    You can only choose from the following four categories:
    1. 'search': The user is asking for general facts, weather, current events, technology news, or any non-medical global knowledge.
    2. 'rag_search': The user is asking for a joke from the local joke knowledge base, or about health and medical topics. This includes:
       - Requests to tell a joke, cold joke, funny story, or similar humor request
       - Diseases or conditions (e.g. heart disease, diabetes, arrhythmia, PVC, AFib)
       - Symptoms and their causes (e.g. palpitations, chest pain, dizziness)
       - Medications, treatments, or medical procedures
       - Preventive healthcare and lifestyle advice (e.g. diet for heart health, exercise recommendations)
       - Medical terminology explained in plain language (e.g. "what is tachycardia?")
       - Any patient education or wellness question
       This route queries authoritative sources (MedlinePlus) for accurate medical information.
    3. 'system_control': The user requests a direct system or hardware command (e.g., switch language to English, adjust volume, stop talking). THIS IS STRICTLY FOR HARDWARE COMMANDS, NOT FOR CHIT-CHAT OR EMOTIONS.
    4. 'agent': Casual conversation, greetings, storytelling, self-introduction requests, or any other conversational interaction unrelated to health or hardware.

    When in doubt between 'search' and 'rag_search', choose 'rag_search' for any health-related question.
    Return format: {"route": "search"} or {"route": "rag_search"} or {"route": "system_control"} or {"route": "agent"}
    """

    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_input)
    ]
    
    # service using openai or llama3
    started_at = time.monotonic()
    response = router_llm.invoke(messages)
    router_llm_ms = round((time.monotonic() - started_at) * 1000, 1)
    logger.info(f"[Latency] router_llm_ms={router_llm_ms}")
    try:
        decision = orjson.loads(response.content)
        route = decision.get("route", "agent")
    except Exception:
        # if parse failed, default to chat agent
        route = "agent"
        
    logger.info(f"[Router] route: {route}")
    
    # Reset transient state variables while preserving persistent ones like language
    return _with_latency(state, {
        "route_decision": route,
        "tool_raw_xml": "",
        "rag_evidence_status": "",
        "rag_max_relevance": 0.0,
        "rag_source_count": 0,
        "medical_risk_level": "",
        "refined_context": "",
        "final_response": "",
        "language": state.get("language", "zh-TW")
    }, "router", node_started_at, router_method="llm", router_llm_ms=router_llm_ms)

def ecg_result_node(state: AgentState):
    """
    Return the latest ECG measurement directly from runtime state.
    This is measured robot data, so it should not go through medical RAG evidence verification.
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    history = state.get("chat_history", [])
    target_lang = state.get("language", "zh-TW")
    measurement = state.get("ecg_measurement") or {}

    if not measurement:
        reply_text = (
            "I do not have an ECG measurement yet. Please ask me to measure ECG first."
            if target_lang == "en-US"
            else "目前還沒有可用的心電圖量測結果。你可以先說：幫我測量心電圖。"
        )
    else:
        reply_text = _ecg_measurement_response(target_lang, measurement)

    action_json_str = orjson.dumps([
        {
            "action_type": "function",
            "func_name": "emotionShow",
            "func_args": {"emotion": "QT/showing_smile"}
        },
        {
            "action_type": "function",
            "func_name": "gesturePlay",
            "func_args": {"name": "QT/happy", "speed": 1.0}
        }
    ]).decode("utf-8")
    final_response = f"{reply_text} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>"
    new_history = history + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": reply_text}
    ]
    return _with_latency(
        state,
        {"final_response": final_response, "chat_history": new_history},
        "ecg_result",
        node_started_at,
        main_agent_method="ecg_result_direct",
    )


def medical_safety_node(state: AgentState):
    """
    Direct safety response for high-risk symptom reports.
    This bypasses RAG because urgent symptoms should not wait for retrieval quality.
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    history = state.get("chat_history", [])
    target_lang = state.get("language", "zh-TW")
    if target_lang == "en-US":
        reply_text = (
            "Shortness of breath with heart discomfort may be urgent. "
            "Please stop activity, ask someone nearby for help, and call emergency services or go to the ER now."
        )
    else:
        reply_text = (
            "你現在很喘又心臟不舒服，可能是緊急狀況。"
            "請先停止活動、請旁人協助，立刻撥打 119 或前往急診。"
        )

    action_json_str = orjson.dumps([
        {
            "action_type": "function",
            "func_name": "emotionShow",
            "func_args": {"emotion": "QT/surprised"}
        },
        {
            "action_type": "function",
            "func_name": "gesturePlay",
            "func_args": {"name": "QT/show_tablet", "speed": 1.0}
        }
    ]).decode("utf-8")
    final_response = f"{reply_text} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>"
    new_history = history + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": reply_text}
    ]
    return _with_latency(
        state,
        {
            "final_response": final_response,
            "chat_history": new_history,
            "medical_risk_level": "high",
        },
        "medical_safety",
        node_started_at,
        main_agent_method="medical_safety_template",
    )


def medical_personal_node(state: AgentState):
    """
    Conservative fixed response for personal medical questions.
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    history = state.get("chat_history", [])
    target_lang = state.get("language", "zh-TW")
    reply_text = _personal_medical_response(target_lang)
    action_json_str = orjson.dumps([
        {
            "action_type": "function",
            "func_name": "emotionShow",
            "func_args": {"emotion": "QT/showing_smile"}
        },
        {
            "action_type": "function",
            "func_name": "gesturePlay",
            "func_args": {"name": "QT/sad", "speed": 1.0}
        }
    ]).decode("utf-8")
    final_response = f"{reply_text} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>"
    new_history = history + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": reply_text}
    ]
    return _with_latency(
        state,
        {
            "final_response": final_response,
            "chat_history": new_history,
            "medical_risk_level": "personal",
        },
        "medical_personal",
        node_started_at,
        main_agent_method="medical_personal_template",
    )


def medical_education_node(state: AgentState):
    """
    Low-risk medical education with deterministic decoding.
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    history = state.get("chat_history", [])
    target_lang = state.get("language", "zh-TW")
    llm_started_at = time.monotonic()
    reply_text = _educational_general_response(target_lang, user_input)
    medical_education_llm_ms = round((time.monotonic() - llm_started_at) * 1000, 1)
    action_json_str = orjson.dumps([
        {
            "action_type": "function",
            "func_name": "emotionShow",
            "func_args": {"emotion": "QT/showing_smile"}
        },
        {
            "action_type": "function",
            "func_name": "gesturePlay",
            "func_args": {"name": "QT/happy", "speed": 1.0}
        }
    ]).decode("utf-8")
    final_response = f"{reply_text} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>"
    new_history = history + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": reply_text}
    ]
    return _with_latency(
        state,
        {
            "final_response": final_response,
            "chat_history": new_history,
            "medical_risk_level": "education",
        },
        "medical_education",
        node_started_at,
        main_agent_method="medical_education_direct",
        medical_education_llm_ms=medical_education_llm_ms,
    )


def system_control_node(state: AgentState):
    """
    system control node: determine what system control action to perform
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    logger.info(f"[Action] Inferring system control action for: {user_input}")

    if _is_answer_resume_command(user_input):
        action = {
            "action_type": "function",
            "func_name": "resumeAnswering",
            "func_args": {},
        }
        action_json_str = orjson.dumps(action).decode("utf-8")
        response = (
            "Okay, I will answer again."
            if state.get("language") == "en-US"
            else "好的，我會恢復回答。"
        )
        return _with_latency(state, {
            "final_response": f"{response} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
        }, "system_control", node_started_at, system_control_method="keyword:answer_resume")

    if _is_answer_pause_command(user_input):
        action = {
            "action_type": "function",
            "func_name": "pauseAnswering",
            "func_args": {},
        }
        action_json_str = orjson.dumps(action).decode("utf-8")
        response = (
            "Okay, I will stay quiet. Say resume answering when you need me."
            if state.get("language") == "en-US"
            else "好的，我會先暫停回答；需要我時可以說恢復回答。"
        )
        return _with_latency(state, {
            "final_response": f"{response} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
        }, "system_control", node_started_at, system_control_method="keyword:answer_pause")

    if _is_mic_resume_command(user_input):
        action = {
            "action_type": "function",
            "func_name": "resumeMicrophone",
            "func_args": {},
        }
        action_json_str = orjson.dumps(action).decode("utf-8")
        response = (
            "Microphone listening is resumed."
            if state.get("language") == "en-US"
            else "好的，我已恢復收音。"
        )
        return _with_latency(state, {
            "final_response": f"{response} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
        }, "system_control", node_started_at, system_control_method="keyword:mic_resume")

    if _is_mic_pause_command(user_input):
        duration_seconds = _extract_mic_pause_seconds(user_input)
        action = {
            "action_type": "function",
            "func_name": "pauseMicrophone",
            "func_args": {"duration_seconds": duration_seconds},
        }
        action_json_str = orjson.dumps(action).decode("utf-8")
        response = (
            f"Okay. I will pause listening for {duration_seconds} seconds."
            if state.get("language") == "en-US"
            else f"好的，我會暫停收音 {duration_seconds} 秒，之後自動恢復。"
        )
        return _with_latency(state, {
            "final_response": f"{response} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
        }, "system_control", node_started_at, system_control_method="keyword:mic_pause")

    if _is_ecg_measurement_command(user_input):
        action = {
            "action_type": "function",
            "func_name": "measureECG",
            "func_args": {"duration_seconds": 60},
        }
        action_json_str = orjson.dumps(action).decode("utf-8")
        response = (
            "Okay. Please keep the ECG device connected and remain still. The 60-second timer will begin after a stable ECG signal is confirmed."
            if state.get("language") == "en-US"
            else "好的，請保持心電裝置連線並維持靜止；確認穩定 ECG 訊號後，才會開始六十秒量測。"
        )
        return _with_latency(state, {
            "final_response": f"{response} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
        }, "system_control", node_started_at, system_control_method="keyword:ecg_measurement")

    mapped_language_action, mapped_language = _map_language_command(user_input)
    if mapped_language_action:
        action_json_str = orjson.dumps(mapped_language_action).decode("utf-8")
        logger.info(f"[Action] Deterministic language switch: {mapped_language}")
        return _with_latency(state, {
            "final_response": f"<PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
            "language": mapped_language
        }, "system_control", node_started_at, system_control_method="keyword")
    
    sys_prompt = """You are a system control mapper for the QTrobot.
    Map the user's explicit command to the correct system function. 
    Return format MUST be valid JSON, strictly following this structure: 
    {"action_type": "function", "func_name": "...", "func_args": {"...": "..."}}
    
    Available system commands:
    1. Set Language: func_name="setLanguage", func_args={"lang_code": "en-US" | "zh-TW"}
    2. Set Volume: func_name="setVolume", func_args={"level": 50}
    3. Measure ECG again: func_name="measureECG", func_args={"duration_seconds": 60}
    
    If the command is not an explicit match for one of the commands above, return:
    {"action_type": "none", "func_name": "none", "func_args": {}}
    """
    
    messages = [
        SystemMessage(content=sys_prompt),
        HumanMessage(content=user_input)
    ]
    
    try:
        started_at = time.monotonic()
        response = router_llm.invoke(messages)
        system_control_llm_ms = round((time.monotonic() - started_at) * 1000, 1)
        logger.info(f"[Latency] system_control_llm_ms={system_control_llm_ms}")
        decision = orjson.loads(response.content)
        func_name = decision.get("func_name")
        allowed_functions = {"setLanguage", "setVolume", "measureECG"}
        if func_name not in allowed_functions:
            fallback_text = (
                "I could not identify a clear system command, so no setting was changed."
                if state.get("language") == "en-US"
                else "我沒有辨識到明確的系統指令，因此沒有變更任何設定。"
            )
            return _with_latency(state, {
                "final_response": fallback_text,
                "language": state.get("language", "zh-TW"),
            }, "system_control", node_started_at, system_control_method="unrecognized", system_control_llm_ms=system_control_llm_ms)
        
        # Sync internal state if language is changed
        new_lang = state.get("language", "zh-TW")
        if decision.get("func_name") == "setLanguage":
            lang_code = decision.get("func_args", {}).get("lang_code")
            if "en" in str(lang_code):
                new_lang = "en-US"
            elif "zh" in str(lang_code):
                new_lang = "zh-TW"

        action_json_str = orjson.dumps(decision).decode('utf-8')
        return _with_latency(state, {
            "final_response": f"<PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>",
            "language": new_lang
        }, "system_control", node_started_at, system_control_method="llm", system_control_llm_ms=system_control_llm_ms)
    except Exception as e:
        logger.error(f"Action mapping failed: {e}")
        fallback_text = (
            "The system command could not be processed, so no setting was changed."
            if state.get("language") == "en-US"
            else "系統指令處理失敗，因此沒有變更任何設定。"
        )
        return _with_latency(state, {
            "final_response": fallback_text,
            "language": state.get("language", "zh-TW")
        }, "system_control", node_started_at, system_control_method="fallback")

def tool_web_search_node(state: AgentState):
    """
    web search node: perform web search
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    logger.info(f"[Tool] web search: {user_input}")
    
    try:
        search_started_at = time.monotonic()
        search = GoogleSerperAPIWrapper()
        raw_results = search.results(user_input)
        serper_ms = round((time.monotonic() - search_started_at) * 1000, 1)
        
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
        serper_ms = round((time.monotonic() - node_started_at) * 1000, 1)
        
    return _with_latency(state, {"tool_raw_xml": xml_content}, "tool_search", node_started_at, serper_ms=serper_ms)

def rag_search_node(state: AgentState):
    """
    RAG search node: query local txt documents via FAISS
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    logger.info(f"[Tool] Local RAG search: {user_input}")
    
    try:
        # Retrieve context plus evidence metadata for medical safety gating.
        started_at = time.monotonic()
        report = rag_engine.retrieve_context_with_report(user_input, k=3)
        rag_retrieve_ms = round((time.monotonic() - started_at) * 1000, 1)
        logger.info(f"[Latency] rag_retrieve_ms={rag_retrieve_ms}")
        xml_content = report.context_xml
        source_count = report.local_count + report.medlineplus_count
        risk_level = _classify_medical_risk(user_input)
        
        if not xml_content:
            xml_content = "No relevant information found in local knowledge or MedlinePlus."
        
        return _with_latency(state, {
            "tool_raw_xml": xml_content,
            "rag_evidence_status": report.evidence_status,
            "rag_max_relevance": report.max_local_relevance,
            "rag_source_count": source_count,
            "medical_risk_level": risk_level,
        }, "rag_search", node_started_at, rag_retrieve_ms=rag_retrieve_ms)

    except Exception as e:
        logger.error(f"Error in rag_search_node: {e}")
        xml_content = f"Error during RAG search: {e}"

    return _with_latency(state, {
        "tool_raw_xml": xml_content,
        "rag_evidence_status": "none",
        "rag_max_relevance": 0.0,
        "rag_source_count": 0,
        "medical_risk_level": _classify_medical_risk(user_input),
    }, "rag_search", node_started_at, rag_retrieve_ms=round((time.monotonic() - node_started_at) * 1000, 1))

def summarizer_node(state: AgentState):
    """
    Summarizes the RAG search results from both TSOC local knowledge 
    and MedlinePlus to provide a unified, authoritative answer.
    """
    node_started_at = time.monotonic()
    raw_xml = state.get("tool_raw_xml", "")
    user_input = state.get("input_text", "")
    evidence_status = state.get("rag_evidence_status", "")
    risk_level = state.get("medical_risk_level", "")
    source_count = state.get("rag_source_count", 0)
    max_relevance = state.get("rag_max_relevance", 0.0)
    target_lang = state.get("language", "zh-TW")
    ecg_measurement = state.get("ecg_measurement") or {}
    ecg_context = format_ecg_context(ecg_measurement)
    is_joke_request = _matches_any(user_input, JOKE_PATTERNS)

    if state.get("route_decision") == "rag_search" and not is_joke_request:
        cache_key = _answer_cache_key(state)
        cached_answer = _get_answer_cache(cache_key)
        if cached_answer:
            return _with_latency(
                state,
                {"refined_context": cached_answer},
                "summarizer",
                node_started_at,
                summarizer_method="cache",
            )

        if risk_level == "high":
            logger.warning("[Medical Guard] High-risk symptom detected; using emergency safety response.")
            safe_response = _safe_medical_response(target_lang, risk_level, evidence_status)
            _set_answer_cache(cache_key, safe_response)
            return _with_latency(
                state,
                {"refined_context": safe_response},
                "summarizer",
                node_started_at,
                summarizer_method="medical_guard_high",
            )

        if (
            _is_ecg_result_question(user_input)
            and ecg_measurement.get("status") in (
                "waiting_device",
                "waiting_signal",
                "measuring",
                "signal_timeout",
                "stream_lost",
                "no_current_face",
                "no_person_measurement",
                "person_measurement_stale",
                "complete",
                "low_quality",
            )
            and not ecg_measurement.get("is_stale", True)
        ):
            measured_response = _ecg_measurement_response(target_lang, ecg_measurement)
            _set_answer_cache(cache_key, measured_response)
            return _with_latency(
                state,
                {"refined_context": measured_response},
                "summarizer",
                node_started_at,
                summarizer_method="ecg_measurement",
            )

        if risk_level == "personal":
            logger.warning("[Medical Guard] Personal medical question; using conservative fixed response.")
            personal_response = _personal_medical_response(target_lang)
            _set_answer_cache(cache_key, personal_response)
            return _with_latency(
                state,
                {"refined_context": personal_response},
                "summarizer",
                node_started_at,
                summarizer_method="medical_guard_personal",
            )

        if evidence_status in ("none", "weak") and risk_level == "education":
            logger.warning(
                f"[Medical Guard] Weak RAG evidence for education question; using general education fallback: "
                f"status={evidence_status}, sources={source_count}, max_relevance={max_relevance:.3f}"
            )
            llm_started_at = time.monotonic()
            educational_response = _educational_general_response(target_lang, user_input)
            medical_education_llm_ms = round((time.monotonic() - llm_started_at) * 1000, 1)
            _set_answer_cache(cache_key, educational_response)
            return _with_latency(
                state,
                {"refined_context": educational_response},
                "summarizer",
                node_started_at,
                summarizer_method="medical_education_llm",
                medical_education_llm_ms=medical_education_llm_ms,
            )

        if evidence_status in ("none", "weak"):
            logger.warning(
                f"[Medical Guard] Evidence gate blocked answer: status={evidence_status}, "
                f"sources={source_count}, max_relevance={max_relevance:.3f}"
            )
            safe_response = _safe_medical_response(target_lang, risk_level, evidence_status)
            _set_answer_cache(cache_key, safe_response)
            return _with_latency(
                state,
                {"refined_context": safe_response},
                "summarizer",
                node_started_at,
                summarizer_method="medical_guard_evidence",
            )

    if not raw_xml or "No relevant information" in raw_xml:
        logger.warning("[Summarizer] No context provided to summarizer.")
        no_context_response = (
            "笑話資料庫裡暫時找不到合適的笑話。" if is_joke_request and target_lang == "zh-TW"
            else "I couldn't find a suitable joke in the local joke collection." if is_joke_request
            else _safe_medical_response(target_lang, risk_level, "none")
        )
        return _with_latency(
            state,
            {"refined_context": no_context_response},
            "summarizer",
            node_started_at,
            summarizer_method="no_context_guard",
        )

    # Determine output language
    lang_name = "TRADITIONAL CHINESE (zh-TW)" if target_lang == "zh-TW" else "ENGLISH"

    if is_joke_request:
        prompt = (
            f"User request: '{user_input}'\n\n"
            "Below are entries retrieved from the local joke knowledge base:\n"
            f"{raw_xml}\n\n"
            f"Reply in {lang_name}. Select exactly one retrieved joke and tell it naturally. "
            "Preserve the setup and punchline, keep the response short, do not explain the joke, "
            "and do not invent a joke that is absent from the retrieved content."
        )
    else:
        prompt = (
        f"User question: '{user_input}'\n\n"
        "Below are the retrieved medical knowledge sources (including Taiwan Society of Cardiology (TSOC) guidelines and MedlinePlus authoritative information):\n"
        f"{raw_xml}\n\n"
        f"Evidence metadata: source_count={source_count}, max_local_relevance={max_relevance:.3f}, evidence_status={evidence_status}.\n\n"
        f"Latest ECG session context: {ecg_context}\n\n"
        f"Please provide a VERY SHORT, professional response IN {lang_name}:\n"
        f"1. THE RESPONSE MUST BE IN {lang_name} and EXTREMELY BRIEF (under 3 sentences / 50 words).\n"
        "2. Prioritize information from TSOC guidelines and attribute it clearly.\n"
        "3. Use MedlinePlus data to supplement details where appropriate.\n"
        "4. Structure the answer normally but keep it strictly narrative.\n"
        "5. USE A NARRATIVE, DESCRIPTIVE STYLE. Avoid bullet points.\n"
        "6. DO NOT say the word 'QTrobot' or 'QT' in your speech.\n"
        "7. Use ONLY facts supported by the provided sources. Do not add diagnosis, treatment instructions, medication dosing, or unsupported claims.\n"
        "8. If the sources do not support a specific answer, say the evidence is insufficient and recommend professional medical advice."
        "9. Use the ECG session only when relevant to the question. Report measured values faithfully, never infer a diagnosis, "
        "and never describe the RR-irregularity indicator as a disease probability."
    )

    logger.info(f"[Summarizer] Processing RAG context (length: {len(raw_xml)})...")
    started_at = time.monotonic()
    response = summarizer_llm.invoke([HumanMessage(content=prompt)])
    summarizer_llm_ms = round((time.monotonic() - started_at) * 1000, 1)
    logger.info(f"[Latency] summarizer_llm_ms={summarizer_llm_ms}")
    refined_context = response.content
    if state.get("route_decision") == "rag_search" and not is_joke_request and not _verify_medical_answer(refined_context, raw_xml):
        if risk_level == "education":
            logger.warning("[Medical Guard] RAG answer verification failed for low-risk education; using concise education fallback.")
            llm_started_at = time.monotonic()
            refined_context = _educational_general_response(target_lang, user_input)
            medical_education_llm_ms = round((time.monotonic() - llm_started_at) * 1000, 1)
            return _with_latency(
                state,
                {"refined_context": refined_context},
                "summarizer",
                node_started_at,
                summarizer_method="medical_education_guard_fallback",
                summarizer_llm_ms=summarizer_llm_ms,
                medical_education_llm_ms=medical_education_llm_ms,
            )
        refined_context = _safe_medical_response(target_lang, risk_level, "weak")
    if state.get("route_decision") == "rag_search":
        _set_answer_cache(_answer_cache_key(state), refined_context)
    logger.info(f"[Summarizer] Refined response generated: {len(refined_context)} chars.")

    return _with_latency(
        state,
        {"refined_context": refined_context},
        "summarizer",
        node_started_at,
        summarizer_method="llm",
        summarizer_llm_ms=summarizer_llm_ms,
    )

def main_agent_node(state: AgentState):
    """
    main agent node: generate final response
    """
    node_started_at = time.monotonic()
    user_input = state["input_text"]
    context = state.get("refined_context", "")
    logger.info("[Agent] main LLM is generating response...")
    history = state.get("chat_history", [])

    if state.get("route_decision") == "rag_search" and context:
        new_history = history + [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": context}
        ]
        return _with_latency(
            state,
            {"final_response": context, "chat_history": new_history},
            "main_agent",
            node_started_at,
            main_agent_method="rag_direct",
        )

    if _matches_any(user_input, GREETING_PATTERNS):
        target_lang = state.get("language", "zh-TW")
        reply_text = "Hi, I'm here. How can I help you?" if target_lang == "en-US" else "你好，我在這裡。你想聊什麼呢？"
        action_json_str = orjson.dumps([
            {
                "action_type": "function",
                "func_name": "emotionShow",
                "func_args": {"emotion": "QT/happy"}
            },
            {
                "action_type": "function",
                "func_name": "gesturePlay",
                "func_args": {"name": "QT/hi", "speed": 1.0}
            }
        ]).decode("utf-8")
        final_response = f"{reply_text} <PHYSICAL_ACTION_REQUEST>{action_json_str}</PHYSICAL_ACTION_REQUEST>"
        new_history = history + [
            {"role": "user", "content": user_input},
            {"role": "assistant", "content": reply_text}
        ]
        return _with_latency(
            state,
            {"final_response": final_response, "chat_history": new_history},
            "main_agent",
            node_started_at,
            main_agent_method="greeting_template",
        )
    
    # Determine output language
    target_lang = state.get("language", "zh-TW")
    lang_name = "TRADITIONAL CHINESE (zh-TW)" if target_lang == "zh-TW" else "ENGLISH"

    sys_prompt = (
        f"You are a warm and friendly voice assistant. Answer the user's question in a VERY SHORT, CONCISE, and NARRATIVE style IN {lang_name}.\n"
        f"CRITICAL: YOUR ENTIRE RESPONSE MUST BE EXTREMELY BRIEF (under 2 sentences / 40 words) and IN {lang_name}.\n"
        "CRITICAL: DO NOT say the word 'QTrobot' or 'QT' in your speech, as it will trigger a hardware echo. Always refer to yourself simply as 'AI' or '我'.\n"
        "CRITICAL: AVOID using bullet points, numbered lists, or '1, 2, 3' sequences in your speech. Speak in cohesive, natural paragraphs as if you are talking to a friend.\n"
        "For every conversational answer, append exactly one <PHYSICAL_ACTION_REQUEST> block with at least one suitable emotionShow or gesturePlay action.\n"
        "You can use multiple actions by returning a JSON array, but keep it to one emotion plus one gesture at most.\n"
        "Available 'emotionShow' actions (func_args={\"emotion\": \"...\"}):\n"
        "- Basic: QT/happy, QT/happy_blinking, QT/sad, QT/cry, QT/angry, QT/surprised, QT/confused, QT/disgusted, QT/shy\n"
        "- Conversational: QT/neutral, QT/neutral_state_blinking, QT/showing_smile, QT/talking, QT/yawn, QT/kiss\n"
        "- Daily habits: QT/brushing_teeth, QT/brushing_teeth_foam, QT/dirty_face, QT/dirty_face_sad, QT/dirty_face_wash\n"
        "- Health: QT/with_a_cold, QT/with_a_cold_cleaning_nose, QT/with_a_cold_sneezing\n"
        "- Relaxation: QT/calming_down, QT/calming_down_exercise_nose, QT/puffing_the_cheeks, QT/scream\n"
        "Available 'gesturePlay' actions (func_args={\"name\": \"...\", \"speed\": 1.0}):\n"
        f"- Use only these verified status=True gestures: {VERIFIED_GESTURE_PROMPT}.\n"
        "- Use QT/hi for greeting, QT/happy for positive or agreement, QT/sad for concern, QT/show_tablet or QT/point_front when referring to the screen or ECG display.\n"
        "- Do not invent gesture names. Do not use gestures that are not in the verified list above.\n\n"
        f"Format Example (ALWAYS IN {lang_name}):\n"
        "你好！今天感覺怎麼樣？ <PHYSICAL_ACTION_REQUEST>[{\"action_type\": \"function\", \"func_name\": \"emotionShow\", \"func_args\": {\"emotion\": \"QT/happy\"}}, {\"action_type\": \"function\", \"func_name\": \"gesturePlay\", \"func_args\": {\"name\": \"QT/hi\", \"speed\": 1.0}}]</PHYSICAL_ACTION_REQUEST>"
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
    if history:
        for msg in history:
            if msg.get("role") == "user":
                lc_messages.append(HumanMessage(content=msg.get("content", "")))
            else:
                from langchain_core.messages import AIMessage
                lc_messages.append(AIMessage(content=msg.get("content", "")))
                
    lc_messages.append(HumanMessage(content=user_input))
    
    started_at = time.monotonic()
    response = main_agent_llm.invoke(lc_messages)
    main_agent_llm_ms = round((time.monotonic() - started_at) * 1000, 1)
    logger.info(f"[Latency] main_agent_llm_ms={main_agent_llm_ms}")
    reply_text = response.content
    
    new_history = history + [
        {"role": "user", "content": user_input},
        {"role": "assistant", "content": reply_text}
    ]
    
    return _with_latency(
        state,
        {"final_response": reply_text, "chat_history": new_history},
        "main_agent",
        node_started_at,
        main_agent_method="llm",
        main_agent_llm_ms=main_agent_llm_ms,
    )
