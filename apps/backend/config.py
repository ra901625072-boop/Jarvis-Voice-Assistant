import os
from dotenv import load_dotenv

_env_loaded = False

def load_config():
    global _env_loaded
    if not _env_loaded:
        env_path = os.path.join(os.path.dirname(__file__), ".env")
        load_dotenv(env_path, override=True)
        
        # Align Gemini/Google API keys to prioritize user's GEMINI_API_KEY
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            os.environ["GOOGLE_API_KEY"] = gemini_key
            
        _env_loaded = True

AGENT_TIMEOUTS = {
    "coding_agent": 60.0,
    "browser_agent": 45.0,
    "execution_agent": 30.0,
    "debugging_agent": 45.0,
    "vision_agent": 20.0,
    "memory_agent": 10.0,
}
