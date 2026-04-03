import os

import pytest
import asyncio
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

from app.main import app, ResearchRequest
from app.modules.execution_engine import SearchSnippet
from app.modules.ai_judge import JudgeOutput

@pytest.fixture
def mock_pipeline_modules():
    """Mock all external module calls to isolate pipeline orchestration."""
    with patch("app.main.execute_all", new_callable=AsyncMock) as mock_execute, \
         patch("app.main.evaluate_snippets", new_callable=AsyncMock) as mock_eval, \
         patch("app.main.fetch_all", new_callable=AsyncMock) as mock_fetch, \
         patch("app.main.judge", new_callable=AsyncMock) as mock_judge:

        # Default fast behaviors
        mock_execute.return_value = [SearchSnippet(url="http://mock.com", title="x", snippet="x")]
        mock_eval.return_value = ["http://mock.com"]
        mock_fetch.return_value = {"http://mock.com": "Mocked Content Body."}
        mock_judge.return_value = JudgeOutput(status="complete", useful_urls=["http://mock.com"], missing_info=None)
        
        yield {
            "execute": mock_execute,
            "eval": mock_eval,
            "fetch": mock_fetch,
            "judge": mock_judge
        }

def test_successful_end_to_end(mock_pipeline_modules):
    """Test standard single-iteration finish returning HTTP 200 and complete status."""
    with TestClient(app) as test_client:
        payload = {"query": "test query", "goal": "test goal"}
        response = test_client.post("/api/v1/research", json=payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["iterations_used"] == 1
        assert "Mocked Content Body" in data["answer"]
        assert "http://mock.com" in data["sources"]
        assert data["elapsed_sec"] >= 0.0

@pytest.mark.asyncio
async def test_global_timeout_graceful_return(mock_pipeline_modules):
    """Test that if the pipeline takes longer than GLOBAL_TIMEOUT_SEC, it returns 'timeout' gracefully."""
    async def slow_execute(*args, **kwargs):
        await asyncio.sleep(2.0)
        return []
        
    mock_pipeline_modules["execute"].side_effect = slow_execute
    
    with patch("app.main.GLOBAL_TIMEOUT_SEC", 1.0):
        with TestClient(app) as test_client:
            response = test_client.post("/api/v1/research", json={"query": "q", "goal": "g"})
            
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "timeout"
            assert data["iterations_used"] == -1
            assert "Превышено время ожидания" in data["answer"]

def test_deep_research_iterations(mock_pipeline_modules):
    """Test that 'incomplete' status causes the loop to run again."""
    mock_pipeline_modules["judge"].side_effect = [
        JudgeOutput(status="incomplete", useful_urls=[], missing_info="more info", new_queries=["q2"]),
        JudgeOutput(status="complete", useful_urls=["http://mock.com"], missing_info=None, new_queries=[])
    ]
    
    with TestClient(app) as test_client:
        response = test_client.post("/api/v1/research", json={"query": "q", "goal": "g"})
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["iterations_used"] == 2
        assert "Mocked Content Body" in data["answer"]

@pytest.mark.asyncio
async def test_concurrent_isolation(mock_pipeline_modules):
    """Test that multiple requests don't leak context across each other."""

    async def mock_execute(queries, session=None):
        # Возвращаем сниппет с URL специфичным для первого запроса
        q = queries[0] if isinstance(queries, list) else queries
        return [SearchSnippet(url=f"http://mock_{q}.com", title=q, snippet=q)]

    async def mock_eval(goal, snippets):
        return [s.url for s in snippets]

    async def mock_fetch(urls):
        return {url: f"Ans for {url}" for url in urls}

    async def mock_judge(inp):
        urls = list(inp.context.keys())
        return JudgeOutput(status="complete", useful_urls=urls, missing_info=None)

    mock_pipeline_modules["execute"].side_effect = mock_execute
    mock_pipeline_modules["eval"].side_effect = mock_eval
    mock_pipeline_modules["fetch"].side_effect = mock_fetch
    mock_pipeline_modules["judge"].side_effect = mock_judge

    async def make_request(query):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/research", json={"query": query, "goal": "g"})
            return resp.json()["answer"]

    queries = [f"query_{i}" for i in range(5)]
    results = await asyncio.gather(*[make_request(q) for q in queries])

    for i, q in enumerate(queries):
        expected = f"Ans for http://mock_{q}.com"
        assert expected in results[i], \
            f"Query '{q}': expected '{expected}' in answer, got: '{results[i][:200]}'"
