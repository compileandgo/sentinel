# External Integrations & LLM Key Pools

Sentinel integrates with multiple external search providers, news APIs, and Large Language Model (LLM) services in `src/tools/llm.py` and `src/tools/search.py`.

---

## Key Libraries Used

* **`langchain-google-genai`**: Wrapper for Google Gemini models (`gemini-3.5-flash`, `gemini-3.1-flash-lite`).
* **`langchain-groq`**: Wrapper for Groq LPUs running `llama-3.3-70b-versatile`.
* **`tavily-python`**: Client for Tavily AI Web Search API.
* **`duckduckgo-search`**: Fallback web search provider when Tavily is unconfigured.
* **`requests` / `httpx`**: HTTP clients for querying the GDELT Project API.

---

## Multi-Key Pool & Round-Robin Load Balancing (`src/config.py`)

To prevent API rate limits (`HTTP 429`) from stopping execution, `Config` loads key pools for Google Gemini and Groq:

```python
def _load_key_pool(primary_env: str, numbered_prefix: str) -> list:
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
 GOOGLE_API_KEYS: list = _load_key_pool("GOOGLE_API_KEY", "GOOGLE_API_KEY")
 GROQ_API_KEYS: list = _load_key_pool("GROQ_API_KEY", "GROQ_API_KEY")
```

If `GOOGLE_API_KEY`, `GOOGLE_API_KEY_1`, `GOOGLE_API_KEY_2` are present in `.env`, Sentinel automatically cycles through them.

---

## Failover & Self-Healing Retry Logic (`src/tools/llm.py`)

When an LLM call fails due to service overload (`HTTP 503`), Sentinel automatically fails over to the next available API key or Groq model:

```python
def safe_llm_invoke(messages, model=None, temperature=None):
 # Try Primary Model (Gemini 3.5 Flash)
 try:
 llm = make_llm(model=model, temperature=temperature)
 return llm.invoke(messages)
 except Exception as e:
 print(f"Primary LLM failed ({e}). Retrying with fallback model...")
 # Failover to Fallback Model (Gemini 3.1 Flash Lite or Groq)
 fallback_llm = make_llm(model=Config.FALLBACK_MODEL, temperature=temperature)
 return fallback_llm.invoke(messages)
```

---

## External Search Tools

### 1. Tavily AI Search (`src/tools/search.py`)
* **Use Case**: Deep web search tailored for LLM context retrieval.
* **Function**: Returns cleaned page snippets and direct URL citations.

### 2. GDELT Project API (`src/tools/gdelt.py`)
* **Use Case**: Real-time global geopolitical news event monitoring.
* **Function**: Queries GDELT's DOC 2.0 API for news mentions, tone scores, and publication dates.
