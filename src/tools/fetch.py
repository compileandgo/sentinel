import requests
import trafilatura
from typing import Optional

def fetch_article(url: str, max_chars: int = 5000) -> str:
    """
    Fetches the HTML content of the URL and extracts its main text content using trafilatura.
    Truncates the output to max_chars.
    """
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        # Fetch content with timeout
        response = requests.get(url, headers=headers, timeout=8, allow_redirects=True)
        if response.status_code != 200:
            return ""

        # Extract main text
        downloaded = response.text
        text = trafilatura.extract(downloaded, include_comments=False, include_tables=True) or ""
        
        # Return cleaned text capped at max_chars
        cleaned_text = text.strip()
        if len(cleaned_text) > max_chars:
            return cleaned_text[:max_chars] + "\n... [TRUNCATED] ..."
        return cleaned_text

    except Exception as e:
        # Silently fail, return empty string so we fallback to snippet
        return ""
