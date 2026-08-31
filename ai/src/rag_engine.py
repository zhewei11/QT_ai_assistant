"""
RAG Engine
==========
Primary knowledge retrieval layer with two sources:
  1. Local FAISS vector store — supports both .txt and structured .xml files
     (.xml files from ai/document/ are parsed by <section>, preserving article
     metadata as LangChain Document.metadata for richer context)
  2. MedlinePlus Web Service (authoritative health-education content, free, no API key)

Retrieval strategy:
  - Always query FAISS first.
  - If FAISS returns fewer than MIN_LOCAL_CHUNKS, supplement with MedlinePlus.
"""

import os
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from config import logger
from medlineplus_rag import search_medlineplus, format_for_rag


MIN_LOCAL_RELEVANCE = 0.35


@dataclass
class RetrievalReport:
    context_xml: str
    local_count: int
    medlineplus_count: int
    max_local_relevance: float

    @property
    def has_evidence(self) -> bool:
        return bool(self.context_xml.strip())

    @property
    def has_sufficient_evidence(self) -> bool:
        return self.medlineplus_count > 0 or self.max_local_relevance >= MIN_LOCAL_RELEVANCE

    @property
    def evidence_status(self) -> str:
        if not self.has_evidence:
            return "none"
        if self.has_sufficient_evidence:
            return "sufficient"
        return "weak"



# ---------------------------------------------------------------------------
# XML Knowledge File Parser
# ---------------------------------------------------------------------------
def _load_xml_knowledge(xml_path: str) -> list[Document]:
    """
    Parse a structured XML knowledge file and return one LangChain Document
    per <section>. Article-level metadata (title, category, source, url) is
    attached so the LLM can cite the source in its reply.

    Expected XML structure:
        <knowledge_base>
          <metadata>
            <source>...</source>
            <url>...</url>
          </metadata>
          <article id="...">
            <title>...</title>
            <category>...</category>
            <keywords>...</keywords>
            <section name="...">content text</section>
            ...
          </article>
          ...
        </knowledge_base>
    """
    docs: list[Document] = []
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        logger.error(f"[RAG] XML parse error in {xml_path}: {e}")
        return docs

    # Global metadata from <knowledge_base><metadata>
    kb_meta = root.find("metadata")
    global_source = ""
    global_url = ""
    if kb_meta is not None:
        global_source = (kb_meta.findtext("source") or "").strip()
        global_url    = (kb_meta.findtext("url") or "").strip()

    for article in root.findall("article"):
        article_id  = article.get("id", "")
        title       = (article.findtext("title")    or "").strip()
        category    = (article.findtext("category") or "").strip()
        keywords    = (article.findtext("keywords") or "").strip()

        for section in article.findall("section"):
            section_name = section.get("name", "內容")
            raw_text     = (section.text or "").strip()
            if not raw_text:
                continue

            # Build the text chunk with context header so the LLM can
            # understand what it's reading even without surrounding context.
            chunk_text = (
                f"【來源】{global_source}\n"
                f"【文章】{title}\n"
                f"【章節】{section_name}\n"
                f"【類別】{category}\n\n"
                f"{raw_text}"
            )

            docs.append(Document(
                page_content=chunk_text,
                metadata={
                    "source_name": global_source,
                    "source_url":  global_url,
                    "article_id":  article_id,
                    "title":       title,
                    "category":    category,
                    "keywords":    keywords,
                    "section":     section_name,
                    "file":        os.path.basename(xml_path),
                }
            ))

    logger.info(
        f"[RAG] Parsed {len(docs)} sections from {os.path.basename(xml_path)}"
    )
    return docs


# ---------------------------------------------------------------------------
# RAG Engine
# ---------------------------------------------------------------------------
class RAGEngine:
    def __init__(self, document_dir: str = "document"):
        self.document_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            document_dir,
        )
        self.vector_store: FAISS | None = None
        self.initialization_error = ""
        self.cache_ttl_seconds = int(os.getenv("RAG_CACHE_TTL_SECONDS", "3600"))
        self._report_cache: dict[str, tuple[float, RetrievalReport]] = {}
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        try:
            self._initialize_knowledge_base()
        except Exception as e:
            self.initialization_error = str(e)
            self.vector_store = None
            logger.error(
                "[RAG] Local knowledge initialization failed; "
                "AI will continue with RAG degraded. "
                f"error={e}"
            )

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------
    def _initialize_knowledge_base(self):
        logger.info(f"[RAG] Loading knowledge base from: {self.document_dir}")

        if not os.path.exists(self.document_dir):
            os.makedirs(self.document_dir)
            logger.warning("[RAG] document/ directory created (empty). RAG disabled until files are added.")
            return

        all_docs: list[Document] = []

        # 1) Load plain .txt files via LangChain DirectoryLoader
        txt_loader = DirectoryLoader(
            self.document_dir, glob="**/*.txt", loader_cls=TextLoader,
            silent_errors=True,
        )
        txt_docs = txt_loader.load()
        if txt_docs:
            logger.info(f"[RAG] Loaded {len(txt_docs)} .txt document(s).")
            all_docs.extend(txt_docs)

        # 2) Load structured .xml files, parsed section-by-section
        for fname in os.listdir(self.document_dir):
            if fname.lower().endswith(".xml"):
                xml_docs = _load_xml_knowledge(
                    os.path.join(self.document_dir, fname)
                )
                all_docs.extend(xml_docs)

        if not all_docs:
            logger.warning(
                "[RAG] No documents found in document/. "
                "MedlinePlus will be used as the sole knowledge source."
            )
            return

        # Chunk only .txt docs (XML docs are pre-chunked by <section>)
        txt_raw = [d for d in all_docs if d.metadata.get("source", "").endswith(".txt")
                   or "file" not in d.metadata]
        xml_raw = [d for d in all_docs if "file" in d.metadata]

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=800, chunk_overlap=100, length_function=len
        )
        txt_splits = splitter.split_documents(txt_raw) if txt_raw else []
        all_splits = txt_splits + xml_raw  # XML sections already sized correctly

        try:
            self.vector_store = FAISS.from_documents(all_splits, self.embeddings)
        except Exception as e:
            self.initialization_error = str(e)
            self.vector_store = None
            logger.error(
                "[RAG] Failed to build local FAISS index. "
                "This usually means embeddings cannot reach OpenAI "
                "or DNS/network is unavailable. "
                f"error={e}"
            )
            return

        logger.info(
            f"[RAG] Indexed {len(all_splits)} chunks "
            f"({len(txt_splits)} from .txt, {len(xml_raw)} from .xml)"
        )

    # ------------------------------------------------------------------
    # Local FAISS retrieval
    # ------------------------------------------------------------------
    def _retrieve_local(self, query: str, k: int = 3) -> list[Document]:
        if not self.vector_store:
            return []
        try:
            return self.vector_store.similarity_search(query, k=k)
        except Exception as e:
            logger.error(f"[RAG] FAISS error: {e}")
            return []

    def _retrieve_local_with_relevance(self, query: str, k: int = 3) -> list[tuple[Document, float]]:
        if not self.vector_store:
            return []
        try:
            results = self.vector_store.similarity_search_with_relevance_scores(query, k=k)
            return [(doc, float(score)) for doc, score in results]
        except Exception as e:
            logger.warning(f"[RAG] FAISS relevance scoring unavailable, falling back to unscored search: {e}")
            return [(doc, 0.0) for doc in self._retrieve_local(query, k=k)]

    # ------------------------------------------------------------------
    # MedlinePlus retrieval
    # ------------------------------------------------------------------
    def retrieve_medlineplus(self, query: str, retmax: int = 3) -> str:
        try:
            results = search_medlineplus(query, lang="en", retmax=retmax)
        except Exception as e:
            logger.warning(f"[RAG] MedlinePlus retrieval failed: {e}")
            return ""
        return format_for_rag(results)

    # ------------------------------------------------------------------
    # Combined retrieval — main entry point called by rag_search_node
    # ------------------------------------------------------------------
    def retrieve_context(
        self,
        query: str,
        k: int = 3,
        use_medlineplus: bool = True,
    ) -> str:
        """
        Always queries BOTH local FAISS and MedlinePlus, then combines
        the results into a single XML context block for the summarizer.

            <local_knowledge>   ← TSOC XML / .txt documents (FAISS)
              ...
            </local_knowledge>
            <medlineplus_results>  ← MedlinePlus authoritative content
              ...
            </medlineplus_results>
        """
        return self.retrieve_context_with_report(
            query,
            k=k,
            use_medlineplus=use_medlineplus,
        ).context_xml

    def retrieve_context_with_report(
        self,
        query: str,
        k: int = 3,
        use_medlineplus: bool = True,
    ) -> RetrievalReport:
        """
        Returns context plus retrieval metadata so medical-answer nodes can
        refuse or ask for clarification when evidence is too weak.
        """
        cache_key = f"{query.strip().lower()}|k={k}|mlp={use_medlineplus}"
        cached = self._report_cache.get(cache_key)
        now = time.time()
        if cached and now - cached[0] <= self.cache_ttl_seconds:
            logger.info(f"[RAG] Cache hit for query: {query!r}")
            return cached[1]

        parts: list[str] = []
        max_local_relevance = 0.0
        medlineplus_count = 0

        # 1) Local FAISS (TSOC and other local docs)
        local_results = self._retrieve_local_with_relevance(query, k=k)
        if local_results:
            max_local_relevance = max(score for _, score in local_results)
            local_blocks = "\n---\n".join(
                f"<chunk relevance=\"{score:.3f}\">\n{doc.page_content}\n</chunk>"
                for doc, score in local_results
            )
            parts.append(f"<local_knowledge>\n{local_blocks}\n</local_knowledge>")
            logger.info(
                f"[RAG] Local FAISS returned {len(local_results)} chunk(s), "
                f"max relevance={max_local_relevance:.3f}."
            )
        else:
            logger.info("[RAG] No local chunks found.")

        # 2) MedlinePlus — supplement when local evidence is weak or unavailable.
        if use_medlineplus and max_local_relevance < MIN_LOCAL_RELEVANCE:
            try:
                medlineplus_results = search_medlineplus(query, lang="en", retmax=3)
            except Exception as e:
                medlineplus_results = []
                logger.warning(f"[RAG] MedlinePlus retrieval failed: {e}")
            medlineplus_count = len(medlineplus_results)
            mlp_xml = format_for_rag(medlineplus_results)
            if mlp_xml:
                parts.append(mlp_xml)
                logger.info(f"[RAG] MedlinePlus appended {medlineplus_count} result(s).")
        elif use_medlineplus:
            logger.info("[RAG] Local evidence sufficient; skipped MedlinePlus for latency.")

        if not parts:
            report = RetrievalReport("", len(local_results), medlineplus_count, max_local_relevance)
            self._report_cache[cache_key] = (now, report)
            return report

        report = RetrievalReport(
            context_xml="\n\n".join(parts),
            local_count=len(local_results),
            medlineplus_count=medlineplus_count,
            max_local_relevance=max_local_relevance,
        )
        self._report_cache[cache_key] = (now, report)
        return report



# Global singleton
rag_engine = RAGEngine()
