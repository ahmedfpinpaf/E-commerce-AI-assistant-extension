"""
Modular Ollama LLM Client
Connects dynamically to Ollama using OLLAMA_BASE_URL, OLLAMA_MODEL, and OLLAMA_API_KEY
loaded strictly from environment variables (.env).
"""

import os
import json
import logging
from typing import Any, Dict, List, Optional
import requests
from dotenv import load_dotenv

# Ensure environment variables from .env are loaded
load_dotenv()

logger = logging.getLogger("ollama_client")


class OllamaClient:
    """
    Modular client for interacting with the configured Ollama LLM service.
    Reads OLLAMA_BASE_URL, OLLAMA_MODEL, and OLLAMA_API_KEY dynamically at runtime
    from environment variables. No URLs or model names are hardcoded.
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self._override_base_url = base_url
        self._override_model = model
        self._override_api_key = api_key

    @property
    def base_url(self) -> str:
        """Returns the configured Ollama base URL from environment or override."""
        url = self._override_base_url or os.getenv("OLLAMA_BASE_URL") or ""
        return url.rstrip("/")

    @property
    def model(self) -> str:
        """Returns the configured Ollama model name from environment or override."""
        return self._override_model or os.getenv("OLLAMA_MODEL") or ""

    @property
    def api_key(self) -> Optional[str]:
        """Returns the optional API key/token from environment or override."""
        return self._override_api_key or os.getenv("OLLAMA_API_KEY") or None

    def is_configured(self) -> bool:
        """Checks if both base_url and model are set."""
        return bool(self.base_url and self.model)

    def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        timeout: Any = (3.0, 45.0),
    ) -> Dict[str, Any]:
        """
        Sends a conversational completion request to Ollama.
        Supports both native Ollama API (/api/chat) and OpenAI-compatible endpoint (/v1/chat/completions).
        
        Returns:
            Dict containing:
                - content: str (the real-time generated response text)
                - model: str (the model name used)
                - error: Optional[str] (technical exception or failure message, if any)
        """
        base_url = self.base_url
        model = self.model
        api_key = self.api_key

        if not base_url or not model:
            missing = []
            if not base_url:
                missing.append("OLLAMA_BASE_URL")
            if not model:
                missing.append("OLLAMA_MODEL")
            err_msg = f"Ollama LLM is not configured. Missing required environment variable(s): {', '.join(missing)} in .env"
            logger.warning(err_msg)
            return {
                "content": None,
                "model": model or "unconfigured",
                "error": err_msg,
            }

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        options: Dict[str, Any] = {"temperature": temperature}
        if max_tokens:
            options["num_predict"] = max_tokens

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": options,
        }

        # Target endpoint resolution
        if base_url.endswith("/v1"):
            target_url = f"{base_url}/chat/completions"
        elif "/chat" in base_url:
            target_url = base_url
        else:
            target_url = f"{base_url}/api/chat"

        try:
            resp = requests.post(target_url, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                # 1. Native Ollama format: data["message"]["content"]
                if "message" in data and isinstance(data["message"], dict):
                    content = data["message"].get("content", "").strip()
                    return {
                        "content": content,
                        "model": data.get("model", model),
                        "error": None,
                    }
                # 2. OpenAI-compatible format: data["choices"][0]["message"]["content"]
                elif "choices" in data and len(data["choices"]) > 0:
                    choice = data["choices"][0]
                    content = choice.get("message", {}).get("content", "").strip()
                    return {
                        "content": content,
                        "model": data.get("model", model),
                        "error": None,
                    }
                else:
                    return {
                        "content": None,
                        "model": model,
                        "error": f"Unexpected response format from Ollama: {data}",
                    }
            elif resp.status_code == 404 and target_url.endswith("/api/chat"):
                # Fallback to OpenAI-compatible endpoint if /api/chat is not mapped
                fallback_url = f"{base_url}/v1/chat/completions"
                resp2 = requests.post(fallback_url, headers=headers, json=payload, timeout=timeout)
                if resp2.status_code == 200:
                    data2 = resp2.json()
                    choices = data2.get("choices", [])
                    if choices:
                        content = choices[0].get("message", {}).get("content", "").strip()
                        return {
                            "content": content,
                            "model": data2.get("model", model),
                            "error": None,
                        }
                return {
                    "content": None,
                    "model": model,
                    "error": f"Ollama HTTP error {resp.status_code}: {resp.text}",
                }
            else:
                return {
                    "content": None,
                    "model": model,
                    "error": f"Ollama HTTP error {resp.status_code}: {resp.text}",
                }
        except requests.exceptions.RequestException as e:
            logger.error(f"Error connecting to Ollama at {target_url}: {e}")
            return {
                "content": None,
                "model": model,
                "error": f"Failed to connect to Ollama at {base_url}: {str(e)}",
            }


# Shared singleton instance
ollama_client = OllamaClient()
