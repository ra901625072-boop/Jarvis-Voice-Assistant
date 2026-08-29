import os
import requests
import logging
import re

logger = logging.getLogger("JARVIS.OpenRouterText")

def generate_openrouter_text(
    prompt: str,
    system_instruction: str = None,
    model: str = "openrouter/free",
    response_mime_type: str = None,
    max_tokens: int = 600
) -> str:
    """
    Generate text using OpenRouter API with high-quality free/configured models.
    """
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not configured in environment.")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/google/antigravity",
        "X-Title": "JARVIS Voice Assistant"
    }

    messages = []
    if system_instruction:
        messages.append({"role": "system", "content": system_instruction})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens
    }
    
    # OpenRouter JSON format request support
    if response_mime_type == "application/json":
        payload["response_format"] = {"type": "json_object"}

    api_url = "https://openrouter.ai/api/v1/chat/completions"
    logger.info(f"Sending text query to OpenRouter using model {model}...")
    response = requests.post(api_url, headers=headers, json=payload, timeout=60)
    
    # If 400 occurred due to unsupported response_format, retry without response_format
    if response.status_code == 400 and response_mime_type == "application/json":
        logger.warning(f"OpenRouter 400 on model {model} with response_format. Retrying without response_format...")
        payload.pop("response_format", None)
        response = requests.post(api_url, headers=headers, json=payload, timeout=60)

    if response.status_code == 402 and max_tokens > 150:
        logger.warning(f"OpenRouter 402 credit limit hit for max_tokens={max_tokens}. Retrying with max_tokens=120...")
        payload["max_tokens"] = 120
        response = requests.post(api_url, headers=headers, json=payload, timeout=30)

    if response.status_code == 200:
        data = response.json()
        choices = data.get("choices", [])
        if choices:
            msg = choices[0].get("message", {})
            content = msg.get("content")
            if content is None:
                content = msg.get("reasoning") or ""
            content = str(content).strip()
            logger.info("Successfully received response from OpenRouter.")
            
            # Clean up reasoning / thought blocks if calling code expects JSON
            if response_mime_type == "application/json" and "<think>" in content:
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                
            return content
        raise ValueError("Empty response structure from OpenRouter.")
    else:
        logger.error(f"OpenRouter Error status {response.status_code}: {response.text}")
        raise RuntimeError(f"OpenRouter API returned status code {response.status_code}: {response.text}")
