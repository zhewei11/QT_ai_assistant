import logging
import os
from dotenv import load_dotenv
# ==========================================
# 0. basic setting
# ==========================================
# load .env before reading logging and model settings
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', '.env')
load_dotenv(config_path, override=True)

log_level_name = os.getenv("AI_LOG_LEVEL", "WARNING").upper()
log_level = getattr(logging, log_level_name, logging.WARNING)
logging.basicConfig(level=log_level, format='%(levelname)s - %(message)s')
logger = logging.getLogger("AI_Brain")
logger.setLevel(log_level)

library_log_level_name = os.getenv("AI_LIBRARY_LOG_LEVEL", "WARNING").upper()
library_log_level = getattr(logging, library_log_level_name, logging.WARNING)
for logger_name in ("httpx", "httpcore", "openai", "urllib3", "langchain", "langchain_openai"):
    logging.getLogger(logger_name).setLevel(library_log_level)

AI_TERMINAL_DEBUG = os.getenv("AI_TERMINAL_DEBUG", "normal").strip().lower()
if AI_TERMINAL_DEBUG not in {"quiet", "normal", "verbose"}:
    logger.warning("Unsupported AI_TERMINAL_DEBUG=%s; falling back to normal.", AI_TERMINAL_DEBUG)
    AI_TERMINAL_DEBUG = "normal"

from langchain_openai import ChatOpenAI  # 保留備用
from langchain_ollama import ChatOllama

if os.getenv("TAVILYT_API_KEY"):
    os.environ["TAVILY_API_KEY"] = os.getenv("TAVILYT_API_KEY")

router_llm     = ChatOpenAI(model="gpt-4o-mini", temperature=0)             # 極速路由，只需回傳 JSON
summarizer_llm = ChatOpenAI(model="gpt-5.4", temperature=0, max_tokens=1000)   # 醫療/RAG 回答採 deterministic decoding
medical_education_llm = ChatOpenAI(model="gpt-5.4", temperature=0, max_tokens=350) # 低風險醫學科普，最低隨機性
main_agent_llm = ChatOpenAI(model="gpt-5.4", temperature=0.3, max_tokens=2000) # 保留自然語氣，但降低隨機性
