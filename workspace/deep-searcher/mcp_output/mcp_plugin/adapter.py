import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

# Import statements
try:
    from deepsearcher.agent.base import BaseAgent
    from deepsearcher.agent.chain_of_rag import ChainOfRAG
    from deepsearcher.agent.collection_router import CollectionRouter
    from deepsearcher.agent.deep_search import DeepSearch
    from deepsearcher.agent.naive_rag import NaiveRAG
    from deepsearcher.agent.rag_router import RAGRouter
    from deepsearcher.embedding.base import BaseEmbedding
    from deepsearcher.embedding.openai_embedding import OpenAIEmbedding
    from deepsearcher.llm.base import BaseLLM
    from deepsearcher.llm.openai_llm import OpenAILLM
    from deepsearcher.loader.file_loader.base import BaseFileLoader
    from deepsearcher.loader.file_loader.text_loader import TextLoader
    from deepsearcher.vector_db.base import BaseVectorDB
    from deepsearcher.vector_db.milvus import MilvusDB
except ImportError as e:
    print(f"Error importing modules: {e}. Ensure the source directory is correctly set.")
    BaseAgent = ChainOfRAG = CollectionRouter = DeepSearch = NaiveRAG = RAGRouter = None
    BaseEmbedding = OpenAIEmbedding = None
    BaseLLM = OpenAILLM = None
    BaseFileLoader = TextLoader = None
    BaseVectorDB = MilvusDB = None


class Adapter:
    """
    Adapter class for the MCP plugin. This class provides methods to interact with the core functionalities
    of the Deep Searcher framework, including agents, embeddings, LLMs, file loaders, and vector databases.
    """

    def __init__(self):
        """
        Initialize the Adapter class with default mode and check for module availability.
        """
        self.mode = "import"
        self.status = {
            "BaseAgent": BaseAgent is not None,
            "ChainOfRAG": ChainOfRAG is not None,
            "CollectionRouter": CollectionRouter is not None,
            "DeepSearch": DeepSearch is not None,
            "NaiveRAG": NaiveRAG is not None,
            "RAGRouter": RAGRouter is not None,
            "BaseEmbedding": BaseEmbedding is not None,
            "OpenAIEmbedding": OpenAIEmbedding is not None,
            "BaseLLM": BaseLLM is not None,
            "OpenAILLM": OpenAILLM is not None,
            "BaseFileLoader": BaseFileLoader is not None,
            "TextLoader": TextLoader is not None,
            "BaseVectorDB": BaseVectorDB is not None,
            "MilvusDB": MilvusDB is not None,
        }

    # ------------------- Agent Methods --------------------

    def create_base_agent(self, **kwargs):
        """
        Create an instance of BaseAgent.

        :param kwargs: Parameters for initializing BaseAgent.
        :return: Dictionary containing the status and instance of BaseAgent.
        """
        if not self.status["BaseAgent"]:
            return {"status": "error", "message": "BaseAgent module is not available."}
        try:
            instance = BaseAgent(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create BaseAgent: {e}"}

    def create_chain_of_rag(self, **kwargs):
        """
        Create an instance of ChainOfRAG.

        :param kwargs: Parameters for initializing ChainOfRAG.
        :return: Dictionary containing the status and instance of ChainOfRAG.
        """
        if not self.status["ChainOfRAG"]:
            return {"status": "error", "message": "ChainOfRAG module is not available."}
        try:
            instance = ChainOfRAG(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create ChainOfRAG: {e}"}

    # Add similar methods for CollectionRouter, DeepSearch, NaiveRAG, and RAGRouter.

    # -------------------- Embedding Methods --------------------

    def create_openai_embedding(self, **kwargs):
        """
        Create an instance of OpenAIEmbedding.

        :param kwargs: Parameters for initializing OpenAIEmbedding.
        :return: Dictionary containing the status and instance of OpenAIEmbedding.
        """
        if not self.status["OpenAIEmbedding"]:
            return {"status": "error", "message": "OpenAIEmbedding module is not available."}
        try:
            instance = OpenAIEmbedding(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create OpenAIEmbedding: {e}"}

    # Add similar methods for other embeddings if needed.

    # -------------------- LLM Methods --------------------

    def create_openai_llm(self, **kwargs):
        """
        Create an instance of OpenAILLM.

        :param kwargs: Parameters for initializing OpenAILLM.
        :return: Dictionary containing the status and instance of OpenAILLM.
        """
        if not self.status["OpenAILLM"]:
            return {"status": "error", "message": "OpenAILLM module is not available."}
        try:
            instance = OpenAILLM(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create OpenAILLM: {e}"}

    # -------------------- File Loader Methods --------------------

    def create_text_loader(self, **kwargs):
        """
        Create an instance of TextLoader.

        :param kwargs: Parameters for initializing TextLoader.
        :return: Dictionary containing the status and instance of TextLoader.
        """
        if not self.status["TextLoader"]:
            return {"status": "error", "message": "TextLoader module is not available."}
        try:
            instance = TextLoader(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create TextLoader: {e}"}

    # -------------------- Vector Database Methods --------------------

    def create_milvus_db(self, **kwargs):
        """
        Create an instance of MilvusDB.

        :param kwargs: Parameters for initializing MilvusDB.
        :return: Dictionary containing the status and instance of MilvusDB.
        """
        if not self.status["MilvusDB"]:
            return {"status": "error", "message": "MilvusDB module is not available."}
        try:
            instance = MilvusDB(**kwargs)
            return {"status": "success", "instance": instance}
        except Exception as e:
            return {"status": "error", "message": f"Failed to create MilvusDB: {e}"}

    # -------------------- Utility Methods --------------------

    def check_status(self):
        """
        Check the availability of all modules.

        :return: Dictionary containing the status of all modules.
        """
        return {"status": "success", "modules": self.status}