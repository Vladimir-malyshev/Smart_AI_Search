import pytest
import os
import asyncio
from unittest.mock import patch, MagicMock
from app.modules.search_router import (
    SearchSnippet,
    execute_search,
    execute_all,
    _search_jina,
    _search_ddg,
    _search_searxng
)

@pytest.fixture
def mock_snippets():
    return [
        SearchSnippet(title="Test 1", url="http://test.com/1", snippet="Snippet 1"),
        SearchSnippet(title="Test 2", url="http://test.com/2", snippet="Snippet 2")
    ]

@pytest.mark.asyncio
async def test_execute_search_routing_jina(mock_snippets):
    with patch("app.modules.search_router._search_jina") as mock_jina:
        mock_jina.return_value = mock_snippets
        os.environ["SEARCH_PROVIDER"] = "jina"
        
        results = await execute_search("test query")
        
        mock_jina.assert_called_once_with("test query")
        assert results == mock_snippets

@pytest.mark.asyncio
async def test_execute_search_routing_ddg(mock_snippets):
    with patch("app.modules.search_router._search_ddg") as mock_ddg:
        mock_ddg.return_value = mock_snippets
        os.environ["SEARCH_PROVIDER"] = "ddg"
        
        results = await execute_search("test query")
        
        mock_ddg.assert_called_once_with("test query")
        assert results == mock_snippets

@pytest.mark.asyncio
async def test_execute_search_routing_searxng(mock_snippets):
    with patch("app.modules.search_router._search_searxng") as mock_searxng:
        mock_searxng.return_value = mock_snippets
        os.environ["SEARCH_PROVIDER"] = "searxng"
        
        results = await execute_search("test query")
        
        mock_searxng.assert_called_once_with("test query")
        assert results == mock_snippets

@pytest.mark.asyncio
async def test_execute_all_deduplication():
    # Return overlapping results to test dedup
    async def mock_execute(query):
        if query == "q1":
            return [
                SearchSnippet(title="A", url="http://test.com/a", snippet="1"),
                SearchSnippet(title="B", url="http://test.com/b", snippet="2")
            ]
        elif query == "q2":
             return [
                SearchSnippet(title="B Duplicate", url="http://test.com/B ", snippet="2 duplicate"), # Different case, added space
                SearchSnippet(title="C", url="http://test.com/c", snippet="3")
            ]
        return []

    with patch("app.modules.search_router.execute_search", side_effect=mock_execute):
        results = await execute_all(["q1", "q2"])
        
        assert len(results) == 3
        urls = [s.url.strip().lower() for s in results]
        assert "http://test.com/a" in urls
        assert "http://test.com/b" in urls
        assert "http://test.com/c" in urls
