import os
import asyncio
import logging
import aiohttp
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

# Configuration
JINA_API_KEY = os.environ.get("JINA_API_KEY")
JINA_MAX_CHARS = int(os.environ.get("JINA_MAX_CHARS", 20000))
JINA_TIMEOUT_SEC = float(os.environ.get("JINA_TIMEOUT_SEC", 15.0))
JINA_CONCURRENCY = int(os.environ.get("JINA_CONCURRENCY", 4))
JINA_REMOVE_OVERLAY = os.environ.get("JINA_REMOVE_OVERLAY", "true").lower() == "true"
JINA_TOKEN_BUDGET = os.environ.get("JINA_TOKEN_BUDGET", "")
JINA_LOCALE = os.environ.get("JINA_LOCALE", "")
JINA_RESPOND_TIMING = os.environ.get("JINA_RESPOND_TIMING", "network-idle")
JINA_REMOVE_SELECTOR = os.environ.get("JINA_REMOVE_SELECTOR", "header, footer, nav, aside, .sidebar, .comments, #comments, .advertisement, .nav, .menu")

TRUNCATION_MARKER = "\n\n[...ТЕКСТ ОБРЕЗАН — достигнут лимит контекста...]"

def truncate_content(text: str, max_chars: int) -> str:
    """Safely trims text to max_chars and adds a marker if truncated."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + TRUNCATION_MARKER

def is_blocked_content(text: str) -> bool:
    """Heuristic check for paywalls, captchas, or failed extraction."""
    if not text or len(text) < 200:
        return True
        
    # Check length-to-word ratio (if average word is > 15 chars, it's likely binary noise/gibberish)
    words = text.split()
    if words and (len(text) / len(words)) > 15:
        return True
    
    blocked_phrases = [
        "Just a moment", 
        "Checking your browser",
        "requires a subscription", 
        "Access denied",
        "Enable JavaScript", 
        "403 Forbidden",
        "Cloudflare",
        "This content is for subscribers",
        "Please enable cookies",
        "verify you are human",
        "429 Too Many Requests"
    ]
    
    # Check lowercase to be safe
    text_lower = text.lower()
    return any(phrase.lower() in text_lower for phrase in blocked_phrases)

async def fetch_url(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Fetches a single URL via Jina Reader API."""
    logger.info(f"Jina: Extracting content from {url}...")
    headers = {
        "Accept": "text/markdown",
        "X-Retain-Images": "none",
        "X-Retain-Links": "none",
        "X-Md-Heading-Style": "atx",
        "X-Md-Link-Style": "discarded"
    }
    
    if JINA_REMOVE_OVERLAY:
        headers["X-Remove-Overlay"] = "true"
    if JINA_REMOVE_SELECTOR:
        headers["X-Remove-Selector"] = JINA_REMOVE_SELECTOR
    if JINA_TOKEN_BUDGET:
        headers["X-Token-Budget"] = JINA_TOKEN_BUDGET
    if JINA_LOCALE:
        headers["X-Locale"] = JINA_LOCALE
    if JINA_RESPOND_TIMING:
        headers["X-Respond-Timing"] = JINA_RESPOND_TIMING
    if JINA_API_KEY:
        headers["Authorization"] = f"Bearer {JINA_API_KEY}"
        
    jina_url = f"https://r.jina.ai/{url}"
    
    try:
        timeout = aiohttp.ClientTimeout(total=JINA_TIMEOUT_SEC)
        async with session.get(jina_url, headers=headers, timeout=timeout) as resp:
            if resp.status != 200:
                logger.warning(f"Jina error: {url} returned HTTP {resp.status}")
                return None
            
            content = await resp.text()
            
            if is_blocked_content(content):
                logger.warning(f"Jina: Content blocked or low quality for {url}")
                return None
            
            final_content = truncate_content(content, JINA_MAX_CHARS)
            logger.info(f"Jina Reader: {url} → {len(final_content)} chars extracted (raw: {len(content)})")
            return final_content
            
    except asyncio.TimeoutError:
        logger.warning(f"Jina: Timeout for {url} after {JINA_TIMEOUT_SEC}s")
        return None
    except aiohttp.ClientError as e:
        logger.warning(f"Jina: Network error for {url}: {e}")
        return None
    except Exception as e:
        logger.error(f"Jina: Unexpected error fetching {url}: {e}")
        return None

async def fetch_all(urls: List[str]) -> Dict[str, Optional[str]]:
    """Fetches multiple URLs in parallel with concurrency limit."""
    if not urls:
        return {}
    
    logger.info(f"Jina: Fetching {len(urls)} URLs in parallel...")
    sem = asyncio.Semaphore(JINA_CONCURRENCY)
    
    # Keep session for all requests
    async with aiohttp.ClientSession() as session:
        async def fetch_with_sem(url: str):
            async with sem:
                content = await fetch_url(session, url)
                return url, content
        
        tasks = [fetch_with_sem(url) for url in urls]
        # Using return_exceptions=True to ensure gather doesn't crash on individual errors
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        final_results = {}
        for res in results:
            if isinstance(res, Exception):
                logger.error(f"Jina: Task failed with exception: {res}")
                continue
            if isinstance(res, tuple) and len(res) == 2:
                final_results[res[0]] = res[1]
                
        return final_results
