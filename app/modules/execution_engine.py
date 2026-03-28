import os
import time
import asyncio
import logging
import aiohttp
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
    url = f"https://s.jina.ai/{query}"
    jina_api_key = os.environ.get("JINA_API_KEY", "")
    
    headers = {
        "Accept": "application/json"
    }
    if jina_api_key:
        headers["Authorization"] = f"Bearer {jina_api_key}"
        
    snippets = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
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
    
    for snippet in flat_results:
        url_norm = snippet.url.strip().lower()
        if url_norm not in seen_urls:
            seen_urls.add(url_norm)
            unique_snippets.append(snippet)
            
    return unique_snippets
