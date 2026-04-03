import os
import json
import re
import logging
from typing import List
from app.core import llm

logger = logging.getLogger(__name__)

# Configuration
QUERY_MAX_WORDS = int(os.environ.get("QUERY_MAX_WORDS", 10))
QUERY_MIN_COUNT = int(os.environ.get("QUERY_MIN_COUNT", 2))
QUERY_MAX_COUNT = int(os.environ.get("QUERY_MAX_COUNT", 5))

# System Prompt with word count constraint
SYSTEM_PROMPT = f"""
Ты — старший исследователь данных. Твоя задача — превратить намерение пользователя 
в набор поисковых запросов для поисковой системы.

Правила генерации запросов:
1. Один запрос должен быть широким (общий контекст темы)
2. Один запрос должен быть узкоспециализированным (профессиональные термины, цифры, даты)
3. Если тема касается технологий, бизнеса или науки — один запрос обязательно на английском 
   языке для охвата западных источников
4. Каждый запрос — не более {QUERY_MAX_WORDS} слов
5. Никаких пояснений, только JSON

Ответ строго в формате:
{{"queries": ["запрос1", "запрос2", "запрос3"]}}
""".strip()

async def expand_query(user_query: str, goal: str) -> List[str]:
    """Expands a user query into multiple optimized search queries using LLM."""
    
    # Determine model name based on provider
    provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
    if provider == "openai":
        model_name = os.environ.get("OPENAI_MODEL", "gpt-4o")
    else:
        # Default to Gemma 3 model for Gemini provider
        model_name = os.environ.get("GEMINI_MODEL", "gemma-3-27b-it")
        
    user_message = f"Запрос пользователя: {user_query}\nЦель: {goal}"
    
    try:
        response_text = await llm.generate_json(
            prompt=user_message,
            system_prompt=SYSTEM_PROMPT,
            model_name=model_name
        )
        return validate_and_parse(response_text)
    except Exception as e:
        logger.error(f"Error expanding query: {e}")
        # Orchestrator will handle this
        raise

def validate_and_parse(raw: str) -> List[str]:
    """Validates and parses the LLM output into a list of queries."""
    
    # Pre-cleaning: Remove markdown if present
    clean = re.sub(r"```json|```", "", raw).strip()
    
    try:
        data = json.loads(clean)
    except json.JSONDecodeError:
        # Fallback to regex extraction if JSON is messy
        match = re.search(r'\{.*\}', clean, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                logger.error(f"Failed to parse LLM response as JSON: {raw}")
                raise ValueError("Невалидный JSON от LLM")
        else:
            logger.error(f"No JSON structure found in LLM response: {raw}")
            raise ValueError("Структура JSON не обнаружена в ответе")
            
    queries = data.get("queries", [])
    
    if not isinstance(queries, list):
        raise ValueError("Поле 'queries' должно быть массивом")
        
    if not (QUERY_MIN_COUNT <= len(queries) <= QUERY_MAX_COUNT):
        raise ValueError(f"Количество запросов ({len(queries)}) вне диапазона [{QUERY_MIN_COUNT}-{QUERY_MAX_COUNT}]")
        
    # Trim each query and filter empty strings
    trimmed = []
    for q in queries:
        words = str(q).strip().split()
        if words:
            trimmed.append(" ".join(words[:QUERY_MAX_WORDS]))
            
    if len(trimmed) < QUERY_MIN_COUNT:
        raise ValueError(f"Недостаточно валидных запросов после очистки: {len(trimmed)}")
        
    return trimmed
