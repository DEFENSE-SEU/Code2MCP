import os
import time
import random
import logging
from typing import Optional, Dict, Any, Type
from dataclasses import dataclass
from pydantic import BaseModel
from langchain.chat_models import init_chat_model
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama
from langchain.schema import HumanMessage, SystemMessage

try:
    from langchain_aws import ChatBedrock, ChatBedrockConverse
    import boto3
    from botocore.exceptions import ClientError
    HAS_AWS = True
except ImportError:
    HAS_AWS = False
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

import platform

if platform.system() == 'Windows':
    import warnings
    warnings.simplefilter("ignore")
    import asyncio.base_subprocess
    import asyncio.proactor_events
    def _suppress_asyncio_warnings(*args, **kwargs): pass
    if hasattr(asyncio.base_subprocess, '_warn'): asyncio.base_subprocess._warn = _suppress_asyncio_warnings
    if hasattr(asyncio.proactor_events, '_warn'): asyncio.proactor_events._warn = _suppress_asyncio_warnings


logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)

def setup_logging(level: str = "INFO", log_dir: str = "logs") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=getattr(logging, level.upper()),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler(os.path.join(log_dir, f"mcp_agent_{time.strftime('%Y%m%d')}.log"))
            ]
        )
    else:
        logging.getLogger().setLevel(getattr(logging, level.upper()))
    
    return logging.getLogger(__name__)

@dataclass
class ModelConfig:
    provider: str
    model_version: str
    api_key: str
    base_url: Optional[str] = None
    temperature: float = 0.1
    max_tokens: int = 8192
    timeout: int = 300
    max_retries: int = 10

class ResponseWithThinkPydantic(BaseModel):
    think: str = "Thinking process"
    response: str = "LLM response"

class LLMService:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.model_version = config.model_version
        self.temperature = config.temperature
        self.model_provider = config.provider.lower()
        self.total_calls = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.failed_calls = 0
        self.retry_count = 0
        self._client = self._create_client()
    
    def _create_client(self):
        try:
            if self.model_provider == "bedrock" and HAS_AWS:
                bedrock_runtime = boto3.client('bedrock-runtime')
                return ChatBedrockConverse(client=bedrock_runtime, model_id=self.model_version, temperature=self.temperature, max_tokens=self.config.max_tokens)
            elif self.model_provider == "anthropic":
                return ChatAnthropic(model=self.model_version, temperature=self.temperature, max_tokens=self.config.max_tokens, request_timeout=self.config.timeout, max_retries=self.config.max_retries)
            elif self.model_provider == "openai":
                return ChatOpenAI(model=self.model_version, openai_api_key=self.config.api_key, openai_api_base=self.config.base_url, temperature=self.temperature, max_tokens=self.config.max_tokens, request_timeout=self.config.timeout, max_retries=self.config.max_retries, streaming=False)
            elif self.model_provider == "deepseek":
                return ChatOpenAI(model=self.model_version, openai_api_key=self.config.api_key, openai_api_base=self.config.base_url, temperature=self.temperature, max_tokens=self.config.max_tokens, request_timeout=self.config.timeout, max_retries=self.config.max_retries, streaming=False)
            elif self.model_provider == "qwen":
                return ChatOpenAI(model=self.model_version, openai_api_key=self.config.api_key, openai_api_base=self.config.base_url, temperature=self.temperature, max_tokens=self.config.max_tokens, request_timeout=self.config.timeout, max_retries=self.config.max_retries, streaming=False)
            elif self.model_provider == "ollama":
                return ChatOllama(model=self.model_version, temperature=self.temperature, num_predict=-1, num_ctx=131072, base_url="http://localhost:11434")
            else:
                return init_chat_model(self.model_version, model_provider=self.model_provider, temperature=self.temperature)
        except Exception as e:
            logger.error(f"Failed to create LLM client: {e}")
            raise
    
    def invoke(self, 
              user_prompt: str, 
              system_prompt: Optional[str] = None, 
              pydantic_obj: Optional[Type[BaseModel]] = None,
              max_retries: int = 10) -> Any:
        """
        Invoke LLM and return response
        
        Args:
            user_prompt: User prompt
            system_prompt: System prompt
            pydantic_obj: Pydantic model for structured output
            max_retries: Maximum retry count
            
        Returns:
            LLM response
        """
        self.total_calls += 1
        
        messages = []
        if system_prompt:
            messages.append(SystemMessage(content=system_prompt))
        messages.append(HumanMessage(content=user_prompt))
        
        prompt_tokens = 0
        for message in messages:
            if hasattr(self._client, 'get_num_tokens'):
                prompt_tokens += self._client.get_num_tokens(message.content)
        
        retry_count = 0
        while True:
            try:
                if pydantic_obj:
                    structured_llm = self._client.with_structured_output(pydantic_obj)
                    response = structured_llm.invoke(messages)
                else:
                    response = self._client.invoke(messages)
                    response = response.content

                response_content = str(response)
                completion_tokens = 0
                if hasattr(self._client, 'get_num_tokens'):
                    completion_tokens = self._client.get_num_tokens(response_content)
                total_tokens = prompt_tokens + completion_tokens
                
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                self.total_tokens += total_tokens
                
                return response
                
            except ClientError as e:
                if HAS_AWS and (e.response['Error']['Code'] == 'Throttling' or 
                               e.response['Error']['Code'] == 'TooManyRequestsException'):
                    retry_count += 1
                    self.retry_count += 1
                    
                    if retry_count > max_retries:
                        self.failed_calls += 1
                        raise Exception(f"Maximum retry count ({max_retries}) exceeded: {str(e)}")
                    
                    base_delay = 1.0
                    max_delay = 60.0
                    delay = min(max_delay, base_delay * (2 ** (retry_count - 1)))
                    jitter = random.uniform(0, 0.1 * delay)
                    sleep_time = delay + jitter
                    
                    logger.warning(f"Rate limiting exception: {str(e)}. Retrying in {sleep_time:.2f} seconds (attempt {retry_count}/{max_retries})")
                    time.sleep(sleep_time)
                else:
                    self.failed_calls += 1
                    raise e
            except Exception as e:
                retry_count += 1
                self.retry_count += 1
                
                if retry_count > max_retries:
                    self.failed_calls += 1
                    raise e
                
                sleep_time = retry_count * 2
                logger.warning(f"LLM call failed, retrying in {sleep_time} seconds (attempt {retry_count}/{max_retries}): {str(e)}")
                time.sleep(sleep_time)
    
    def generate_text(self, prompt: str, system_prompt: str = None) -> str:
        return self.invoke(prompt, system_prompt)
    
    def agenerate_text(self, prompt: str, system_prompt: str = None) -> str:

        return self.invoke(prompt, system_prompt)

    def get_statistics(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "failed_calls": self.failed_calls,
            "retry_count": self.retry_count,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "average_prompt_tokens": self.total_prompt_tokens / self.total_calls if self.total_calls > 0 else 0,
            "average_completion_tokens": self.total_completion_tokens / self.total_calls if self.total_calls > 0 else 0,
            "average_tokens": self.total_tokens / self.total_calls if self.total_calls > 0 else 0
        }
    
    def print_statistics(self) -> None:
        stats = self.get_statistics()
        print("\n<LLM Service Statistics>")
        print(f"Total call count: {stats['total_calls']}")
        print(f"Failed call count: {stats['failed_calls']}")
        print(f"Total retry count: {stats['retry_count']}")
        print(f"Total prompt tokens: {stats['total_prompt_tokens']}")
        print(f"Total completion tokens: {stats['total_completion_tokens']}")
        print(f"Total tokens: {stats['total_tokens']}")
        print(f"Average prompt tokens per call: {stats['average_prompt_tokens']:.2f}")
        print(f"Average completion tokens per call: {stats['average_completion_tokens']:.2f}")
        print(f"Average tokens per call: {stats['average_tokens']:.2f}\n")
        print("</LLM Service Statistics>")

def get_model_config(provider: str = None) -> ModelConfig:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    if not provider:
        provider = os.getenv("MODEL_PROVIDER", "openai")
    
    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        model_version = os.getenv("OPENAI_MODEL", "gpt-5")
    elif provider == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        model_version = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    elif provider == "qwen":
        api_key = os.getenv("QWEN_API_KEY")
        base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
        model_version = os.getenv("QWEN_MODEL", "qwen-3")
    elif provider == "claude":
        api_key = os.getenv("CLAUDE_API_KEY")
        base_url = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com")
        model_version = os.getenv("CLAUDE_MODEL", "claude-4-sonnet")
    elif provider == "bedrock":
        api_key = os.getenv("AWS_ACCESS_KEY_ID")
        base_url = None
        model_version = os.getenv("BEDROCK_MODEL", "anthropic.claude-4-sonnet")
    elif provider == "ollama":
        api_key = None
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model_version = os.getenv("OLLAMA_MODEL", "llama2")
    else:
        raise ValueError(f"Unsupported model provider: {provider}")
    
    if provider not in ["ollama"] and not api_key:
        raise ValueError(f"Environment variable {provider.upper()}_API_KEY not set")
    
    return ModelConfig(
        provider=provider,
        model_version=model_version,
        api_key=api_key or "",
        base_url=base_url,
        temperature=float(os.getenv("MODEL_TEMPERATURE", "0.1")),
        max_tokens=int(os.getenv("MODEL_MAX_TOKENS", "8192")),
        timeout=int(os.getenv("MODEL_TIMEOUT", "300")),
        max_retries=int(os.getenv("MODEL_MAX_RETRIES", "10"))
    )

_global_llm_service = None

def get_llm_service(provider: str = None) -> LLMService:
    global _global_llm_service
    
    if _global_llm_service is None:
        config = get_model_config(provider)
        _global_llm_service = LLMService(config)
    
    return _global_llm_service

def get_llm_statistics() -> dict:
    global _global_llm_service
    
    if _global_llm_service is None:
        return {
            "total_calls": 0,
            "failed_calls": 0,
            "retry_count": 0,
            "total_prompt_tokens": 0,
            "total_completion_tokens": 0,
            "total_tokens": 0,
            "average_prompt_tokens": 0,
            "average_completion_tokens": 0,
            "average_tokens": 0
        }
    
    return _global_llm_service.get_statistics()

def safe_module_name(name: str) -> str:
    safe_name = ''.join(c for c in name if c.isalnum() or c == '_')
    if safe_name and safe_name[0].isdigit():
        safe_name = 'mcp_' + safe_name
    if not safe_name:
        safe_name = 'mcp_service'
    return safe_name.lower()

def create_directory(path: str) -> None:
    os.makedirs(path, exist_ok=True)

def write_file(file_path: str, content: str) -> None:
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)

def ensure_directory(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    return directory

def save_json(data: dict, file_path: str, indent: int = 2) -> bool:
    try:
        import json
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        return True
    except Exception as e:
        logger.error(f"Failed to save JSON {file_path}: {e}")
        return False

def load_json(file_path: str) -> dict:
    try:
        import json
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load JSON {file_path}: {e}")
        return {}

def get_project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_output_dir(base_dir: str = "output") -> str:
    output_path = os.path.join(get_project_root(), base_dir)
    ensure_directory(output_path)
    return output_path

def format_size(size_bytes: int) -> str:
    if size_bytes == 0:
        return "0B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    import math
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_names[i]}"

def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.2f} seconds"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.2f} minutes"
    else:
        hours = seconds / 3600
        return f"{hours:.2f} hours"

def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
    if len(text) <= max_length:
        return text
    return text[:max_length - len(suffix)] + suffix

def monitor_performance(func_name: str = None):
    def decorator(func):
        nonlocal func_name
        if func_name is None:
            func_name = func.__name__
        
        def wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                raise
            finally:
                execution_time = time.time() - start_time
                logger.debug(f"{func_name} execution time: {execution_time:.2f} seconds")
        
        return wrapper
    return decorator

def retry_async(func, *args, retry_config=None, **kwargs):
    if retry_config is None:
        retry_config = type('RetryConfig', (), {'max_retries': 3, 'delay': 1.0, 'backoff': 2.0})()
    
    last_exception = None
    delay = retry_config.delay
    
    for attempt in range(retry_config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if attempt < retry_config.max_retries:
                logger.warning(f"Attempt {attempt + 1} failed: {e}, retrying in {delay} seconds")
                time.sleep(delay)
                delay *= retry_config.backoff
            else:
                logger.error(f"Still failed after {retry_config.max_retries} retries: {e}")
    
    raise last_exception

def is_llm_available() -> bool:
    try:
        config = get_model_config()
        return bool(config.api_key or config.provider == "ollama")
    except:
        return False

def list_available_providers() -> list:
    providers = []
    if os.getenv("OPENAI_API_KEY"):
        providers.append("openai")
    if os.getenv("DEEPSEEK_API_KEY"):
        providers.append("deepseek")
    if os.getenv("QWEN_API_KEY"):
        providers.append("qwen")
    if os.getenv("CLAUDE_API_KEY"):
        providers.append("claude")
    if os.getenv("AWS_ACCESS_KEY_ID"):
        providers.append("bedrock")
    providers.append("ollama")
    return providers

def get_llm_stats() -> dict:
    return {
        "available_providers": list_available_providers(),
        "llm_available": is_llm_available()
    }

def fetch_deepwiki(url: str, timeout: int = 120) -> dict:
    import requests
    import time
    
    api = os.getenv("JINA_API_KEY")
    headers = {
        "X-Cache-Control": "no-cache",
        "X-Force-Refresh": "true",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
    }
    if api:
        headers.update({
            "Authorization": f"Bearer {api}",
            "X-Engine": "direct",
            "X-Return-Format": "markdown",
        })
    
    for attempt in range(5):
        try:
            cache_bust_url = f"{url}?t={int(time.time())}&attempt={attempt}"
            base = f"https://r.jina.ai/{cache_bust_url}"
            
            r = requests.get(base, headers=headers, timeout=timeout, verify=False)
            if r.status_code == 200 and r.text:
                content = r.text
                if "Loading..." not in content and len(content) > 50:
                    return {"success": True, "content": content, "status": r.status_code}
                elif "Loading..." in content and attempt < 4:
                    time.sleep(10)
                    continue
            
            return {"success": False, "error": f"status {r.status_code}", "status": r.status_code}
        except Exception as e:
            if attempt < 4:
                time.sleep(10)
                continue
            return {"success": False, "error": str(e)}
    
    return {"success": False, "error": "Max retries exceeded"}

class RetryConfig:
    def __init__(self, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
        self.max_retries = max_retries
        self.delay = delay
        self.backoff = backoff

def has_critical_errors(state: Dict[str, Any]) -> bool:
    errors = state.get("errors", [])
    run_result = state.get("run_result", {})
    error_analysis = state.get("error_analysis", {})
    
    if not run_result.get("success", False):
        return True
    
        if error_analysis:
            status = error_analysis.get("status", "PASS")
            feasibility = error_analysis.get("fix_strategy", {}).get("feasibility", "FIXABLE")
            
            if status == "FAIL" and feasibility == "FIXABLE":
                return True
            
            if feasibility == "REDESIGN":
                logger.warning("Error analysis suggests redesign, stopping retry attempts")
                return False
    
    for error in errors:
        if error.get("severity") in ["high", "critical"]:
            return True
        if "No module named" in str(error.get("message", "")):
            return True
        if "ImportError" in str(error.get("message", "")):
            return True
    
    return False

def should_retry_generation(state: Dict[str, Any], max_retries: int = 3) -> bool:
    retry_count = state.get("generation_retry_count", 0)
    return retry_count < max_retries and has_critical_errors(state)

def should_stop_workflow(state: Dict[str, Any]) -> tuple[bool, str]:
    error_analysis = state.get("error_analysis", {})
    
    if error_analysis:
        next_action = error_analysis.get("next_action", "continue")
        confidence = error_analysis.get("confidence", 0.5)
        
        if next_action == "environment_fix":
            return True, "Error analysis suggests fixing environment configuration, current workflow cannot handle"
        elif confidence < 0.3:
            return True, f"Error analysis confidence too low ({confidence:.2f})"
    
    return False, ""