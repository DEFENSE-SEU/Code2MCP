import os
import sys

# Path settings
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "source")
sys.path.insert(0, source_path)

from fastmcp import FastMCP
from deepsearcher.agent import base, chain_of_rag, collection_router, deep_search, naive_rag, rag_router
from deepsearcher.embedding import base as embedding_base, bedrock_embedding, fastembed_embdding, gemini_embedding, glm_embedding, milvus_embedding, novita_embedding, ollama_embedding, openai_embedding, ppio_embedding, sentence_transformer_embedding, siliconflow_embedding, volcengine_embedding, voyage_embedding, watsonx_embedding
from deepsearcher.llm import aliyun, anthropic_llm, azure_openai, base as llm_base, bedrock, deepseek, gemini, glm, novita, ollama, openai_llm, ppio, siliconflow, together_ai, volcengine, watsonx, xai
from deepsearcher.loader import splitter
from deepsearcher.loader.file_loader import base as file_loader_base, docling_loader, json_loader, pdf_loader, text_loader, unstructured_loader
from deepsearcher.loader.web_crawler import base as web_crawler_base, crawl4ai_crawler, docling_crawler, firecrawl_crawler, jina_crawler
from deepsearcher.utils import log
from deepsearcher.vector_db import azure_search, base as vector_db_base, milvus, oracle, qdrant

# Initialize FastMCP
mcp = FastMCP("deep_searcher_service")

# Tool Endpoints
@mcp.tool(name="agent_base", description="Base agent functionality.")
def agent_base_tool() -> dict:
    """
    Executes base agent functionality.
    Returns:
        dict: A dictionary containing success or error information.
    """
    try:
        result = base.some_functionality()
        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="chain_of_rag", description="Chain of RAG functionality.")
def chain_of_rag_tool() -> dict:
    """
    Executes chain of RAG functionality.
    Returns:
        dict: A dictionary containing success or error information.
    """
    try:
        result = chain_of_rag.some_functionality()
        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="collection_router", description="Collection router functionality.")
def collection_router_tool() -> dict:
    """
    Executes collection router functionality.
    Returns:
        dict: A dictionary containing success or error information.
    """
    try:
        result = collection_router.some_functionality()
        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="deep_search", description="Deep search functionality.")
def deep_search_tool() -> dict:
    """
    Executes deep search functionality.
    Returns:
        dict: A dictionary containing success or error information.
    """
    try:
        result = deep_search.some_functionality()
        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="naive_rag", description="Naive RAG functionality.")
def naive_rag_tool() -> dict:
    """
    Executes naive RAG functionality.
    Returns:
        dict: A dictionary containing success or error information.
    """
    try:
        result = naive_rag.some_functionality()
        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="rag_router", description="RAG router functionality.")
def rag_router_tool() -> dict:
    """
    Executes RAG router functionality.
    Returns:
        dict: A dictionary containing success or error information.
    """
    try:
        result = rag_router.some_functionality()
        return {"success": True, "result": result, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="health_check", description="Health check endpoint.")
def health_check() -> dict:
    """
    Performs a health check for the service.
    Returns:
        dict: A dictionary containing the health status.
    """
    try:
        return {"success": True, "result": "Service is healthy", "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

@mcp.tool(name="version_info", description="Version information endpoint.")
def version_info() -> dict:
    """
    Provides version information for the service.
    Returns:
        dict: A dictionary containing the version information.
    """
    try:
        version = "1.0.0"  # Replace with dynamic version retrieval if needed
        return {"success": True, "result": {"version": version}, "error": None}
    except Exception as e:
        return {"success": False, "result": None, "error": str(e)}

# Application Factory
def create_app() -> FastMCP:
    """
    Creates and returns the FastMCP application instance.
    Returns:
        FastMCP: The FastMCP application instance.
    """
    return mcp