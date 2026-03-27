import os
import time
import logging
import asyncio
from typing import List
import redis.asyncio as aioredis
from redis.exceptions import ConnectionError, TimeoutError

logger = logging.getLogger(__name__)

# Strict requirement: Load from environment variable without default
REDIS_URL = os.environ["REDIS_URL"]

# Connection Pool
pool = aioredis.ConnectionPool.from_url(
    REDIS_URL,
    max_connections=20,
    decode_responses=True
)
redis_client = aioredis.Redis(connection_pool=pool)

ZSET_KEY = "searx:nodes:score"
QUARANTINE_PREFIX = "searx:quarantine:"
QUARANTINE_TTL = 3600

# In-memory fallback states
_fallback_scores: dict[str, float] = {}
_fallback_quarantine: dict[str, float] = {}  # url -> expire_timestamp
_redis_available: bool = True
_sync_lock = asyncio.Lock()


async def _check_and_sync_fallback():
    """Check if Redis is back up and sync fallback data if needed."""
    global _redis_available
    if _redis_available:
        return

    # If it was unavailable, we try to ping it
    try:
        await redis_client.ping()
    except (ConnectionError, TimeoutError):
        return  # Still down

    # Looks like it's back, let's sync
    async with _sync_lock:
        if _redis_available:  # Double check
            return
            
        try:
            async with redis_client.pipeline() as pipe:
                if _fallback_scores:
                    pipe.zadd(ZSET_KEY, _fallback_scores)
                
                current_time = time.time()
                for url, exp_time in _fallback_quarantine.items():
                    if exp_time > current_time:
                        ttl = int(exp_time - current_time)
                        pipe.set(f"{QUARANTINE_PREFIX}{url}", "1", ex=ttl)
                
                await pipe.execute()
                
            _fallback_scores.clear()
            _fallback_quarantine.clear()
            _redis_available = True
            logger.info("Successfully synced fallback data to Redis.")
        except (ConnectionError, TimeoutError):
            logger.warning("Failed to sync fallback data to Redis.")


def _handle_redis_error(e: Exception):
    global _redis_available
    if _redis_available:
        logger.warning(f"Redis недоступен, используется fallback: {e}")
        _redis_available = False


async def add_score(url: str, delta: float) -> float:
    await _check_and_sync_fallback()
    
    if _redis_available:
        try:
            async with redis_client.pipeline() as pipe:
                # Базовый рейтинг новой ноды = 100. NX запишет 100, только если ключа еще нет.
                pipe.zadd(ZSET_KEY, {url: 100.0}, nx=True)
                pipe.zincrby(ZSET_KEY, delta, url)
                results = await pipe.execute()
            return float(results[1])
        except (ConnectionError, TimeoutError) as e:
            _handle_redis_error(e)
            
    # Fallback path
    current = _fallback_scores.get(url, 100.0)
    new_score = current + delta
    _fallback_scores[url] = new_score
    return new_score


# Lua script for reducing score atomically without read-modify-write in Python.
# Ensures that the score never drops below 0.
_REDUCE_SCORE_LUA = """
local current = redis.call('ZSCORE', KEYS[1], ARGV[1])
if current == false then
    current = 100
end
local new_score = tonumber(current) - tonumber(ARGV[2])
if new_score < 0 then
    new_score = 0
end
redis.call('ZADD', KEYS[1], new_score, ARGV[1])
return tonumber(new_score)
"""


async def reduce_score(url: str, delta: float) -> float:
    await _check_and_sync_fallback()
    
    if _redis_available:
        try:
            new_score = await redis_client.eval(_REDUCE_SCORE_LUA, 1, ZSET_KEY, url, delta)
            return float(new_score)
        except (ConnectionError, TimeoutError) as e:
            _handle_redis_error(e)
            
    # Fallback path
    current = _fallback_scores.get(url, 100.0)
    new_score = max(0.0, current - delta)
    _fallback_scores[url] = new_score
    return new_score


async def quarantine(url: str, ttl: int = QUARANTINE_TTL) -> None:
    await _check_and_sync_fallback()
    
    if _redis_available:
        try:
            async with redis_client.pipeline() as pipe:
                pipe.zrem(ZSET_KEY, url)
                pipe.set(f"{QUARANTINE_PREFIX}{url}", "1", ex=ttl)
                await pipe.execute()
            return
        except (ConnectionError, TimeoutError) as e:
            _handle_redis_error(e)
            
    # Fallback path
    _fallback_scores.pop(url, None)
    _fallback_quarantine[url] = time.time() + ttl


async def is_quarantined(url: str) -> bool:
    await _check_and_sync_fallback()
    
    if _redis_available:
        try:
            exists = await redis_client.exists(f"{QUARANTINE_PREFIX}{url}")
            return exists > 0
        except (ConnectionError, TimeoutError) as e:
            _handle_redis_error(e)
            
    # Fallback path
    exp_time = _fallback_quarantine.get(url)
    if exp_time is not None:
        if time.time() < exp_time:
            return True
        else:
            del _fallback_quarantine[url]  # Expired
    return False


async def get_top_nodes(limit: int = 10) -> List[str]:
    await _check_and_sync_fallback()
    
    if _redis_available:
        try:
            nodes = await redis_client.zrevrange(ZSET_KEY, 0, (limit * 2) - 1)
            valid_nodes = []
            for url in nodes:
                if not await is_quarantined(url):
                    valid_nodes.append(url)
                    if len(valid_nodes) == limit:
                        break
            return valid_nodes
        except (ConnectionError, TimeoutError) as e:
            _handle_redis_error(e)
            
    # Fallback path
    valid_nodes = []
    # Sort fallback scores globally descending
    sorted_nodes = sorted(_fallback_scores.keys(), key=lambda k: _fallback_scores[k], reverse=True)
    
    for url in sorted_nodes:
        # Check if quarantined in fallback
        exp_time = _fallback_quarantine.get(url)
        is_q = False
        if exp_time is not None:
            if time.time() < exp_time:
                is_q = True
            else:
                del _fallback_quarantine[url]
                
        if not is_q:
            valid_nodes.append(url)
            if len(valid_nodes) == limit:
                break
    return valid_nodes
