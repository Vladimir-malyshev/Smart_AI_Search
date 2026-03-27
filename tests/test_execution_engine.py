import os
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

import pytest
import asyncio
import time
from aioresponses import aioresponses, CallbackResult
from fakeredis import aioredis as fake_aioredis
from app.modules import execution_engine, redis_manager

@pytest.fixture(autouse=True)
async def setup_env(monkeypatch):
    """Setup fakeredis and clean state"""
    fake_client = fake_aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_manager, "redis_client", fake_client)
    redis_manager._fallback_scores.clear()
    redis_manager._fallback_quarantine.clear()
    redis_manager._redis_available = True
    yield fake_client
    await fake_client.flushdb()

@pytest.mark.asyncio
async def test_parallel_execution(setup_env):
    """
    Тест 1: Параллельность
    Дано: 3 мок-ноды, каждая отвечает за 1.5 секунды
    Действие: запустить execute_all(["q1", "q2", "q3"])
    """
    nodes = ["http://node1.com", "http://node2.com", "http://node3.com"]
    for node in nodes:
        await redis_manager.add_score(node, 0.0)
    
    async def delayed_callback(url, **kwargs):
        await asyncio.sleep(1.5)
        return CallbackResult(status=200, payload={"results": [{"url": f"{url}/res", "title": "res"}]})
        
    with aioresponses() as m:
        for node in nodes:
            # Need to match exact query or use regex. Pattern matching with regex is safer for query param.
            import re
            m.get(re.compile(fr"^{node}/\?format=json&q=q[123]$"), callback=delayed_callback)
            
        start_time = time.time()
        results = await execution_engine.execute_all(["q1", "q2", "q3"])
        elapsed = time.time() - start_time
        
        assert 1.4 <= elapsed < 2.5
        assert len(results) == 3

@pytest.mark.asyncio
async def test_fallback_mechanics(setup_env):
    """
    Тест 2: Fallback-механика
    Дано: нода A = 502, нода B = 200 OK.
    """
    node_a = "http://node-a.com"
    node_b = "http://node-b.com"
    
    await redis_manager.add_score(node_a, 50.0) # -> 150
    await redis_manager.add_score(node_b, 0.0)  # -> 100
    
    with aioresponses() as m:
        m.get(f"{node_a}/?format=json&q=test", status=502)
        m.get(f"{node_b}/?format=json&q=test", status=200, payload={
            "results": [{"url": "http://ok", "title": "ok"}]
        })
        
        results = await execution_engine.execute_all(["test"])
        
        assert await redis_manager.is_quarantined(node_a) is True
        assert len(results) == 1
        assert results[0].source_node == node_b

@pytest.mark.asyncio
async def test_deduplication(setup_env):
    """
    Тест 3: Дедупликация
    Два ответа от разных нод с одинаковым URL.
    """
    node1 = "http://node1.com"
    node2 = "http://node2.com"
    
    await redis_manager.add_score(node1, 0.0)
    await redis_manager.add_score(node2, 0.0)
    
    with aioresponses() as m:
        import re
        m.get(re.compile(fr"^{node1}/\?format=json&q=query1$"), status=200, payload={
            "results": [{"url": "https://en.wikipedia.org/wiki/Test", "title": "Test1"}]
        })
        m.get(re.compile(fr"^{node2}/\?format=json&q=query2$"), status=200, payload={
            "results": [{"url": "https://en.wikipedia.org/wiki/Test", "title": "Test2"}]
        })
        
        results = await execution_engine.execute_all(["query1", "query2"])
        
        assert len(results) == 1
        assert results[0].url == "https://en.wikipedia.org/wiki/Test"
