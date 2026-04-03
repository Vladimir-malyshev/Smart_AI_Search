import os
import sys
from dotenv import load_dotenv
load_dotenv()
from pathlib import Path
# Добавляем корень проекта в sys.path, чтобы можно было запускать файл напрямую из IDE
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import logging
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pydantic import BaseModel

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
GLOBAL_TIMEOUT_SEC = float(os.environ.get("GLOBAL_TIMEOUT_SEC", "200.0"))

class ResearchRequest(BaseModel):
    query: str
    goal: str

class ResearchResponse(BaseModel):
    status: str
    answer: str
    iterations_used: int
    sources: List[str]
    elapsed_sec: float

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Harvester loop disabled as per task_011
    yield

app = FastAPI(title="Smart AI Search API", lifespan=lifespan)


async def run_research_pipeline(query: str, goal: str) -> dict:
    """Core RAG loop executing the sub-agents."""
    
    # Critical: Strict Isolation
    accumulated_context: dict[str, str] = {}
    current_queries: Optional[List[str]] = None
    all_executed_queries: List[str] = []
    
    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info(f"Research Pipeline Iteration {iteration}/{MAX_ITERATIONS} for query: {query[:30]}")
        
        # 1. Initial Queries (Task 011: No expansion on Iteration 1)
        if current_queries is None:
            current_queries = [query]
            logger.info(f"Iteration 1: Using exact user query: {current_queries}")
            
        all_executed_queries.extend(current_queries)
            
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
            max_iterations=MAX_ITERATIONS,
            executed_queries=all_executed_queries
        )
        judge_result = await judge(judge_input)
        
        if judge_result.status == "complete":
            useful_urls = judge_result.useful_urls
            if not useful_urls:
                logger.warning("Judge returned 'complete' but empty 'useful_urls'. Fallback to all sources.")
                useful_urls = list(accumulated_context.keys())
                
            parts = []
            for url in useful_urls:
                content = accumulated_context.get(url)
                if content:
                    parts.append(f"### Источник: {url}\n{content}")
                    
            if not parts:
                final_answer = "Собранные источники не содержат релевантного контента."
            else:
                final_answer = "\n\n".join(parts)
                
            logger.info(f"Pipeline Completed (Status: complete, Iterations: {iteration}, Useful URLs: {len(useful_urls)})")
            
            return {
                "status": "complete",
                "answer": final_answer,
                "iterations_used": iteration,
                "sources": useful_urls
            }
            
        # Prepare for next iteration
        current_queries = judge_result.new_queries
        logger.info(f"Iteration {iteration} incomplete. New queries: {current_queries}")
        
    logger.warning("Pipeline hit fallback return outside iteration loop.")
    
    parts = []
    for url, content in accumulated_context.items():
        if content:
            parts.append(f"### Источник: {url}\n{content}")
            
    final_answer = "\n\n".join(parts) if parts else "Исчерпан лимит итераций пайплайна. Информации нет."
    
    return {
        "status": "complete",
        "answer": final_answer,
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
    except Exception as e:
        logger.error(f"Global Pipeline Error for query: {request.query}: {e}", exc_info=True)
        elapsed = loop.time() - start_time
        return ResearchResponse(
            status="error",
            answer=f"Произошла внутренняя ошибка при обработке запроса: {str(e)}",
            iterations_used=-1,
            sources=[],
            elapsed_sec=elapsed
        )

if __name__ == "__main__":
    import uvicorn
    # Запуск сервера локально на порту 8000
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
