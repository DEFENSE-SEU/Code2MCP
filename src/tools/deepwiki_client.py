# DeepWiki Client - Analyze GitHub repository information through DeepWiki and LLM
import json
import logging
import time
import os
from typing import Dict, Any, Optional, List
from openai import OpenAI
from ..utils import setup_logging

logger = setup_logging("INFO")

class DeepWikiClient:
    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-5"):
        self.model = model
        self.server_url = "https://deepwiki.com"
        self.fallback_enabled = True
        
        if not api_key:
            if "deepseek" in model.lower():
                api_key = os.getenv("DEEPSEEK_API_KEY")
                base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            elif "qwen" in model.lower():
                api_key = os.getenv("QWEN_API_KEY")
                base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            elif "claude" in model.lower():
                api_key = os.getenv("CLAUDE_API_KEY")
                base_url = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com")
            else:
                api_key = os.getenv("OPENAI_API_KEY")
                base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        else:
            if "deepseek" in model.lower():
                base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
            elif "qwen" in model.lower():
                base_url = os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
            elif "claude" in model.lower():
                base_url = os.getenv("CLAUDE_BASE_URL", "https://api.anthropic.com")
            else:
                base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        
        self.api_key = api_key
        
        if "claude" in model.lower():
            self.client_type = "anthropic"
        elif "deepseek" in model.lower():
            self.client_type = "deepseek"
        else:
            self.client_type = "openai"
        
        logger.info(f"DeepWikiClient initialized: model={model}, client_type={self.client_type}, api_key_set={bool(api_key)}")
        
        if "claude" in model.lower():
            try:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=api_key)
            except ImportError:
                self.client = OpenAI(api_key=api_key, base_url=base_url)
                self.client_type = "openai"  
        elif "deepseek" in model.lower():
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        
    def query(self, question: str) -> Dict[str, Any]:
        try:
            logger.info(f"DeepWiki query: {question[:100]}...")
            
            if not self.api_key:
                logger.warning(f"{self.client_type} API key not set, using fallback analysis")
                return self._fallback_analysis(question)
            
            try:
                resp = self.client.responses.create(
                    model=self.model,
                    tools=[{"type": "mcp", "server_label": "deepwiki", "server_url": self.server_url, "require_approval": "never"}],
                    input=question,
                )
                result = {"success": True, "output_text": resp.output_text, "model": self.model, "question": question, "source": "deepwiki"}
                logger.info(f"DeepWiki query successful, response length: {len(resp.output_text)}")
                return result
            except Exception as deepwiki_error:
                if self.fallback_enabled:
                    return self._fallback_analysis(question)
                else:
                    raise deepwiki_error
                    
        except Exception as e:
            error_msg = str(e)
            
            if "404" in error_msg or "page not found" in error_msg.lower():
                return {"success": False, "error": "DeepWiki service temporarily unavailable", "question": question, "model": self.model, "suggestion": "You can retry later or use basic analysis"}
            elif "rate limit" in error_msg.lower() or "quota" in error_msg.lower():
                return {"success": False, "error": "API quota exhausted", "question": question, "model": self.model, "suggestion": "Please check API quota or retry later"}
            elif "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
                return {"success": False, "error": "API authentication failed", "question": question, "model": self.model, "suggestion": "Please check API key settings"}
            else:
                return {"success": False, "error": error_msg, "question": question, "model": self.model}
    
    def _fallback_analysis(self, question: str) -> Dict[str, Any]:
        try:
            if self.client_type == "anthropic":
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=1000,
                    messages=[
                        {"role": "user", "content": question}
                    ]
                )
                output_text = resp.content[0].text
            elif self.client_type == "deepseek":
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a code analysis expert, please provide professional analysis and suggestions based on the user's question."},
                        {"role": "user", "content": question}
                    ],
                    max_tokens=1000,
                    temperature=0.1
                )
                output_text = resp.choices[0].message.content
            else:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a code analysis expert, please provide professional analysis and suggestions based on the user's question."},
                        {"role": "user", "content": question}
                    ],
                    max_tokens=1000,
                    temperature=0.1
                )
                output_text = resp.choices[0].message.content
            
            result = {
                "success": True, 
                "output_text": output_text, 
                "model": self.model, 
                "question": question, 
                "source": "fallback_llm"
            }
            logger.info(f"Fallback analysis successful, response length: {len(output_text)}")
            return result
            
        except Exception as e:
            logger.error(f"Fallback analysis also failed: {e}")
            return {
                "success": False, 
                "error": f"Fallback analysis failed: {e}", 
                "question": question, 
                "model": self.model,
                "suggestion": "Please check API key settings or network connection"
            }
    
    def _get_deepwiki_content(self, deepwiki_url: str) -> Optional[str]:
        try:
            content = self._get_deepwiki_content_with_selenium(deepwiki_url)
            if content:
                return content
            
            import requests
            from bs4 import BeautifulSoup
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Cache-Control': 'no-cache, no-store, must-revalidate',
                'Pragma': 'no-cache',
                'Expires': '0'
            }
            cache_bust_url = f"{deepwiki_url}?t={int(time.time())}"
            response = requests.get(cache_bust_url, headers=headers, timeout=60)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            content_text = []
            
            main_content = soup.find('main') or soup.find('article') or soup.find('div', class_='content') or soup.find('div', id='content')
            if main_content:
                content_elements = main_content.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'code', 'pre'])
            else:
                content_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'code', 'pre'])
            
            if content_elements:
                for element in content_elements:
                    text = element.get_text(strip=True)
                    if text and len(text) > 10:
                        content_text.append(text)
                
                if content_text:
                    full_content = '\n'.join(content_text[:20])
                    if len(full_content) > 2000:
                        full_content = full_content[:2000] + "..."
                    
                if "Loading..." in full_content and len(full_content.strip()) < 100:
                    logger.warning("DeepWiki HTTP content still shows Loading, may need more time")
                    return None
                
                return full_content
                
                all_text = soup.get_text(separator='\n', strip=True)
                if all_text and len(all_text) > 100:
                    cleaned_text = '\n'.join(line.strip() for line in all_text.split('\n') if line.strip())
                    if len(cleaned_text) > 2000:
                        cleaned_text = cleaned_text[:2000] + "..."
                    return cleaned_text
            
            return None
            
        except ImportError:
            logger.warning("Missing required libraries, unable to get DeepWiki content")
            return None
        except Exception as e:
            logger.warning(f"Failed to get DeepWiki content: {e}")
            return None

    def _get_deepwiki_content_with_selenium(self, deepwiki_url: str) -> Optional[str]:
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.common.exceptions import TimeoutException
            
            chrome_options = Options()
            chrome_options.add_argument('--headless')
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-logging')
            chrome_options.add_argument('--disable-dev-tools')
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-extensions')
            chrome_options.add_argument('--disable-plugins')
            chrome_options.add_argument('--disable-sync')
            chrome_options.add_argument('--disable-default-apps')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            chrome_options.add_experimental_option('useAutomationExtension', False)
            chrome_options.add_experimental_option('prefs', {
                'profile.default_content_setting_values.notifications': 2,
                'profile.default_content_settings.popups': 0,
                'profile.managed_default_content_settings.images': 2
            })
            
            driver = webdriver.Chrome(options=chrome_options)
            cache_bust_url = f"{deepwiki_url}?t={int(time.time())}"
            driver.get(cache_bust_url)

            wait = WebDriverWait(driver, 60)
            wait.until(lambda driver: driver.execute_script("return document.readyState") == "complete")
            
            time.sleep(5)
            
            for attempt in range(12):
                page_source = driver.page_source
                if "Loading..." not in page_source and len(page_source) > 10000:
                    break
                if any(keyword in page_source for keyword in ["Analysis", "Repository", "Functions", "Classes"]):
                    break
                time.sleep(5)
            
            time.sleep(3)
            
            page_source = driver.page_source
            driver.quit()

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(page_source, 'html.parser')

            content_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'code', 'pre'])
            content_text = []
            
            for element in content_elements:
                text = element.get_text(strip=True)
                if text and len(text) > 10:
                    content_text.append(text)
            
            if content_text:
                full_content = '\n'.join(content_text[:200])
                if len(full_content) > 50000:
                    full_content = full_content[:50000] + "..."
                
                if "Loading..." in full_content and len(full_content.strip()) < 100:
                    logger.warning("DeepWiki content still shows Loading, may need more time")
                    return None
                
                return full_content
            
            all_text = soup.get_text(separator='\n', strip=True)
            if all_text and len(all_text) > 100:
                cleaned_text = '\n'.join(line.strip() for line in all_text.split('\n') if line.strip())
                if len(cleaned_text) > 2000:
                    cleaned_text = cleaned_text[:2000] + "..."
                return cleaned_text
            
            return None
            
        except ImportError:
            return None
        except Exception as e:
            logger.warning(f"Selenium extraction failed: {e}")
            return None
    
    def analyze_repository(self, repo_url: str, repo_name: str) -> Dict[str, Any]:
        try:
            logger.info(f"Starting repository analysis {repo_name} ({repo_url})")
            
            repo_owner = repo_url.split('/')[-2]
            deepwiki_link = f"{self.server_url}/{repo_owner}/{repo_name}"
            logger.info(f"DeepWiki auxiliary link: {deepwiki_link}")
            
            deepwiki_content = self._get_deepwiki_content(deepwiki_link)
            
            if deepwiki_content:
                analysis_prompt = f"""
Please analyze this GitHub repository: {repo_name} ({repo_url})

Based on the following DeepWiki page information for analysis:
{deepwiki_content}

Please answer the following questions:
1. What are the main functions and purposes of this repository?
2. What are the core modules and entry points of this repository?
3. What are the main technology stacks and dependencies used by this repository?
        4. Is this project suitable for conversion to MCP (Model Context Protocol) service? Why?

Please provide detailed analysis and recommendations.
"""
                logger.info("Using DeepWiki content to assist LLM analysis...")
            else:
                analysis_prompt = f"""
Please analyze this GitHub repository: {repo_name} ({repo_url})

Please answer the following questions:
1. What are the main functions and purposes of this repository?
2. What are the core modules and entry points of this repository?
3. What are the main technology stacks and dependencies used by this repository?
        4. Is this project suitable for conversion to MCP service? Why?

Please provide detailed analysis and recommendations.
"""
            
            if self.client_type == "anthropic":
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=2000,
                    messages=[
                        {"role": "user", "content": analysis_prompt}
                    ]
                )
                output_text = resp.content[0].text
            elif self.client_type == "deepseek":
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a professional code repository analysis expert, skilled at analyzing GitHub projects and evaluating their suitability for conversion to MCP services. Please provide detailed and accurate analysis."},
                        {"role": "user", "content": analysis_prompt}
                    ],
                    max_tokens=2000,
                    temperature=0.1
                )
                output_text = resp.choices[0].message.content
            else:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a professional code repository analysis expert, skilled at analyzing GitHub projects and evaluating their suitability for conversion to MCP services. Please provide detailed and accurate analysis."},
                        {"role": "user", "content": analysis_prompt}
                    ],
                    max_tokens=2000,
                    temperature=0.1
                )
                output_text = resp.choices[0].message.content
            
            analysis_result = {
                "repo_url": repo_url,
                "repo_name": repo_name,
                "content": deepwiki_content,
                "model": self.model,
                "source": "selenium",
                "success": True
            }
            
            return analysis_result
            
        except Exception as e:
            return {
                "repo_url": repo_url,
                "repo_name": repo_name,
                "error": "DeepWiki analysis failed",
                "model": self.model,
                "source": "llm_direct_analysis",
                "success": False
            }
    
    def _summarize_analysis(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        successful_results = [r for r in results if r.get("success", False)]
        if not successful_results:
            return {"status": "failed", "reason": "All queries failed"}
        
        summary = {
            "status": "success", 
            "total_queries": len(results), 
            "successful_queries": len(successful_results), 
            "key_insights": [],
            "analysis_sources": list(set(r.get("source", "unknown") for r in successful_results))
        }
        
        for result in successful_results:
            output_text = result.get("output_text", "")
            if output_text:
                summary["key_insights"].append({
                    "question": result.get("question", ""), 
                    "insight": output_text[:200] + "..." if len(output_text) > 200 else output_text,
                    "source": result.get("source", "unknown")
                })
        return summary

def get_deepwiki_client(api_key: Optional[str] = None, model: Optional[str] = None) -> DeepWikiClient:
    if not model:
        provider = os.getenv("MODEL_PROVIDER", "openai").lower()
        if provider == "deepseek":
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-v3")
        elif provider == "qwen":
            model = os.getenv("QWEN_MODEL", "qwen-3")
        elif provider == "claude":
            model = os.getenv("CLAUDE_MODEL", "claude-4-sonnet")
        else:
            model = os.getenv("OPENAI_MODEL", "gpt-5")
    

    
    return DeepWikiClient(api_key=api_key, model=model)

if __name__ == "__main__":
    pass