import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def _load_key_pool(primary_env: str, numbered_prefix: str) -> list:
    """Collect all non-empty keys: primary key + any GOOGLE_API_KEY_1, _2, _3... etc."""
    keys = []
    primary = os.getenv(primary_env, "").strip()
    if primary:
        keys.append(primary)
    i = 1
    while True:
        key = os.getenv(f"{numbered_prefix}_{i}", "").strip()
        if not key:
            break
        if key not in keys:
            keys.append(key)
        i += 1
    return keys

class Config:
    # LLM settings
    LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    SUBAGENT_MODEL = os.getenv("SUBAGENT_MODEL", "gemini-2.5-flash")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    # Multi-key pools (primary + numbered extras)
    GOOGLE_API_KEYS: list = _load_key_pool("GOOGLE_API_KEY", "GOOGLE_API_KEY")
    GROQ_API_KEYS: list = _load_key_pool("GROQ_API_KEY", "GROQ_API_KEY")

    # Single-key aliases for backward compat
    @classmethod
    def get_google_api_key(cls) -> str:
        return cls.GOOGLE_API_KEYS[0] if cls.GOOGLE_API_KEYS else ""

    @classmethod
    def get_groq_api_key(cls) -> str:
        return cls.GROQ_API_KEYS[0] if cls.GROQ_API_KEYS else ""

    # Backward compat properties
    GROQ_API_KEY = property(lambda self: Config.get_groq_api_key())

    # Search settings
    SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "tavily")  # "tavily" | "duckduckgo"
    TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

    # Cost controls
    MAX_RESEARCH_ITERATIONS = int(os.getenv("MAX_RESEARCH_ITERATIONS", "1"))
    MAX_SEARCH_CALLS_PER_SUBAGENT = int(os.getenv("MAX_SEARCH_CALLS_PER_SUBAGENT", "2"))
    MAX_SUBAGENTS = int(os.getenv("MAX_SUBAGENTS", "3"))

    # Output settings
    OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
    SUBAGENT_DIR = OUTPUT_DIR / "subagents"

    # Optional feature flags
    ENABLE_GDELT = os.getenv("ENABLE_GDELT", "false").lower() == "true"
    ENABLE_RSS_FEEDS = os.getenv("ENABLE_RSS_FEEDS", "false").lower() == "true"
    ENABLE_LOCAL_CACHE = os.getenv("ENABLE_LOCAL_CACHE", "false").lower() == "true"
    ENABLE_CROSS_MODEL_BIAS = os.getenv("ENABLE_CROSS_MODEL_BIAS_CHECK", "false").lower() == "true"

    # Legacy single-key reads (still work if only one key set)
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")

# Ensure folders exist
Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
Config.SUBAGENT_DIR.mkdir(parents=True, exist_ok=True)
