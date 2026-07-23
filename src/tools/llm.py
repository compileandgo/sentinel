import os
import time
import re
import threading
from typing import List, Optional
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import BaseMessage
from src.config import Config

thread_local = threading.local()

# ── Per-key exhaustion tracking ───────────────────────────────────────────────
# Maps api_key → True if permanently quota-exhausted
_gemini_exhausted: dict = {}
_groq_exhausted: dict = {}

def _is_rate_error(msg: str) -> bool:
    return any(k in msg for k in ("429", "rate limit", "resource_exhausted", "quota", "limit", "too many"))


def _is_overload_error(msg: str) -> bool:
    """503 / service unavailable — model is overloaded, not quota-exhausted."""
    return any(k in msg for k in ("503", "unavailable", "overloaded", "high demand", "try again later"))


def _is_permanent_quota(msg: str) -> bool:
    """Permanent (billing/daily quota, invalid key) vs transient (per-minute RPM) error."""
    permanent_indicators = (
        "daily quota", "daily limit", "quota exceeded", "quota_exceeded", 
        "credit", "billing", "blocked", "key not valid", "api_key_invalid", 
        "invalid api key", "invalid key", "not authorized", "forbidden"
    )
    return any(k in msg for k in permanent_indicators)


def _parse_retry_wait(err_msg: str, default: float = 3.0) -> float:
    """Extract wait seconds from Groq 'try again in X.XXs' messages."""
    m = re.search(r"try again in (\d+(?:\.\d+)?)s", err_msg)
    return float(m.group(1)) + 0.5 if m else default


def _invoke_with_retry(llm_client, messages, name: str = "LLM", max_attempts: int = 3):
    """Single-key retry with backoff on transient rate limits and 503 overloads."""
    for attempt in range(max_attempts):
        try:
            return llm_client.invoke(messages)
        except Exception as e:
            msg = str(e).lower()
            is_last = attempt >= max_attempts - 1
            if _is_overload_error(msg) and not is_last:
                # Exponential backoff for 503: 5s, 15s
                wait = 5.0 * (3 ** attempt)
                print(f"  [{name}] 503 Overloaded. Waiting {wait:.0f}s before retry (attempt {attempt + 1}/{max_attempts})...")
                time.sleep(wait)
            elif _is_rate_error(msg) and not is_last:
                wait = _parse_retry_wait(msg, default=(attempt + 1) * 3.0)
                print(f"  [{name}] Rate limit hit. Waiting {wait:.1f}s (attempt {attempt + 1}/{max_attempts})...")
                time.sleep(wait)
            else:
                raise


def _clean_response(res):
    if not res:
        return res
    if hasattr(res, "content"):
        content = res.content
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, str):
                    text_parts.append(part)
                elif isinstance(part, dict) and "text" in part:
                    text_parts.append(part["text"])
            res.content = "".join(text_parts)
        elif not isinstance(content, str):
            res.content = str(content)
        
        # Clean up double spacing / extra white spaces if applicable
        if isinstance(res.content, str):
            res.content = re.sub(r" {50,}", " ", res.content)
    return res


def _check_cancellation():
    run_id = getattr(thread_local, "run_id", None)
    if run_id:
        try:
            from src.web.app import active_cancellations
            if run_id in active_cancellations:
                raise RuntimeError("Research cancelled by user")
        except ImportError:
            pass


# ── Public API ────────────────────────────────────────────────────────────────

def make_llm(model: Optional[str] = None, temperature: Optional[float] = None) -> ChatGoogleGenerativeAI:
    """Instantiate Gemini with the first non-exhausted key in the pool."""
    for key in Config.GOOGLE_API_KEYS:
        if not _gemini_exhausted.get(key):
            return ChatGoogleGenerativeAI(
                model=model or Config.LLM_MODEL,
                temperature=temperature if temperature is not None else Config.LLM_TEMPERATURE,
                google_api_key=key,
                timeout=60.0,
            )
    # All exhausted — return first key anyway (will fail gracefully)
    key = Config.GOOGLE_API_KEYS[0] if Config.GOOGLE_API_KEYS else os.getenv("GOOGLE_API_KEY", "")
    return ChatGoogleGenerativeAI(
        model=model or Config.LLM_MODEL,
        temperature=temperature if temperature is not None else Config.LLM_TEMPERATURE,
        google_api_key=key,
        timeout=60.0,
    )


def _try_gemini_pool(messages, model, temperature):
    import random
    keys = Config.GOOGLE_API_KEYS.copy()
    if not keys:
        raise RuntimeError("no gemini API keys configured.")
    
    # Shuffle keys to distribute parallel requests across keys and avoid RPM rate limits
    random.shuffle(keys)

    last_err = None
    primary_model = model or Config.LLM_MODEL
    # Fallback model when primary is overloaded (503)
    fallback_model = Config.FALLBACK_MODEL

    for attempt_model in ([primary_model] + ([fallback_model] if fallback_model and fallback_model != primary_model else [])):
        for key in keys:
            if _gemini_exhausted.get(key):
                print(f"  gemini: skipping exhausted key ...{key[-6:]}")
                continue
            try:
                llm = ChatGoogleGenerativeAI(
                    model=attempt_model,
                    temperature=temperature if temperature is not None else Config.LLM_TEMPERATURE,
                    google_api_key=key,
                    timeout=60.0,
                )
                result = _invoke_with_retry(llm, messages, name=f"Gemini[{attempt_model}...{key[-6:]}]")
                if attempt_model != primary_model:
                    print(f"  [Gemini] Used fallback model {attempt_model} (primary was overloaded).")
                return result
            except Exception as e:
                msg = str(e).lower()
                if _is_permanent_quota(msg):
                    print(f"  [Gemini] Key ...{key[-6:]} permanently exhausted — blacklisting.")
                    _gemini_exhausted[key] = True
                elif _is_overload_error(msg):
                    # 503 = model overloaded, not key exhausted — don't blacklist
                    print(f"  [Gemini] {attempt_model} overloaded on key ...{key[-6:]}: {e}")
                else:
                    print(f"  [Gemini] Key ...{key[-6:]} transient error: {e}")
                last_err = e

    raise last_err or RuntimeError("All Gemini keys failed.")


def _try_groq_pool(messages, temperature):
    """Try each Groq key in order, skipping permanently exhausted ones."""
    import random
    keys = Config.GROQ_API_KEYS.copy()
    if not keys:
        raise RuntimeError("No Groq API keys configured.")
    
    # Shuffle keys to load-balance parallel requests
    random.shuffle(keys)

    last_err = None
    for key in keys:
        if _groq_exhausted.get(key):
            print(f"  [Groq] Skipping exhausted key ...{key[-6:]}")
            continue
        try:
            from langchain_groq import ChatGroq
            llm = ChatGroq(
                model=Config.GROQ_MODEL,
                temperature=temperature if temperature is not None else Config.LLM_TEMPERATURE,
                groq_api_key=key,
                timeout=60.0,
            )
            result = _invoke_with_retry(llm, messages, name=f"Groq[...{key[-6:]}]")
            return result
        except Exception as e:
            msg = str(e).lower()
            if _is_permanent_quota(msg):
                print(f"  [Groq] Key ...{key[-6:]} permanently exhausted — blacklisting.")
                _groq_exhausted[key] = True
            else:
                print(f"  [Groq] Key ...{key[-6:]} transient error: {e}")
            last_err = e

    raise last_err or RuntimeError("All Groq keys failed.")


def safe_llm_invoke(
    messages: List[BaseMessage],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> BaseMessage:
    """
    Invoke LLM with multi-key fallback:
      1. Try each Gemini key in pool (skip permanently exhausted ones)
      2. If all Gemini keys fail → try each Groq key in pool
      3. If all Groq keys also fail → raise the original Gemini error
    """
    _check_cancellation()

    # ── Gemini pool ──────────────────────────────────────────────────────────
    all_gemini_exhausted = all(_gemini_exhausted.get(k) for k in Config.GOOGLE_API_KEYS) if Config.GOOGLE_API_KEYS else True

    if not all_gemini_exhausted:
        try:
            return _clean_response(_try_gemini_pool(messages, model, temperature))
        except Exception as gemini_err:
            print(f"  [Gemini pool] All available keys failed. Falling back to Groq pool...")
            gemini_fallback_err = gemini_err
    else:
        print(f"  [Gemini pool] All keys exhausted. Going straight to Groq pool...")
        gemini_fallback_err = RuntimeError("All Gemini keys permanently exhausted.")

    # ── Groq pool ────────────────────────────────────────────────────────────
    if Config.GROQ_API_KEYS:
        try:
            return _clean_response(_try_groq_pool(messages, temperature))
        except Exception as groq_err:
            print(f"  [Groq pool] All Groq keys also failed: {groq_err}")
            raise gemini_fallback_err  # surface the original Gemini error
    else:
        raise gemini_fallback_err


def safe_gemini_invoke(
    messages: List[BaseMessage],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
) -> BaseMessage:
    """Invoke Gemini pool exclusively, raising error if all keys fail."""
    _check_cancellation()
    all_gemini_exhausted = all(_gemini_exhausted.get(k) for k in Config.GOOGLE_API_KEYS) if Config.GOOGLE_API_KEYS else True
    if all_gemini_exhausted:
        raise RuntimeError("All Gemini keys permanently exhausted.")
    return _clean_response(_try_gemini_pool(messages, model, temperature))


def safe_groq_invoke(
    messages: List[BaseMessage],
    temperature: Optional[float] = None,
) -> BaseMessage:
    """Invoke Groq pool exclusively, raising error if all keys fail or none configured."""
    _check_cancellation()
    if not Config.GROQ_API_KEYS:
        raise RuntimeError("No Groq API keys configured.")
    all_groq_exhausted = all(_groq_exhausted.get(k) for k in Config.GROQ_API_KEYS)
    if all_groq_exhausted:
        raise RuntimeError("All Groq keys permanently exhausted.")
    return _clean_response(_try_groq_pool(messages, temperature))


class FastEmbedWrapper:
    def __init__(self, model_name: str = "BAAI/bge-base-en-v1.5"):
        from fastembed import TextEmbedding
        self.model = TextEmbedding(model_name=model_name)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        embeddings = list(self.model.embed(texts))
        return [e.tolist() for e in embeddings]

    def embed_query(self, text: str) -> List[float]:
        embeddings = list(self.model.embed([text]))
        return embeddings[0].tolist()

_embeddings_singleton = None

def make_embeddings():
    """Returns a local CPU FastEmbed instance (768 dimensions, BAAI/bge-base-en-v1.5)."""
    global _embeddings_singleton
    if _embeddings_singleton is None:
        _embeddings_singleton = FastEmbedWrapper("BAAI/bge-base-en-v1.5")
    return _embeddings_singleton
