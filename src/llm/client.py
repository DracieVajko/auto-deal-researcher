import requests
import logging

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, config):
        self.config = config
        
    def generate_search_query(self, product_description):
        """Generate search queries using LLM"""
        # This is a simplified implementation - in practice would call actual LLM API
        prompt = f"Generate search query for: {product_description}"
        
        if self.config.search.llm.api_key:
            # Cloud API fallback
            api_url = "https://api.openai.com/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {self.config.search.llm.api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.config.search.llm.model_name,
                "messages": [{"role": "user", "content": prompt}]
            }
            response = requests.post(api_url, headers=headers, json=payload)
            return response.json()["choices"][0]["message"]["content"]
        else:
            # Local LLM fallback (Ollama)
            try:
                api_url = f"{self.config.search.llm.local_endpoint}/api/generate"
                payload = {
                    "model": self.config.search.llm.model_name,
                    "prompt": prompt
                }
                response = requests.post(api_url, json=payload)
                return response.json()["response"]
            except Exception as e:
                logger.error(f"Failed to connect to local LLM: {e}")
                # Fallback to simple query generation
                return product_description

    def judge_results(self, results):
        """Judge and rank search results"""
        # Implementation would use LLM to filter and rank results
        return results