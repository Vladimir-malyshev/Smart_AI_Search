import os
from dotenv import load_dotenv
load_dotenv()

import pytest
import asyncio
from unittest.mock import patch, MagicMock

from app.modules.execution_engine import (
    execute_search,
    execute_all,
    SearchSnippet
)

def get_provider():
    return os.environ.get("SEARCH_PROVIDER", "jina").lower()

@pytest.mark.asyncio
async def test_live_search_provider():
    """
    Тест реального поиска через выбранного по умолчанию провайдера.
    """
    provider = get_provider()
    if provider in ("searxng", "tavily"):
        pytest.skip(f"Provider {provider} live test not implemented yet.")
        
    query = "Тестовый запрос AI"
    results = await execute_search(query)
    
    assert isinstance(results, list), "Should return a list"
    assert len(results) > 0, f"Provider {provider} returned empty list for '{query}'"
    
    for snippet in results:
        assert isinstance(snippet, SearchSnippet), "Items must be SearchSnippet objects"
        assert snippet.title, "Title must not be empty"
        assert snippet.url, "URL must not be empty"
        assert snippet.snippet is not None, "Snippet must not be None"
        
@pytest.mark.asyncio
async def test_execute_all_deduplication():
    """
    Тест оркестратора на дедупликацию и склейку.
    """
    # Имитируем ответы от провайдера для предсказуемости
    async def mock_execute(query: str):
        if query == "query1":
            return [
                SearchSnippet(title="Doc 1", url="https://example.com/1", snippet="text 1"),
                SearchSnippet(title="Doc 2", url="https://example.com/2", snippet="text 2")
            ]
        elif query == "query2":
            return [
                SearchSnippet(title="Doc 2 Duplicate", url="https://example.com/2 ", snippet="text 2 duplicated"), # Пробел в URL
                SearchSnippet(title="Doc 3", url="https://example.com/3", snippet="text 3")
            ]
        return []

    with patch("app.modules.execution_engine.execute_search", side_effect=mock_execute):
        results = await execute_all(["query1", "query2"])
        
        urls = set(s.url.strip().lower() for s in results)
        assert len(results) == 3, "Should have exactly 3 unique results"
        assert "https://example.com/1" in urls
        assert "https://example.com/2" in urls
        assert "https://example.com/3" in urls


@pytest.mark.asyncio
@pytest.mark.skipif(
    get_provider() != "searxng",
    reason="Legacy Redis logic only tested when SEARCH_PROVIDER == 'searxng'"
)
async def test_searxng_redis_logic():
    """
    Условный тест Redis. Выполняется только для searxng.
    Проверяет, что движок обращается к Redis за нодой.
    """
    # Этот тест проверяет логику легаси-провайдера SearXNG, которая пока не реализована в новом роутере.
    # Ожидается, что при вызове _search_searxng будет использован get_top_nodes.
    
    with patch("app.modules.redis_manager.get_top_nodes", new_callable=pytest.AsyncMock) as mock_get_nodes:
        mock_get_nodes.return_value = ["http://mock-node1.com"]
        
        # Мокаем aiohttp сессию, чтобы не ходить в сеть
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_response = MagicMock()
            mock_response.status = 200
            # Mocking async context manager for response
            mock_response.__aenter__.return_value = mock_response
            mock_response.json = pytest.AsyncMock(return_value={"results": []})
            mock_response.text = pytest.AsyncMock(return_value="")
            mock_get.return_value = mock_response
            
            await execute_search("Test SearXNG query")
            
            # Проверки: что мы брали ноды из Redis
            mock_get_nodes.assert_called_once()
