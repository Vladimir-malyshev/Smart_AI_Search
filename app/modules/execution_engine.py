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

async def _search_jina(query: str, session: aiohttp.ClientSession) -> List[SearchSnippet]:
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
    params["num"] = int(os.environ.get("SEARCH_NUM_RESULTS", "5"))
    
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

async def _search_tavily(query: str, session: aiohttp.ClientSession) -> List[SearchSnippet]:
    """Search using Tavily AI provider."""
    start_time = time.monotonic()
    tavily_api_key = os.environ.get("TAVILY_API_KEY")
    num_results = int(os.environ.get("SEARCH_NUM_RESULTS", "5"))
    
    if not tavily_api_key:
        logger.error("TAVILY_API_KEY not found in environment.")
        return []
        
    snippets = []
    try:
        url = "https://api.tavily.com/search"
        payload = {
            "api_key": tavily_api_key,
            "query": query,
            "max_results": num_results,
            "search_depth": "basic",
            "include_answer": False,
            "include_images": False,
            "include_raw_content": False
        }
        
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                text = await response.text()
                logger.warning(f"Tavily API returned status {response.status} for query '{query}': {text}")
                return snippets
                
            data = await response.json()
            results = data.get("results", [])
            
            for res in results:
                snippets.append(SearchSnippet(
                    title=res.get("title", ""),
                    url=res.get("url", ""),
                    snippet=res.get("content", "")
                ))
    except Exception as e:
        logger.error(f"Error calling Tavily API for query '{query}': {e}", exc_info=True)
        
    duration = time.monotonic() - start_time
    logger.info(f"Tavily search for '{query}' took {duration:.2f}s")
    return snippets

async def _search_searxng(query: str, session: aiohttp.ClientSession) -> List[SearchSnippet]:
    """Stub for SearXNG provider."""
    return []

async def execute_search(query: str, session: aiohttp.ClientSession) -> List[SearchSnippet]:
    """Route search to the selected provider. Defalut is Tavily."""
    provider = os.environ.get("SEARCH_PROVIDER", "tavily").lower()
    logger.info(f"Routing query '{query}' to provider: {provider}")
    
    if provider == "tavily":
        return await _search_tavily(query, session)
    elif provider == "searxng":
        return await _search_searxng(query, session)
    else:
        # Default or unknown provider falls back to jina
        return await _search_jina(query, session)

async def execute_all(queries: List[str]) -> List[SearchSnippet]:
    """Execute search for multiple queries concurrently, flatten and deduplicate."""
    if not queries:
        return []
    
    logger.info(f"Executing parallel search for {len(queries)} queries...")
    async with aiohttp.ClientSession() as session:
        tasks = [execute_search(query, session) for query in queries]
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
    
    exclude_domains_str = os.environ.get("SEARCH_EXCLUDE_DOMAINS", "twitter.com,x.com,facebook.com,instagram.com,t.me,vk.com")
    exclude_domains = [d.strip().lower() for d in exclude_domains_str.split(",") if d.strip()]
    exclude_exts = [".pdf", ".doc", ".docx", ".xls", ".ppt"]
    
    for snippet in flat_results:
        url_norm = snippet.url.strip().lower()
        
        # Check extensions
        if any(url_norm.endswith(ext) for ext in exclude_exts):
            logger.debug(f"Search Engine: excluded {snippet.url} (document extension)")
            continue
            
        # Check domains
        if any(domain in url_norm for domain in exclude_domains):
            logger.debug(f"Search Engine: excluded {snippet.url} (domain filter)")
            continue

        if url_norm not in seen_urls:
            seen_urls.add(url_norm)
            unique_snippets.append(snippet)
            
    return unique_snippets
