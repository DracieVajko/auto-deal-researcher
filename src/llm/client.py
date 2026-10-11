import requests
import logging

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, config):
        self.config = config
        self.llm_config = config.search.llm

    def generate_search_query(self, product_description):
        """Generate search queries using LLM"""
        prompt = f"Generate an optimized search query for an e-commerce site based on this product description: {product_description}. Return only the search query string, nothing else."
        
        # Try local LLM first (LM Studio / Ollama)
        try:
            return self._call_local_llm(prompt)
        except Exception as e:
            logger.warning(f"Local LLM failed: {e}, trying cloud providers...")
        
        # Try cloud providers in order
        for provider in ["openrouter", "gemini", "mistral"]:
            api_key = getattr(self.llm_config, provider, None)
            if api_key:
                try:
                    return self._call_cloud_llm(provider, api_key, prompt)
                except Exception as e:
                    logger.warning(f"{provider.capitalize()} API failed: {e}")
        
        # Final fallback
        logger.error("All LLM providers failed, using raw prompt")
        return product_description

    def _call_local_llm(self, prompt):
        """Call local LLM (Ollama or LM Studio)"""
        api_url = f"{self.llm_config.local_endpoint}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        payload = {
            "model": self.llm_config.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 100
        }
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def _call_cloud_llm(self, provider, api_key, prompt):
        """Call cloud LLM API"""
        if provider == "openrouter":
            return self._call_openrouter(api_key, prompt)
        elif provider == "gemini":
            return self._call_gemini(api_key, prompt)
        elif provider == "mistral":
            return self._call_mistral(api_key, prompt)
        else:
            raise ValueError(f"Unknown provider: {provider}")

    def _call_openrouter(self, api_key, prompt):
        api_url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/DracieVajko/auto-deal-searcher-beta",
            "X-Title": "Auto Deal Searcher"
        }
        payload = {
            "model": self.llm_config.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 100
        }
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def _call_gemini(self, api_key, prompt):
        api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 100
            }
        }
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["candidates"][0]["content"]["parts"][0]["text"].strip()

    def _call_mistral(self, api_key, prompt):
        api_url = "https://api.mistral.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_config.model_name if "mistral" in self.llm_config.model_name.lower() else "mistral-large-latest",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 100
        }
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()

    def judge_results(self, results, query):
        """Judge and rank search results using LLM"""
        if not results:
            return results
        
        # Create a prompt for the LLM to judge results
        results_text = "\n".join([
            f"{i+1}. {r.get('title', 'N/A')} - {r.get('price', 'N/A')} - {r.get('link', 'N/A')} - {r.get('website', 'N/A')}"
            for i, r in enumerate(results)
        ])
        
        prompt = f"""You are a deal evaluator. Given the search query: "{query}"
        
Evaluate these search results and rank them from best to worst match:
{results_text}

Return ONLY a JSON array of indices (0-based) in order from best to worst match. Example: [2, 0, 1]"""
        
        try:
            judgment = self.generate_search_query(prompt)  # Reuse the same LLM call logic
            import json
            ranking = json.loads(judgment)
            
            # Reorder results based on ranking
            ranked_results = [results[i] for i in ranking if i < len(results)]
            return ranked_results
        except Exception as e:
            logger.warning(f"LLM judgment failed: {e}, returning original order")
            return results