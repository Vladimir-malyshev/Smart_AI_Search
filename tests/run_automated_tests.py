import asyncio
import os
import argparse
import aiohttp
import json
import logging
from pathlib import Path
import time
from typing import TypedDict, List, Dict, Any

# Настроим детальное логирование самого тест-раннера
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [TEST_RUNNER] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/test_run.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

class TestCase(TypedDict):
    level: str
    query: str
    goal: str

def load_test_cases(file_path: Path) -> List[TestCase]:
    if not file_path.exists():
        logger.error(f"Test cases file not found at: {file_path}")
        return []
    with file_path.open('r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse test cases JSON: {e}")
            return []

async def send_research_request(session: aiohttp.ClientSession, endpoint: str, test_case: TestCase) -> Dict[str, Any]:
    payload = {
        "query": test_case["query"],
        "goal": test_case["goal"]
    }
    
    start_time = time.monotonic()
    try:
        # Уставляем таймаут для клиента чуть больше, чем GLOBAL_TIMEOUT_SEC на сервере (например 60 сек)
        # На сервере по умолчанию 45.0
        async with session.post(endpoint, json=payload, timeout=60.0) as response:
            if response.status != 200:
                text = await response.text()
                logger.error(f"Server returned non-200 status: {response.status}. Body: {text}")
                return {
                    "status": "error",
                    "iterations_used": 0,
                    "elapsed_sec": time.monotonic() - start_time,
                    "error": f"HTTP {response.status}: {text}"
                }
                
            data = await response.json()
            # Убедимся, что мы корректно обрабатываем ответ API
            # data = ResearchResponse dict
            # status: str, answer: str, iterations_used: int, sources: List[str], elapsed_sec: float
            return {
                "status": data.get("status", "unknown"),
                "iterations_used": data.get("iterations_used", 0),
                "elapsed_sec": data.get("elapsed_sec", time.monotonic() - start_time),
                "answer_length": len(data.get("answer", "")),
                "sources_count": len(data.get("sources", []))
            }
            
    except asyncio.TimeoutError:
        logger.error("Request to API timed out.")
        return {
            "status": "timeout",
            "iterations_used": 0,
            "elapsed_sec": time.monotonic() - start_time,
            "error": "Client timeout"
        }
    except Exception as e:
        logger.error(f"Unexpected error during request: {e}")
        return {
            "status": "error",
            "iterations_used": 0,
            "elapsed_sec": time.monotonic() - start_time,
            "error": str(e)
        }

async def run_all_tests(endpoint: str, cases: List[TestCase]):
    total = len(cases)
    success_count = 0
    total_time = 0.0
    total_iterations = 0
    
    logger.info(f"Starting E2E test suite. Loaded {total} test cases.")
    logger.info(f"API Endpoint: {endpoint}")
    logger.info("=" * 60)
    
    async with aiohttp.ClientSession() as session:
        for idx, case in enumerate(cases, 1):
            logger.info(f"--- Test {idx}/{total} [{case['level'].upper()}] ---")
            logger.info(f"Query: {case['query']}")
            logger.info(f"Goal:  {case['goal']}")
            
            result = await send_research_request(session, endpoint, case)
            
            status = result.get("status")
            elapsed = result.get("elapsed_sec", 0.0)
            iters = result.get("iterations_used", 0)
            
            logger.info(f"Result Status: {status}")
            logger.info(f"Iterations:    {iters}")
            logger.info(f"Time Taken:    {elapsed:.2f}s")
            logger.info(f"Answer Size:   {result.get('answer_length', 0)} chars")
            logger.info(f"Sources Used:  {result.get('sources_count', 0)}")
            
            if status == "complete":
                success_count += 1
                total_time += elapsed
                total_iterations += iters
            else:
                logger.warning(f"Test failed with status: {status}")
                if "error" in result:
                    logger.error(f"Error details: {result['error']}")
            
            logger.info("-" * 60)
            
            # Критическое правило: обязательная пауза после каждого запроса (для избежания бана)
            if idx < total:
                logger.info("Waiting 5 seconds before next request (Anti-ban)...")
                await asyncio.sleep(5)
                
    # Выводим финальную статистику
    logger.info("=" * 60)
    logger.info("TEST SUITE SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Total Tests:  {total}")
    logger.info(f"Successful:   {success_count}")
    logger.info(f"Failed:       {total - success_count}")
    
    if success_count > 0:
        avg_time = total_time / success_count
        avg_iters = total_iterations / success_count
        logger.info(f"Avg Time (successful):      {avg_time:.2f}s")
        logger.info(f"Avg Iterations (effective): {avg_iters:.1f}")
    else:
        logger.info("No tests completed successfully to calculate averages.")

def main():
    parser = argparse.ArgumentParser(description="Deep Research API Test Runner")
    parser.add_argument("--url", default="http://127.0.0.1:8000/api/v1/research", help="API Endpoint URL")
    parser.add_argument("--cases", default="tests/test_cases.json", help="Path to test cases JSON file")
    
    args = parser.parse_args()
    
    cases_path = Path(args.cases)
    cases = load_test_cases(cases_path)
    
    if not cases:
        logger.error("Exiting due to empty or missing test cases.")
        return
        
    try:
        asyncio.run(run_all_tests(args.url, cases))
    except KeyboardInterrupt:
        logger.info("Test execution interrupted by user.")

if __name__ == "__main__":
    main()
