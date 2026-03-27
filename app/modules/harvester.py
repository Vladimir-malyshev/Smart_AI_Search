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

async def fetch_instances() -> Optional[Dict[str, Any]]:
    """Fetch instances list from searx.space."""
    try:
        async with aiohttp.ClientSession() as session:
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
            # Step 2 logic with strict paths:
            network_type = info["network_type"]
            uptime = info["monitoring"]["stats"]["uptime"]
            grade = info["monitoring"]["http"]["grade"]
            
            if (network_type == "normal" and 
                uptime >= 90 and 
                grade in allowed_grades):
                filtered_urls.append(url)
        except (KeyError, TypeError):
            # Если какого-то ключа нет — просто пропускаем ноду
            continue
        except Exception as e:
            logger.warning(f"Unexpected error filtering node {url}: {e}")
            continue
            
    return filtered_urls

async def health_check_node(session: aiohttp.ClientSession, url: str, semaphore: asyncio.Semaphore) -> Optional[str]:
    """Test a single node for availability and valid JSON response."""
    async with semaphore:
        test_url = f"{url.rstrip('/')}/?q=test&format=json"
        timeout = aiohttp.ClientTimeout(total=HEALTH_CHECK_TIMEOUT_SEC)
        try:
            async with session.get(test_url, timeout=timeout) as response:
                if response.status == 200:
                    # Verify it's valid JSON
                    await response.json()
                    return url
        except Exception:
            # Silence health-check failures as they are expected
            pass
    return None

async def health_check_all(urls: List[str]) -> List[str]:
    """Perform parallel health-checks with concurrency limit."""
    semaphore = asyncio.Semaphore(HEALTH_CHECK_CONCURRENCY)
    async with aiohttp.ClientSession() as session:
        tasks = [health_check_node(session, url, semaphore) for url in urls]
        results = await asyncio.gather(*tasks)
        return [url for url in results if url is not None]

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
