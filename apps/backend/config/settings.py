import os
from dotenv import load_dotenv

_backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("JARVIS_DATA_DIR", os.path.join(_backend_root, "database"))
CHROMA_DIR = os.environ.get("JARVIS_CHROMA_DIR", os.path.join(_backend_root, "chroma"))


_env_loaded = False

def load_config():
    global _env_loaded
    if not _env_loaded:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        load_dotenv(env_path, override=True)
        
        # Align Gemini/Google API keys to prioritize user's GEMINI_API_KEY
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if gemini_key:
            os.environ["GOOGLE_API_KEY"] = gemini_key
            
        _env_loaded = True

# Eagerly load .env so all following module-level dictionaries and settings read it
load_config()

AGENT_TIMEOUTS = {
    "coding_agent": 300.0,
    "browser_agent": 300.0,
    "execution_agent": 600.0,
    "debugging_agent": 300.0,
    "vision_agent": 300.0,
    "memory_agent": 45.0,
    "planning_agent": 300.0,
    "coordinator_agent": 600.0,
    "supervisor_agent": 45.0,
    "verification_agent": 300.0,
    "recovery_agent": 300.0,
    "integration_agent":300.0,
    "interaction_agent":300.0,
    "ui_ux_agent":       300.0,
    "social_media_agent":300.0,
}

# Proactive Speech Settings
JARVIS_PROACTIVE_SPEECH_ENABLED = os.environ.get("JARVIS_PROACTIVE_SPEECH_ENABLED", "true").lower() == "true"
JARVIS_ANNOUNCE_MILESTONES = [int(x.strip()) for x in os.environ.get("JARVIS_ANNOUNCE_MILESTONES", "25,50,75,100").split(",") if x.strip().isdigit()]
JARVIS_ANNOUNCE_BATCH_WINDOW_SEC = float(os.environ.get("JARVIS_ANNOUNCE_BATCH_WINDOW_SEC", "1.5"))
JARVIS_ANNOUNCE_MIN_TASK_DURATION_SEC = float(os.environ.get("JARVIS_ANNOUNCE_MIN_TASK_DURATION_SEC", "5"))
JARVIS_ANNOUNCE_DEFAULT_PRIORITY = os.environ.get("JARVIS_ANNOUNCE_DEFAULT_PRIORITY", "normal")

# LLM Model Configurations & Routing Maps
GROQ_MODEL_MAP = {
    "supervisor_agent": os.environ.get("JARVIS_GROQ_MODEL_SUPERVISOR", "openai/gpt-oss-120b"),
    "execution_agent":  os.environ.get("JARVIS_GROQ_MODEL_EXECUTION", "openai/gpt-oss-120b"),
    "memory_agent":     os.environ.get("JARVIS_GROQ_MODEL_MEMORY", "openai/gpt-oss-20b"),
    "coding_agent":     os.environ.get("JARVIS_GROQ_MODEL_CODING", "openai/gpt-oss-120b"),
    "browser_agent":    os.environ.get("JARVIS_GROQ_MODEL_BROWSER", "openai/gpt-oss-120b"),
    "integration_agent":os.environ.get("JARVIS_GROQ_MODEL_INTEGRATION", "openai/gpt-oss-120b"),
    "planning_agent":   os.environ.get("JARVIS_GROQ_MODEL_PLANNING", "openai/gpt-oss-120b"),
    "coordinator_agent":os.environ.get("JARVIS_GROQ_MODEL_COORDINATOR", "openai/gpt-oss-120b"),
    "ui_ux_agent":      os.environ.get("JARVIS_GROQ_MODEL_UI_UX", "openai/gpt-oss-120b"),
    "social_media_agent":os.environ.get("JARVIS_GROQ_MODEL_SOCIAL_MEDIA", "openai/gpt-oss-120b"),
    "verification_agent":os.environ.get("JARVIS_GROQ_MODEL_VERIFICATION", "openai/gpt-oss-20b"),
    "debugging_agent":  os.environ.get("JARVIS_GROQ_MODEL_DEBUGGING", "openai/gpt-oss-120b"),
}
DEFAULT_GROQ_MODEL = os.environ.get("JARVIS_DEFAULT_GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_FALLBACK_CHAIN = [
    x.strip() for x in os.environ.get(
        "JARVIS_GROQ_FALLBACK_CHAIN",
        "openai/gpt-oss-120b,openai/gpt-oss-20b,qwen/qwen3.6-27b,qwen/qwen3.8-27b,groq/compound"
    ).split(",")
]


OPENROUTER_MODEL_MAP = {
    "coding_agent":       os.environ.get("JARVIS_OPENROUTER_MODEL_CODING", "qwen/qwen-2.5-coder-32b-instruct:free"),
    "debugging_agent":    os.environ.get("JARVIS_OPENROUTER_MODEL_DEBUGGING", "deepseek/deepseek-r1:free"),
    "planning_agent":     os.environ.get("JARVIS_OPENROUTER_MODEL_PLANNING", "deepseek/deepseek-r1:free"),
    "coordinator_agent":  os.environ.get("JARVIS_OPENROUTER_MODEL_COORDINATOR", "openrouter/free"),
    "recovery_agent":     os.environ.get("JARVIS_OPENROUTER_MODEL_RECOVERY", "deepseek/deepseek-r1:free"),
    "social_media_agent": os.environ.get("JARVIS_OPENROUTER_MODEL_SOCIAL_MEDIA", "openrouter/free"),
    "verification_agent": os.environ.get("JARVIS_OPENROUTER_MODEL_VERIFICATION", "openrouter/free"),
    "research_agent":     os.environ.get("JARVIS_OPENROUTER_MODEL_RESEARCH", "openrouter/free"),
    "language_agent":     os.environ.get("JARVIS_OPENROUTER_MODEL_LANGUAGE", "openrouter/free"),
    "interaction_agent":  os.environ.get("JARVIS_OPENROUTER_MODEL_INTERACTION", "openrouter/free"),
    "ui_ux_agent":        os.environ.get("JARVIS_OPENROUTER_MODEL_UI_UX", "openrouter/free"),
}
DEFAULT_OPENROUTER_MODEL = os.environ.get("JARVIS_DEFAULT_OPENROUTER_MODEL", "openrouter/free")

OPENROUTER_FREE_FALLBACK_CHAIN = [
    x.strip() for x in os.environ.get(
        "JARVIS_OPENROUTER_FREE_FALLBACK_CHAIN",
        "openrouter/free,meta-llama/llama-3.3-70b-instruct:free,meta-llama/llama-3.2-3b-instruct:free,mistralai/mistral-small-24b-instruct-2501:free,qwen/qwen-2.5-coder-32b-instruct:free,qwen/qwen-2.5-72b-instruct:free,deepseek/deepseek-r1:free"
    ).split(",")
]

DEFAULT_GEMINI_MODEL = os.environ.get("JARVIS_DEFAULT_GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_FALLBACK_CHAIN = [
    x.strip() for x in os.environ.get(
        "JARVIS_GEMINI_FALLBACK_CHAIN",
        "gemini-3.5-flash,gemini-3.5-flash-lite,gemini-3.6-flash,gemini-flash-lite-latest,gemini-3.7-flash,gemini-2.5-flash,gemini-3.1-pro-preview"
    ).split(",")
]

DEFAULT_LIVEKIT_MODEL = os.environ.get("LIVEKIT_GEMINI_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")

JARVIS_CORS_ORIGINS = [
    x.strip() for x in os.environ.get("JARVIS_CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if x.strip()
]

# Dedicated Browser & Account Profile Settings
JARVIS_BROWSER_TYPE = os.environ.get("JARVIS_BROWSER_TYPE", "msedge").lower().strip()
JARVIS_BROWSER_PROFILE_DIR = os.environ.get(
    "JARVIS_BROWSER_PROFILE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "browser_profile")
)
JARVIS_BROWSER_HEADLESS = os.environ.get("JARVIS_BROWSER_HEADLESS", "false").lower().strip() in ("true", "1", "yes")
JARVIS_AUTO_OPEN_BROWSER = os.environ.get("JARVIS_AUTO_OPEN_BROWSER", "true").lower().strip() in ("true", "1", "yes")
JARVIS_BROWSER_STARTUP_URL = os.environ.get("JARVIS_BROWSER_STARTUP_URL", "http://localhost:8000")

