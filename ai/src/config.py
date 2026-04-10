import logging
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

# ==========================================
# 0. basic setting
# ==========================================
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AI_Brain")

# load .env
config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', '.env')
load_dotenv(config_path)

if os.getenv("TAVILYT_API_KEY"):
    os.environ["TAVILY_API_KEY"] = os.getenv("TAVILYT_API_KEY")

router_llm     = ChatOpenAI(model="gpt-4o-mini", temperature=0)
summarizer_llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)  
main_agent_llm = ChatOpenAI(model="gpt-4o", temperature=0.7)
