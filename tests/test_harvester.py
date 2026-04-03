import os
os.environ["REDIS_URL"] = "redis://localhost:6379/15"

import pytest
import asyncio
import json
from aioresponses import aioresponses
from fakeredis import aioredis as fake_aioredis
from app.modules import harvester, redis_manager

@pytest.fixture(autouse=True)
async def mock_redis(monkeypatch):
    """Replace real redis client with fakeredis one."""
    fake_client = fake_aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(redis_manager, "_redis_client", fake_client)
    
    # Reset in-memory fallback state if any
    redis_manager._fallback_scores.clear()
    redis_manager._fallback_quarantine.clear()
    redis_manager._redis_available = True
    
    yield fake_client
    await fake_client.flushdb()

@pytest.fixture
def mock_instances_data():
    return {
        "instances": {
            "http://node-a.tor": {
                "network_type": "tor",
                "uptime": {"uptimeWeek": 99},
                "http": {"grade": "A"}
            },
            "http://node-b.poor": {
                "network_type": "normal",
                "uptime": {"uptimeWeek": 85},
                "http": {"grade": "C"}
            },
            "http://node-c.good": {
                "network_type": "normal",
                "uptime": {"uptimeWeek": 99},
                "http": {"grade": "A"}
            },
            "http://node-d.slow": {
                "network_type": "normal",
                "uptime": {"uptimeWeek": 95},
                "http": {"grade": "B+"}
            },
            "http://node-e.existing": {
                "network_type": "normal",
                "uptime": {"uptimeWeek": 98},
                "http": {"grade": "A+"}
            },
            "http://node-f.missing-keys": {
                "network_type": "normal"
                # missing uptime and http
            }
        }
    }

@pytest.mark.asyncio
async def test_harvester_filtering_and_sync(mock_redis, mock_instances_data):
    """
    Тест 1: Фильтрация мок-данных.
    Ожидается, что пройдут только C, D и E по фильтру.
    Затем health-check пройдет только C (D - медленный, E - не тестируем здесь).
    """
    with aioresponses() as m:
        # Mock instances fetch
        m.get(harvester.INSTANCES_JSON_URL, status=200, payload=mock_instances_data)
        
        # Mock health-checks
        # health-check query is now q=weather
        m.get("http://node-c.good/?q=weather&format=json", status=200, payload={"results": []})
        # node-a and node-b are filtered out before healthcheck, so no need to mock them for success
        
        # Run cycle
        await harvester.run_harvest_cycle()
        
        # Check ZSET: only node-c should be there with 100
        # (node-d and node-e were not mocked for healthcheck yet, they would fail by default or timeout)
        score = await mock_redis.zscore(redis_manager.ZSET_KEY, "http://node-c.good")
        assert score == 100.0
        
        # Ensure node-a, node-b were not added
        assert await mock_redis.zscore(redis_manager.ZSET_KEY, "http://node-a.tor") is None
        assert await mock_redis.zscore(redis_manager.ZSET_KEY, "http://node-b.poor") is None

@pytest.mark.asyncio
async def test_harvester_timeout(mock_redis, mock_instances_data):
    """
    Тест 2: Таймаут Health-check.
    Нода D отвечает слишком долго.
    """
    with aioresponses() as m:
        m.get(harvester.INSTANCES_JSON_URL, status=200, payload=mock_instances_data)
        
        # node-d will timeout (simulated by exception or delay?)
        # aioresponses handles timeout as an error if we raise it
        # health-check query is now q=weather
        m.get("http://node-d.slow/?q=weather&format=json", exception=asyncio.TimeoutError())
        m.get("http://node-c.good/?q=weather&format=json", status=200, payload={})
        
        await harvester.run_harvest_cycle()
        
        # Check results
        assert await mock_redis.zscore(redis_manager.ZSET_KEY, "http://node-c.good") == 100.0
        assert await mock_redis.zscore(redis_manager.ZSET_KEY, "http://node-d.slow") is None

@pytest.mark.asyncio
async def test_harvester_idempotency(mock_redis, mock_instances_data):
    """
    Тест 3: Идемпотентность.
    Нода E уже в Redis со score 150.
    После прохождения harvester score должен остаться 150.
    """
    node_e_url = "http://node-e.existing"
    # Pre-fill redis
    await mock_redis.zadd(redis_manager.ZSET_KEY, {node_e_url: 150.0})
    
    with aioresponses() as m:
        m.get(harvester.INSTANCES_JSON_URL, status=200, payload=mock_instances_data)
        
        # Health-check success for E (using q=weather)
        m.get(f"{node_e_url.rstrip('/')}/?q=weather&format=json", status=200, payload={})
        
        # Run twice
        await harvester.run_harvest_cycle()
        await harvester.run_harvest_cycle()
        
        # Score remains 150
        score = await mock_redis.zscore(redis_manager.ZSET_KEY, node_e_url)
        assert score == 150.0
        
        # Only one entry for node E
        count = await mock_redis.zcard(redis_manager.ZSET_KEY)
        # Assuming only E passed healthcheck (since others didn't have mocks)
        assert count == 1
