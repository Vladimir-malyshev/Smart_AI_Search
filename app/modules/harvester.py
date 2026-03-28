import os
import asyncio
import aiohttp
import logging
from typing import List, Optional, Dict, Any
from app.modules import redis_manager

logger = logging.getLogger(__name__)

# Configuration
INSTANCES_JSON_URL = "https://searx.space/data/instances.json"
HARVESTER_INTERVAL_SEC = int(os.environ.get("HARVESTER_INTERVAL_SEC", 3600))
HEALTH_CHECK_TIMEOUT_SEC = float(os.environ.get("HEALTH_CHECK_TIMEOUT_SEC", 2.0))
HEALTH_CHECK_CONCURRENCY = int(os.environ.get("HEALTH_CHECK_CONCURRENCY", 20))

# Имитируем реальный браузер, чтобы ноды не блокировали нас
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json"
}

async def fetch_instances() -> Optional[Dict[str, Any]]:
    """Fetch instances list from searx.space."""
    try:
        async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
            async with session.get(INSTANCES_JSON_URL, timeout=10) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.error(f"Failed to fetch instances from {INSTANCES_JSON_URL}: {response.status}")
                    return None
    except Exception as e:
        logger.error(f"Error fetching instances from {INSTANCES_JSON_URL}: {e}")
        return None

def apply_primary_filter(data: Dict[str, Any]) -> List[str]:
    """Filter instances based on uptime, network type, and http grade."""
    instances = data.get("instances", {})
    filtered_urls = []
    
    allowed_grades = {"A+", "A", "A-", "B+", "B"}
    
    for url, info in instances.items():
        try:
            # Реальная структура instances.json:
            # info["network_type"]          -> "normal" | "tor"
            # info["uptime"]["uptimeWeek"]  -> float (процент)
            # info["http"]["grade"]         -> "A+" | "A" | ...
            network_type = info.get("network_type")
            
            uptime_data = info.get("uptime") or {}
            uptime = uptime_data.get("uptimeWeek", 0)
            
            http_data = info.get("http") or {}
            grade = http_data.get("grade", "")
            
            if (network_type == "normal"
                    and uptime >= 90
                    and grade in allowed_grades):
                filtered_urls.append(url)
        except (KeyError, TypeError):
            continue
        except Exception as e:
            logger.warning(f"Unexpected error filtering node {url}: {e}")
            continue
    
    logger.info(f"Primary filter: {len(filtered_urls)}/{len(instances)} nodes passed")
    return filtered_urls


async def health_check_node(session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore) -> Optional[str]:
    """Test a single node for availability and valid JSON response."""
    async with semaphore:
        # Небольшая пауза перед запросом, чтобы не выглядеть как DDoS
        await asyncio.sleep(0.5)
        
        # Меняем 'test' на 'weather' — так запрос выглядит как от реального человека
        test_url = f"{url.rstrip('/')}/?q=weather&format=json"
        timeout = aiohttp.ClientTimeout(total=HEALTH_CHECK_TIMEOUT_SEC)
        try:
            async with session.get(test_url, timeout=timeout) as response:
                if response.status == 200:
                    # Verify it's valid JSON
                    await response.json()
                    logger.debug(f"Health check OK: {url}")
                    return url
                else:
                    logger.debug(f"Health check failed for {url}: HTTP {response.status}")
        except asyncio.TimeoutError:
            logger.debug(f"Health check timeout for {url} (>{HEALTH_CHECK_TIMEOUT_SEC}s)")
        except Exception as e:
            logger.debug(f"Health check error for {url}: {type(e).__name__}: {e}")
    return None

async def health_check_all(urls: List[str]) -> List[str]:
    """Perform parallel health-checks with concurrency limit."""
    logger.info(f"Checking health of {len(urls)} candidates...")
    semaphore = asyncio.Semaphore(HEALTH_CHECK_CONCURRENCY)
    async with aiohttp.ClientSession(headers=DEFAULT_HEADERS) as session:
        tasks = [health_check_node(session, url, semaphore) for url in urls]
        # Запускаем проверки
        results = await asyncio.gather(*tasks)
        
        healthy = [url for url in results if url is not None]
        logger.info(f"Health check complete: Found {len(healthy)} living nodes")
        return healthy



async def sync_node(url: str):
    """Idempotent sync using redis_manager."""
    # Based on redis_manager.py, calling add_score with delta=0 
    # will add it with 100 if new (zadd nx) and keep existing if not.
    await redis_manager.add_score(url, 0.0)

async def run_harvest_cycle():
    """Execute a single harvest cycle."""
    logger.info("Starting harvest cycle...")
    data = await fetch_instances()
    if data is None:
        return
    
    filtered = apply_primary_filter(data)
    if not filtered:
        logger.warning("No nodes passed primary filtering.")
        return
        
    healthy = await health_check_all(filtered)
    
    if not healthy:
        logger.critical("CRITICAL: ни одна нода не прошла health-check. Возможен IP-бан хостинга или недоступность сети.")
        return
        
    for url in healthy:
        await sync_node(url)
        
    logger.info(f"Harvest complete: {len(healthy)} живых нод синхронизировано")

async def harvester_loop():
    """Background loop for harvester."""
    while True:
        try:
            await run_harvest_cycle()
        except Exception as e:
            logger.error(f"Harvest cycle failed: {e}")
        
        logger.debug(f"Harvester sleeping for {HARVESTER_INTERVAL_SEC} seconds.")
        await asyncio.sleep(HARVESTER_INTERVAL_SEC)
