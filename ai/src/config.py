import logging
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI  # 保留備用
from langchain_ollama import ChatOllama
# ==========================================
# 0. basic setting
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AI_Brain")

# load .env
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', '.env')
load_dotenv(config_path, override=True)

if os.getenv("TAVILYT_API_KEY"):
    os.environ["TAVILY_API_KEY"] = os.getenv("TAVILYT_API_KEY")

router_llm     = ChatOpenAI(model="gpt-4o-mini", temperature=0)             # 極速路由，只需回傳 JSON
summarizer_llm = ChatOpenAI(model="gpt-5.4", temperature=0, max_tokens=1000)   # 提高 token 上限避免擷取
main_agent_llm = ChatOpenAI(model="gpt-5.4", temperature=0.7, max_tokens=2000)
