"""
MedlinePlus RAG Client
======================
Queries the MedlinePlus Web Service (free, no API key required) to retrieve
authoritative health-education content. Results are cached locally as JSON
to avoid redundant network calls.

API docs: https://wsearch.nlm.nih.gov/ws/query
"""

import os
import re
import json
import hashlib
import logging
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

logger = logging.getLogger("AI_Brain")

# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------
_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "knowledge_cache"
)
os.makedirs(_CACHE_DIR, exist_ok=True)

# Cache TTL: 7 days (health guidelines rarely change that fast)
_CACHE_TTL_DAYS = 7

# ---------------------------------------------------------------------------
# MedlinePlus Web Service
# ---------------------------------------------------------------------------
MEDLINEPLUS_WS_URL = "https://wsearch.nlm.nih.gov/ws/query"

MEDICAL_TERM_MAP = [
    (r"心律不整|心律失常|心跳不規則|心跳不规则", "arrhythmia irregular heartbeat"),
    (r"心房顫動|心房颤动|房顫|房颤|afib|af", "atrial fibrillation"),
    (r"心電圖|心电图|心電|心电|ecg|ekg", "electrocardiogram ECG"),
    (r"r\s*peak|r波|R波", "ECG R wave R peak"),
    (r"心悸", "heart palpitations"),
    (r"胸痛|胸悶|胸闷|胸口痛", "chest pain"),
    (r"呼吸困難|呼吸困难|喘|喘不過氣|喘不过气", "shortness of breath"),
    (r"心搏過速|心跳過快|心跳过快|tachycardia", "tachycardia"),
    (r"心搏過緩|心跳過慢|心跳过慢|bradycardia", "bradycardia"),
    (r"血壓|血压|高血壓|高血压", "blood pressure hypertension"),
    (r"糖尿病|血糖", "diabetes blood glucose"),
    (r"膽固醇|胆固醇|血脂", "cholesterol blood lipids"),
    (r"中風|中风", "stroke"),
]

# No longer using hardcoded dictionary. We use LLM for medical translation.
from langchain_core.messages import SystemMessage, HumanMessage
import sys
# Add current directory to path to ensure config can be imported if it's not in the same package
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from config import router_llm

def _translate_to_en(query: str) -> str:
    """
    Use LLM to convert a health query into English search terms for MedlinePlus.
    This is much more flexible than a hardcoded dictionary.
    """
    # Quick check: if the query is already pure English, just return it
    if all(ord(c) < 128 for c in query):
        return query

    mapped_terms = [
        english
        for pattern, english in MEDICAL_TERM_MAP
        if re.search(pattern, query, re.IGNORECASE)
    ]
    if mapped_terms:
        mapped = " ".join(dict.fromkeys(mapped_terms))
        logger.info(f"[MedlinePlus] Static medical term mapping: {query!r} -> {mapped!r}")
        return mapped

    logger.info(f"[MedlinePlus] Translating query using LLM: {query!r}")
    
    sys_prompt = (
        "You are a medical translation assistant. Extract English medical search keywords "
        "from the user's query. Output ONLY the English keywords, separated by spaces. \n"
        "Example:\n"
        "Input: '心房顫動是什麼？' -> Output: 'atrial fibrillation'\n"
        "Input: 'Rpeak是什麼' -> Output: 'ECG R-peak'\n"
    )

    try:
        messages = [
            SystemMessage(content=sys_prompt),
            HumanMessage(content=query)
        ]
        response = router_llm.invoke(messages)
        translated = response.content.strip()
        # Strip non-ASCII
        translated_clean = re.sub(r'[^\x00-\x7F]+', '', translated).strip()
        if translated_clean:
            return translated_clean
    except Exception as e:
        logger.error(f"[MedlinePlus] LLM translation failed: {e}")
    
    # Fallback: strip Chinese
    fallback = re.sub(r'[^\x00-\x7F]+', '', query).strip()
    return fallback if fallback else query



def _cache_path(query: str, lang: str) -> str:
    key = hashlib.md5(f"{lang}:{query.lower().strip()}".encode()).hexdigest()
    return os.path.join(_CACHE_DIR, f"mlp_{key}.json")


def _is_fresh(cache_file: str) -> bool:
    if not os.path.exists(cache_file):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(cache_file))
    return datetime.now() - mtime < timedelta(days=_CACHE_TTL_DAYS)


def _clean_html(raw: str) -> str:
    """Strip HTML tags and unescape common entities."""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace(
        "&amp;", "&").replace("&apos;", "'").replace("&quot;", '"')
    # Collapse whitespace
    return re.sub(r"\s+", " ", text).strip()


def _parse_medlineplus_xml(xml_text: str) -> list[dict]:
    """
    Parse MedlinePlus Web Service XML and return a list of
    {title, summary, url, group} dicts.
    """
    results = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"[MedlinePlus] XML parse error: {e}")
        return results

    for doc in root.findall(".//document"):
        url = doc.get("url", "")
        title = ""
        summary = ""
        group = ""

        for content in doc.findall("content"):
            name = content.get("name", "")
            raw = content.text or ""
            if name == "title":
                title = _clean_html(raw)
            elif name == "FullSummary":
                summary = _clean_html(raw)
            elif name == "groupName":
                group = raw.strip()

        if title and summary:
            results.append({
                "title": title,
                "summary": str(summary)[:2000],   # cap length
                "url": url,
                "group": group,
            })

    return results


def search_medlineplus(query: str, lang: str = "en", retmax: int = 3) -> list[dict]:
    """
    Search MedlinePlus health topics for `query`.

    Args:
        query:  Natural-language health query (e.g. "tachycardia causes")
        lang:   "en" (English) or "es" (Spanish); MedlinePlus only has these two.
        retmax: Maximum number of results to return.

    Returns:
        List of dicts: [{title, summary, url, group}, ...]
        Returns [] on any error so callers can degrade gracefully.
    """
    # Translate Chinese query to English for MedlinePlus API compatibility
    en_query = _translate_to_en(query)

    cache_file = _cache_path(en_query, lang)   # cache keyed on English term
    if _is_fresh(cache_file):
        logger.info(f"[MedlinePlus] Cache hit for: {en_query!r}")
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    logger.info(f"[MedlinePlus] Fetching from API: {en_query!r} (lang={lang})")
    params = {
        "db": "healthTopics",
        "term": en_query,
        "retmax": retmax,
    }
    if lang == "es":
        params["lang"] = "Spanish"

    try:
        resp = requests.get(MEDLINEPLUS_WS_URL, params=params, timeout=10)
        resp.raise_for_status()
        results = _parse_medlineplus_xml(resp.text)
    except requests.RequestException as e:
        logger.error(f"[MedlinePlus] API request failed: {e}")
        return []

    # Persist to cache
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    return results


def format_for_rag(results: list[dict]) -> str:
    """
    Format MedlinePlus results as structured XML, consistent with the
    tool_raw_xml convention used by the rest of the LangGraph pipeline.

    Output example:
        <medlineplus_results>
          <article index="1">
            <title>Arrhythmia</title>
            <group>Blood, Heart and Circulation</group>
            <summary>What is an arrhythmia? ...</summary>
            <url>https://medlineplus.gov/arrhythmia.html</url>
          </article>
          ...
        </medlineplus_results>
    """
    if not results:
        return ""

    lines = ["<medlineplus_results>"]
    for i, r in enumerate(results, 1):
        lines.append(f'  <article index="{i}">')
        lines.append(f'    <title>{_xml_escape(r["title"])}</title>')
        if r.get("group"):
            lines.append(f'    <group>{_xml_escape(r["group"])}</group>')
        lines.append(f'    <summary>{_xml_escape(str(r["summary"])[:2000])}</summary>')
        lines.append(f'    <url>{r["url"]}</url>')
        lines.append("  </article>")
    lines.append("</medlineplus_results>")
    return "\n".join(lines)


def _xml_escape(text: str) -> str:
    """Minimal XML escaping so summaries don't break the XML structure."""
    return (text
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))
