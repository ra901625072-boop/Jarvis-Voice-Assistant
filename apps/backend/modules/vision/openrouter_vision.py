import os
import requests
import logging

logger = logging.getLogger("JARVIS.OpenRouterVision")

class OpenRouterVisionClient:
    """
    Client for OpenRouter vision API.
    """
    def __init__(self):
        self.api_key = os.getenv("OPENROUTER_API_KEY")
        self.api_url = "https://openrouter.ai/api/v1/chat/completions"

    def analyze_image(self, base64_image: str, prompt: str, model: str = "qwen/qwen2.5-vl-72b-instruct", max_tokens: int = 1024) -> str:
        api_key = self.api_key or os.getenv("OPENROUTER_API_KEY")
        if not api_key:
            return "Error: OPENROUTER_API_KEY is not configured in environment."

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/google/antigravity",
            "X-Title": "JARVIS Voice Assistant"
        }

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ]

        target_tokens = min(max_tokens, 250)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": target_tokens
        }


        try:
            logger.info(f"Sending image query to OpenRouter using model {model} (max_tokens={target_tokens})...")
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=15)
            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "").strip()
                    logger.info("Successfully received analysis from OpenRouter.")
                    return content
                return "Error: Empty response structure from OpenRouter."
            elif response.status_code in (402, 429):
                logger.warning(f"OpenRouter Vision credit limit/exhausted (HTTP {response.status_code}). Falling back to Gemini Vision immediately.")
                return f"Error: OpenRouter API returned status code {response.status_code}."
            else:
                logger.error(f"OpenRouter Error status {response.status_code}: {response.text}")
                return f"Error: OpenRouter API returned status code {response.status_code}."
        except Exception as e:
            logger.warning(f"Failed to query OpenRouter Vision API: {e}")
            return f"Error: Exception occurred during OpenRouter query: {str(e)}"
