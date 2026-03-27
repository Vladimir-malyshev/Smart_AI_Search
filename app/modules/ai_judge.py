import os
import json
import re
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from app.core import llm

logger = logging.getLogger(__name__)

# Model Configuration
provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
if provider == "openai":
    DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
else:
    DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemma-3-27b-it")

@dataclass
class JudgeInput:
    original_query: str
    goal: str
    context: Dict[str, Optional[str]]
    current_iteration: int
    max_iterations: int

@dataclass
class JudgeOutput:
    status: str
    final_answer: Optional[str]
    missing_info: Optional[str]
    new_queries: List[str] = field(default_factory=list)

def format_context(context: Dict[str, Optional[str]]) -> str:
    """Formats the Jina-extracted context for LLM ingestion."""
    parts = []
    for url, content in context.items():
        if content:
            parts.append(f"=== Источник: {url} ===\n{content}\n")
        else:
            parts.append(f"=== Источник: {url} ===\n[Контент недоступен]\n")
    return "\n".join(parts)

def build_system_prompt(current_iteration: int, max_iterations: int, is_final: bool) -> str:
    """Builds the dynamic system prompt based on iteration context."""
    base = f"""Ты — аналитик-синтезатор. Твоя задача — оценить собранные материалы и принять решение.

Тебе дано:
- Оригинальный запрос пользователя
- Цель исследования
- Собранные тексты источников
- Номер текущей итерации: {current_iteration} из {max_iterations}

Инструкция:

Если собранного материала ДОСТАТОЧНО для достижения цели:
  - Установи "status": "complete"
  - Напиши детальный "final_answer" на основе источников
  - "missing_info": null, "new_queries": []

Если НЕДОСТАТОЧНО:
  - Установи "status": "incomplete"  
  - В "missing_info" опиши конкретно, чего не хватает
  - В "new_queries" дай 2-3 новых поисковых запроса для восполнения пробелов"""
    
    if is_final:
        base += """

[СПЕЦИАЛЬНОЕ ПРАВИЛО — ТОЛЬКО ПРИ current_iteration == max_iterations]
Это последняя попытка. Статус ОБЯЗАТЕЛЬНО "complete".
Синтезируй лучший возможный ответ из имеющихся данных.
Если по каким-то аспектам информации нет — честно укажи это в final_answer.
Никогда не оставляй пользователя без ответа."""
        
    base += "\n\nОтвет строго в формате JSON, без пояснений и преамбулы."
    return base

def parse_judge_output(raw: str, inp: JudgeInput) -> JudgeOutput:
    """Parses LLM JSON and applies safety limits on iterations."""
    
    clean = re.sub(r"```json|```", "", raw).strip()
    
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        # Fallback regex
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.error(f"Failed to parse AI-Judge JSON output: {raw}")
                raise ValueError("Невалидный JSON от Судьи")
        else:
            logger.error(f"No JSON structure found in AI-Judge response: {raw}")
            raise ValueError("Структура JSON не обнаружена")
            
    status = data.get("status")
    if status not in ("complete", "incomplete"):
        logger.warning(f"Unknown status '{status}', defaulting to 'incomplete'.")
        status = "incomplete"
        
    # Safeguard: Forced complete on max iterations
    if inp.current_iteration >= inp.max_iterations and status == "incomplete":
        logger.warning(f"AI-Judge returned 'incomplete' on max_iteration={inp.max_iterations}. Forcing 'complete' override.")
        status = "complete"
        # Populate final_answer if missing since we bypass LLM completion
        if not data.get("final_answer"):
            data["final_answer"] = "Поиск достиг лимита итераций. Полную информацию собрать не удалось на основе найденных источников: " + str(data.get("missing_info", ""))
            
    return JudgeOutput(
        status=status,
        final_answer=data.get("final_answer"),
        missing_info=data.get("missing_info"),
        new_queries=data.get("new_queries", [])
    )

async def judge(inp: JudgeInput) -> JudgeOutput:
    """Evaluates search result context array via LLM layer."""
    is_final = inp.current_iteration >= inp.max_iterations
    
    system = build_system_prompt(
        current_iteration=inp.current_iteration,
        max_iterations=inp.max_iterations,
        is_final=is_final
    )
    
    user_message = f"Запрос: {inp.original_query}\nЦель: {inp.goal}\n\nСобранные материалы:\n{format_context(inp.context)}"
    
    try:
        response_text = await llm.generate_json(
            prompt=user_message,
            system_prompt=system,
            model_name=DEFAULT_MODEL
        )
        return parse_judge_output(response_text, inp)
    except Exception as e:
        logger.error(f"Error during AI-Judge execution: {e}")
        raise
