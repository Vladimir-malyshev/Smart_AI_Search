import asyncio
import os
import aiohttp
import logging
from dataclasses import dataclass
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS
from typing import List

logger = logging.getLogger(__name__)

@dataclass
class SearchSnippet:
    title: str
    url: str
    snippet: str

async def _search_jina(query: str) -> List[SearchSnippet]:
    """Search using Jina API."""
    snippets = []
    url = f"https://s.jina.ai/{query}"
    
    jina_key = os.environ.get("JINA_API_KEY", "")
    headers = {
        "Accept": "application/json"
    }
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"Jina search returned status {response.status} for query '{query}'")
                    return snippets

                data = await response.json()
                items = data.get("data", [])
                
                for item in items:
                    title = item.get("title", "")
                    item_url = item.get("url", "")
                    description = item.get("description", "")
                    
                    # Some data may be missing, we require at least URL
                    if item_url:
                        snippets.append(SearchSnippet(
                            title=title,
                            url=item_url,
                            snippet=description
                        ))
    except Exception as e:
        logger.error(f"Error during Jina search for query '{query}': {e}", exc_info=True)
        
    return snippets

async def _search_ddg(query: str) -> List[SearchSnippet]:
    """Search using DuckDuckGo (fallback)."""
    snippets = []
    try:
        def fetch_ddg():
            with DDGS() as ddgs:
                return list(ddgs.text(query, max_results=5))
        
        results = await asyncio.to_thread(fetch_ddg)
        
        for item in results:
            url = item.get("href", "")
            if url:
                snippets.append(SearchSnippet(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("body", "")
                ))
    except Exception as e:
        logger.error(f"Error during DuckDuckGo search for query '{query}': {e}", exc_info=True)
        
    return snippets

async def _search_searxng(query: str) -> List[SearchSnippet]:
    """Search using SearXNG public nodel HTML parsing."""
    snippets = []
    url = "https://searx.be/search"
    params = {"q": query}
    headers = {
         # Use a realistic User-Agent for HTML scraping
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status != 200:
                    logger.warning(f"SearXNG search returned status {response.status} for query '{query}'")
                    return snippets
                
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")
                articles = soup.find_all("article", class_="result")
                
                for article in articles:
                    a_tag = article.find("a")
                    p_tag = article.find("p", class_="content")
                    
                    if a_tag and a_tag.get("href"):
                        title = a_tag.get_text(strip=True)
                        item_url = a_tag.get("href")
                        snippet_text = p_tag.get_text(strip=True) if p_tag else ""
                        
                        snippets.append(SearchSnippet(
                            title=title,
                            url=item_url,
                            snippet=snippet_text
                        ))
    except Exception as e:
        logger.error(f"Error during SearXNG search for query '{query}': {e}", exc_info=True)
        
    return snippets

async def execute_search(query: str) -> List[SearchSnippet]:
    """Route search based on SEARCH_PROVIDER env var."""
    provider = os.environ.get("SEARCH_PROVIDER", "jina").lower()
    
    if provider == "ddg":
        return await _search_ddg(query)
    elif provider == "searxng":
        return await _search_searxng(query)
    else:
        # Default fallback is jina
        return await _search_jina(query)

async def execute_all(queries: List[str]) -> List[SearchSnippet]:
    """Execute search for multiple queries concurrently and deduplicate by URL."""
    tasks = [execute_search(query) for query in queries]
    results_list = await asyncio.gather(*tasks)
    
    # Flatten the list
    flat_results = [item for sublist in results_list for item in sublist]
    
    # Deduplicate by url, keeping the first occurrence
    unique_snippets = []
    seen_urls = set()
    
    for snippet in flat_results:
        # Normalize url: simple trim and lowercase to catch basic duplicates
        url_norm = snippet.url.strip().lower()
        if url_norm not in seen_urls:
            seen_urls.add(url_norm)
            unique_snippets.append(snippet)
            
    return unique_snippets
