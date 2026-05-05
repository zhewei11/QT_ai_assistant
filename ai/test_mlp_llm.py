import logging
import sys
import os

# Setup logging to see output
logging.basicConfig(level=logging.INFO)

# Add src to path
sys.path.append(os.path.join(os.getcwd(), 'src'))

from medlineplus_rag import _translate_to_en

queries = [
    "心房顫動是什麼？",
    "Rpeak是什麼",
    "胸痛喘不過氣",
    "How to treat hypertension?"
]

for q in queries:
    en = _translate_to_en(q)
    print(f"Query: {q} -> EN: {en}")
