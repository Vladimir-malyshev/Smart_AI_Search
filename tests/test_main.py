import os
os.environ["REDIS_URL"] = "redis://localhost:6379"

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
    with patch("app.main.expand_query", new_callable=AsyncMock) as mock_expand, \
         patch("app.main.execute_all", new_callable=AsyncMock) as mock_execute, \
         patch("app.main.evaluate_snippets", new_callable=AsyncMock) as mock_eval, \
         patch("app.main.fetch_all", new_callable=AsyncMock) as mock_fetch, \
         patch("app.main.judge", new_callable=AsyncMock) as mock_judge, \
         patch("app.main.run_harvest_cycle", new_callable=AsyncMock) as mock_run_harvest_cycle, \
         patch("app.modules.harvester.harvester_loop", new_callable=AsyncMock) as mock_harvester_loop:

        # Default fast behaviors
        mock_run_harvest_cycle.return_value = None
        mock_expand.return_value = ["q1"]
        mock_execute.return_value = [SearchSnippet(url="http://mock.com", title="x", snippet="x", source_node="n")]
        mock_eval.return_value = ["http://mock.com"]
        mock_fetch.return_value = {"http://mock.com": "content"}
        mock_judge.return_value = JudgeOutput(status="complete", final_answer="Mocked Answer", missing_info=None)
        
        yield {
            "expand": mock_expand,
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
        assert data["answer"] == "Mocked Answer"
        assert "http://mock.com" in data["sources"]
        assert data["elapsed_sec"] >= 0.0

@pytest.mark.asyncio
async def test_global_timeout_graceful_return(mock_pipeline_modules):
    """Test that if the pipeline takes longer than GLOBAL_TIMEOUT_SEC, it returns 'timeout' gracefully."""
    async def slow_expand(*args, **kwargs):
        await asyncio.sleep(2.0)
        return ["q1"]
        
    mock_pipeline_modules["expand"].side_effect = slow_expand
    
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
        JudgeOutput(status="incomplete", final_answer=None, missing_info="more info", new_queries=["q2"]),
        JudgeOutput(status="complete", final_answer="Deep Answer", missing_info=None, new_queries=[])
    ]
    
    with TestClient(app) as test_client:
        response = test_client.post("/api/v1/research", json={"query": "q", "goal": "g"})
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "complete"
        assert data["iterations_used"] == 2
        assert data["answer"] == "Deep Answer"

@pytest.mark.asyncio
async def test_concurrent_isolation(mock_pipeline_modules):
    """Test that multiple requests don't leak context across each other."""
    
    async def mock_judge(inp):
        return JudgeOutput(status="complete", final_answer=f"Ans for {inp.original_query}", missing_info=None)
        
    mock_pipeline_modules["judge"].side_effect = mock_judge

    async def make_request(query):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/api/v1/research", json={"query": query, "goal": "g"})
            return resp.json()["answer"]

    queries = [f"query_{i}" for i in range(5)]
    tasks = [make_request(q) for q in queries]
    
    # We must use proper asyncio event loop context since lifespan is ASGI context based
    # However since we mocked out the lifespan harvester loop anyway, directly calling app endpoint is safe.
    results = await asyncio.gather(*tasks)
    
    for q in queries:
        assert f"Ans for {q}" in results
