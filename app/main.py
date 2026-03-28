import os
import sys
from pathlib import Path
# Добавляем корень проекта в sys.path, чтобы можно было запускать файл напрямую из IDE
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import logging
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel

from app.modules.harvester import harvester_loop, run_harvest_cycle
from app.modules.query_expansion import expand_query
from app.modules.execution_engine import execute_all
from app.modules.snippet_evaluator import evaluate_snippets
from app.modules.jina_reader import fetch_all
from app.modules.ai_judge import judge, JudgeInput

# Настройка глобального логирования для отображения подробной "кухни" сервиса и записи в файл
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/server.log", encoding="utf-8")
    ]
)
logger = logging.getLogger(__name__)

# Config
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 3))
GLOBAL_TIMEOUT_SEC = float(os.environ.get("GLOBAL_TIMEOUT_SEC", 45.0))

class ResearchRequest(BaseModel):
    query: str
    goal: str

class ResearchResponse(BaseModel):
    status: str
    answer: str
    iterations_used: int
    sources: List[str]
    elapsed_sec: float

# Ensure the harvester fills up the node pool before serving traffic
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Launch background loop
    logger.info("Starting Harvester background loop...")
    harvester_task = asyncio.create_task(harvester_loop())
    
    yield
    
    # Shutdown
    logger.info("Shutting down Harvester...")
    harvester_task.cancel()

app = FastAPI(title="Smart AI Search API", lifespan=lifespan)


async def run_research_pipeline(query: str, goal: str) -> dict:
    """Core RAG loop executing the sub-agents."""
    
    # Critical: Strict Isolation
    accumulated_context: dict[str, str] = {}
    current_queries: Optional[List[str]] = None
    
    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info(f"Research Pipeline Iteration {iteration}/{MAX_ITERATIONS} for query: {query[:30]}")
        
        # 1. Expand Query
        if current_queries is None:
            current_queries = await expand_query(query, goal)
            logger.info(f"AI Planner initial queries: {current_queries}")
            
        # 2. Execute parallel search
        snippets = await execute_all(current_queries)
        logger.info(f"Iteration {iteration}: Execution engine returned {len(snippets)} raw snippets.")
        if not snippets:
            logger.warning(f"Execution engine returned no snippets on iteration {iteration}.")
            
        # 3. Snippet Triage 
        selected_urls = await evaluate_snippets(goal, snippets)
        logger.info(f"Iteration {iteration}: Snippet Evaluator selected {len(selected_urls)} URLs: {selected_urls}")
        if not selected_urls:
            logger.warning(f"Iteration {iteration}: Snippet Evaluator selected 0 URLs.")
        
        # 4. Extract content via Jina
        if selected_urls:
            new_content = await fetch_all(selected_urls)
            accumulated_context.update(new_content)
            
        # 5. AI Judge Evaluation
        judge_input = JudgeInput(
            original_query=query,
            goal=goal,
            context=accumulated_context,
            current_iteration=iteration,
            max_iterations=MAX_ITERATIONS
        )
        judge_result = await judge(judge_input)
        
        if judge_result.status == "complete":
            return {
                "status": "complete",
                "answer": judge_result.final_answer or "Ответ был завершен, но текст пуст.",
                "iterations_used": iteration,
                "sources": list(accumulated_context.keys())
            }
            
        # Prepare for next iteration
        current_queries = judge_result.new_queries
        logger.info(f"Iteration {iteration} incomplete. New queries: {current_queries}")
        
    return {
        "status": "complete",
        "answer": "Исчерпан лимит итераций пайплайна.",
        "iterations_used": MAX_ITERATIONS,
        "sources": list(accumulated_context.keys())
    }

@app.post("/api/v1/research", response_model=ResearchResponse)
async def research_endpoint(request: ResearchRequest):
    loop = asyncio.get_running_loop()
    start_time = loop.time()
    
    try:
        pipeline_result = await asyncio.wait_for(
            run_research_pipeline(request.query, request.goal),
            timeout=GLOBAL_TIMEOUT_SEC
        )
        
        elapsed = loop.time() - start_time
        return ResearchResponse(
            status=pipeline_result["status"],
            answer=pipeline_result["answer"],
            iterations_used=pipeline_result["iterations_used"],
            sources=pipeline_result["sources"],
            elapsed_sec=elapsed
        )
        
    except asyncio.TimeoutError:
        logger.error(f"Global Pipeline Timeout ({GLOBAL_TIMEOUT_SEC}s) for query: {request.query}")
        elapsed = loop.time() - start_time
        return ResearchResponse(
            status="timeout",
            answer="Превышено время ожидания. Анализ был прерван, так как сбор информации занял слишком много времени.",
            iterations_used=-1,
            sources=[],
            elapsed_sec=elapsed
        )

if __name__ == "__main__":
    import uvicorn
    # Запуск сервера локально на порту 8000
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
