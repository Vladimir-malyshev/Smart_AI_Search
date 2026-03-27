import os
import asyncio
import logging
from dataclasses import dataclass
from typing import List, Tuple
import aiohttp

from app.modules.redis_manager import get_top_nodes, quarantine, add_score, reduce_score

logger = logging.getLogger(__name__)

SEARCH_TIMEOUT_FAST_SEC = float(os.environ.get("SEARCH_TIMEOUT_FAST_SEC", 1.0))
SEARCH_TIMEOUT_SLOW_SEC = float(os.environ.get("SEARCH_TIMEOUT_SLOW_SEC", 2.0))
SEARCH_TIMEOUT_HARD_SEC = float(os.environ.get("SEARCH_TIMEOUT_HARD_SEC", 5.0))
SEARCH_FALLBACK_MAX_ATTEMPTS = int(os.environ.get("SEARCH_FALLBACK_MAX_ATTEMPTS", 2))

@dataclass
class SearchSnippet:
    url: str
    title: str
    snippet: str
    source_node: str

async def assign_nodes(queries: list[str]) -> list[tuple[str, str]]:
    top_nodes = await get_top_nodes(limit=len(queries) * 2)
    if not top_nodes:
        raise RuntimeError("Пул нод пуст: Redis недоступен или все ноды в карантине")
        
    assignments = []
    for i, query in enumerate(queries):
        node = top_nodes[i % len(top_nodes)]  # round-robin если нод меньше запросов
        assignments.append((query, node))
    return assignments

async def update_reputation(node_url: str, elapsed_sec: float):
    if elapsed_sec < SEARCH_TIMEOUT_FAST_SEC:
        await add_score(node_url, 2.0)       # быстро — бонус
    elif elapsed_sec > SEARCH_TIMEOUT_SLOW_SEC:
        await reduce_score(node_url, 5.0)    # медленно — штраф
    # в диапазоне [1.0, 2.0] сек — репутация не меняется

def parse_snippets(data: dict, source_node: str) -> list[SearchSnippet]:
    snippets = []
    for item in data.get("results", []):
        try:
            url = item.get("url")
            title = item.get("title")
            content = item.get("content", "")
            if not url or not title:
                continue
            snippets.append(SearchSnippet(
                url=url, 
                title=title, 
                snippet=content, 
                source_node=source_node
            ))
        except Exception as e:
            logger.debug(f"Snippet parsing error: {e}")
            continue
    return snippets

async def execute_search(query: str, node_url: str, attempt: int = 1) -> list[SearchSnippet]:
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    
    try:
        async with aiohttp.ClientSession() as session:
            timeout = aiohttp.ClientTimeout(total=SEARCH_TIMEOUT_HARD_SEC)
            async with session.get(
                node_url,
                params={"q": query, "format": "json"},
                timeout=timeout
            ) as resp:
                if resp.status != 200:
                    raise aiohttp.ClientResponseError(
                        resp.request_info,
                        resp.history,
                        status=resp.status,
                        message=f"HTTP Error {resp.status}"
                    )
                
                data = await resp.json()
                elapsed = loop.time() - start_time
                
                # Обратная связь по скорости
                await update_reputation(node_url, elapsed)
                
                return parse_snippets(data, source_node=node_url)
                
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        logger.warning(f"Node {node_url} failed query '{query}', attempt {attempt}: {e.__class__.__name__}")
        await quarantine(node_url)
        
        if attempt < SEARCH_FALLBACK_MAX_ATTEMPTS:
            fallback_nodes = await get_top_nodes(limit=attempt + 2)
            next_node = next((n for n in fallback_nodes if n != node_url), None)
            if next_node:
                logger.info(f"Fallback to node {next_node} for query '{query}'")
                return await execute_search(query, next_node, attempt + 1)
                
        logger.warning(f"Все попытки исчерпаны для запроса '{query}'")
        return []

def deduplicate(snippets: list[SearchSnippet]) -> list[SearchSnippet]:
    seen_urls = set()
    result = []
    for s in snippets:
        if s.url not in seen_urls:
            seen_urls.add(s.url)
            result.append(s)
    return result

async def execute_all(queries: list[str]) -> list[SearchSnippet]:
    if not queries:
        return []
    
    assignments = await assign_nodes(queries)
    
    tasks = []
    for query, node_url in assignments:
        tasks.append(execute_search(query, node_url, attempt=1))
        
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    all_snippets = []
    for res in results:
        if isinstance(res, Exception):
            logger.error(f"Unexpected error in execute_search: {res}")
        elif isinstance(res, list):
            all_snippets.extend(res)
            
    return deduplicate(all_snippets)
