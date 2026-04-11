import os
from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from config import logger

class RAGEngine:
    def __init__(self, document_dir="document"):
        self.document_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), document_dir)
        self.vector_store = None
        self.embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
        self._initialize_knowledge_base()

    def _initialize_knowledge_base(self):
        logger.info(f"Checking RAG documents in {self.document_dir}...")
        
        # Ensure directory exists
        if not os.path.exists(self.document_dir):
            os.makedirs(self.document_dir)
            logger.warning(f"Directory {self.document_dir} did not exist. Created empty directory.")
            return

        # Load TXT files
        loader = DirectoryLoader(self.document_dir, glob="**/*.txt", loader_cls=TextLoader)
        docs = loader.load()
        
        if not docs:
            logger.warning(f"No .txt documents found in {self.document_dir}. RAG is disabled until files are added.")
            return
            
        logger.info(f"Loaded {len(docs)} documents. Chunking and indexing...")
        
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=150,
            length_function=len
        )
        splits = text_splitter.split_documents(docs)
        
        # Create FAISS memory vector store
        self.vector_store = FAISS.from_documents(splits, self.embeddings)
        logger.info(f"Successfully indexed {len(splits)} chunks into FAISS vector store.")

    def retrieve_context(self, query: str, k: int = 3) -> str:
        if not self.vector_store:
            return ""
            
        try:
            results = self.vector_store.similarity_search(query, k=k)
            context = "\n---\n".join([doc.page_content for doc in results])
            return context
        except Exception as e:
            logger.error(f"Error retrieving RAG context: {e}")
            return ""

# Initialize global singleton
rag_engine = RAGEngine()
