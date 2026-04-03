import os
import time
import asyncio
import logging
import aiohttp
import urllib.parse
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)

@dataclass
class SearchSnippet:
    title: str
    url: str
    snippet: str

async def _search_jina(query: str) -> List[SearchSnippet]:
    """Search using Jina AI provider."""
    start_time = time.monotonic()
    
    logger.info(f"Searching Jina for: {query}")
    
    encoded_query = urllib.parse.quote(query, safe="")
    url = f"https://s.jina.ai/{encoded_query}"
    
    jina_api_key = os.environ.get("JINA_API_KEY", "")
    jina_search_engine = os.environ.get("JINA_SEARCH_ENGINE", "google")
    
    headers = {
        "Accept": "application/json",
        "X-Retain-Images": "none",
        "X-Retain-Links": "none",
        "X-Engine": jina_search_engine
    }
    if jina_api_key:
        headers["Authorization"] = f"Bearer {jina_api_key}"
        
    params = {}
    params["num"] = int(os.environ.get("JINA_SEARCH_NUM_RESULTS", "5"))
    
    locale = os.environ.get("JINA_SEARCH_LOCALE", "")
    if locale:
        params["hl"] = locale
        
    country = os.environ.get("JINA_SEARCH_COUNTRY", "")
    if country:
        params["gl"] = country
        
    nfpr = os.environ.get("JINA_SEARCH_NO_FIX_PHRASE", "true").lower() == "true"
    if nfpr:
        params["nfpr"] = "true"
        
    snippets = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, params=params) as response:
                if response.status != 200:
                    logger.warning(f"Jina API returned status {response.status} for query '{query}'")
                    return snippets
                    
                data = await response.json()
                items = data.get("data", [])
                
                for item in items:
                    title = item.get("title", "")
                    item_url = item.get("url", "")
                    description = item.get("description", "")
                    
                    if item_url and title:
                        snippets.append(SearchSnippet(
                            title=title,
                            url=item_url,
                            snippet=description
                        ))
    except Exception as e:
        logger.error(f"Error calling Jina API for query '{query}': {e}", exc_info=True)
        
    duration = time.monotonic() - start_time
    logger.info(f"Jina search for '{query}' took {duration:.2f}s")
    return snippets

async def _search_tavily(query: str) -> List[SearchSnippet]:
    """Stub for Tavily provider."""
    return []

async def _search_searxng(query: str) -> List[SearchSnippet]:
    """Stub for SearXNG provider."""
    return []

async def execute_search(query: str) -> List[SearchSnippet]:
    """Route search to the selected provider. Defalut is Jina."""
    provider = os.environ.get("SEARCH_PROVIDER", "jina").lower()
    logger.info(f"Routing query '{query}' to provider: {provider}")
    
    if provider == "tavily":
        return await _search_tavily(query)
    elif provider == "searxng":
        return await _search_searxng(query)
    else:
        # Default or unknown provider falls back to jina
        return await _search_jina(query)

async def execute_all(queries: List[str]) -> List[SearchSnippet]:
    """Execute search for multiple queries concurrently, flatten and deduplicate."""
    if not queries:
        return []
    
    logger.info(f"Executing parallel search for {len(queries)} queries...")
    tasks = [execute_search(query) for query in queries]
    results_list = await asyncio.gather(*tasks, return_exceptions=True)
    
    flat_results = []
    for res in results_list:
        if isinstance(res, Exception):
            logger.error(f"Search task raised an exception: {res}")
        elif isinstance(res, list):
            flat_results.extend(res)
            
    # Deduplicate by URL
    unique_snippets = []
    seen_urls = set()
    
    exclude_domains_str = os.environ.get("JINA_SEARCH_EXCLUDE_DOMAINS", "twitter.com,x.com,facebook.com,instagram.com,t.me,vk.com")
    exclude_domains = [d.strip().lower() for d in exclude_domains_str.split(",") if d.strip()]
    exclude_exts = [".pdf", ".doc", ".docx", ".xls", ".ppt"]
    
    for snippet in flat_results:
        url_norm = snippet.url.strip().lower()
        
        # Check extensions
        if any(url_norm.endswith(ext) for ext in exclude_exts):
            logger.debug(f"Jina Search: excluded {snippet.url} (document extension)")
            continue
            
        # Check domains
        if any(domain in url_norm for domain in exclude_domains):
            logger.debug(f"Jina Search: excluded {snippet.url} (domain filter)")
            continue

        if url_norm not in seen_urls:
            seen_urls.add(url_norm)
            unique_snippets.append(snippet)
            
    return unique_snippets
