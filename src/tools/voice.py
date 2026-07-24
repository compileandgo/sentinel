import os
import httpx
from typing import Optional
from src.config import Config

# Domain vocabulary prompt to guide Whisper on technical/project-specific jargon
DOMAIN_PROMPT = (
    "Sentinel, RAG, Pinecone, Supabase, GDELT, Geopolitical, LLM, "
    "Cosine, Vector, Search, Research, Intelligence, Analysis, Sedition"
)

async def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """
    Transcribes raw audio bytes using Groq Whisper-v3 API.
    Falls back to empty string if no API key is available or request fails.
    """
    keys = Config.GROQ_API_KEYS.copy()
    if not keys:
        print("  [Voice STT] Warning: No GROQ_API_KEYS configured.")
        return ""

    for key in keys:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                files = {
                    "file": (filename, audio_bytes, "audio/webm")
                }
                data = {
                    "model": "whisper-large-v3",
                    "prompt": DOMAIN_PROMPT,
                    "temperature": "0.0",
                    "response_format": "json"
                }
                headers = {
                    "Authorization": f"Bearer {key}"
                }
                response = await client.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files
                )
                if response.status_code == 200:
                    res_json = response.json()
                    text = res_json.get("text", "").strip()
                    print(f"  [Voice STT] Transcribed: '{text}'")
                    return text
                else:
                    print(f"  [Voice STT] Groq API returned status {response.status_code}: {response.text}")
        except Exception as e:
            print(f"  [Voice STT] Error calling Whisper API with key ...{key[-6:]}: {e}")

    return ""
