import os
import json
import re
import logging
import asyncio
import yaml
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from app.core import llm

logger = logging.getLogger(__name__)

# Model Configuration
# Судья использует JUDGE_LLM_MODEL — отделён от оценщика.
# По умолчанию gemini-2.5-flash-lite: допускает большой контекст и стоит дёшево.
provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
if provider == "openai":
    JUDGE_LLM_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
else:
    JUDGE_LLM_MODEL = os.environ.get("JUDGE_LLM_MODEL", "gemini-3.1-flash-lite-preview")

@dataclass
class JudgeInput:
    original_query: str
    goal: str
    context: Dict[str, Optional[str]]
    current_iteration: int
    max_iterations: int
    executed_queries: List[str]

@dataclass
class JudgeOutput:
    status: str
    useful_urls: List[str]
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

_prompts_config = None

def get_prompts_config():
    global _prompts_config
    if _prompts_config is None:
        config_path = Path(__file__).resolve().parent.parent / "config" / "prompts.yaml"
        with open(config_path, "r", encoding="utf-8") as f:
            _prompts_config = yaml.safe_load(f)
    return _prompts_config

def build_system_prompt(current_iteration: int, max_iterations: int, is_final: bool) -> str:
    """Builds the dynamic system prompt based on iteration context."""
    prompts_config = get_prompts_config()
        
    base = prompts_config.get("ai_judge_system", "")
    
    final_attempt_rule = ""
    if is_final:
        final_attempt_rule = """
[СПЕЦИАЛЬНОЕ ПРАВИЛО — ТОЛЬКО ПРИ current_iteration >= max_iterations]
Это последняя попытка. Статус ОБЯЗАТЕЛЬНО \"complete\".
Верни \"useful_urls\" с лучшими из имеющихся источников, даже если они не охватывают цель на 100%.
"""
    return base.format(
        current_iteration=current_iteration, 
        max_iterations=max_iterations, 
        final_attempt_rule=final_attempt_rule
    ).strip()

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

    useful_urls = data.get("useful_urls", [])
    if not isinstance(useful_urls, list):
        useful_urls = []
        
    if status == "incomplete":
        useful_urls = []
            
    return JudgeOutput(
        status=status,
        useful_urls=useful_urls,
        missing_info=data.get("missing_info"),
        new_queries=data.get("new_queries", [])
    )

async def judge(inp: JudgeInput) -> JudgeOutput:
    """Evaluates search result context array via LLM layer with retry on 429."""
    logger.info(f"AI-Judge evaluating content (Iteration {inp.current_iteration}/{inp.max_iterations}), model={JUDGE_LLM_MODEL}...")
    is_final = inp.current_iteration >= inp.max_iterations
    
    system = build_system_prompt(
        current_iteration=inp.current_iteration,
        max_iterations=inp.max_iterations,
        is_final=is_final
    )
    
    # --- Локальное усечение контекста (Task 3) ---
    # Создаём копию — исходный словарь inp.context НЕ изменяем!
    JUDGE_MAX_CHARS_PER_SOURCE = int(os.environ.get("JUDGE_MAX_CHARS_PER_SOURCE", 6000))
    TRUNCATION_MARKER = "\n\n...[УСЕЧЕНО ДЛЯ СУДЬИ]"
    truncated_context: Dict[str, Optional[str]] = {}
    for url, text in inp.context.items():
        if text and len(text) > JUDGE_MAX_CHARS_PER_SOURCE:
            truncated_context[url] = text[:JUDGE_MAX_CHARS_PER_SOURCE] + TRUNCATION_MARKER
        else:
            truncated_context[url] = text

    user_message = f"Запрос: {inp.original_query}\nЦель: {inp.goal}\nУже выполненные поисковые запросы (НЕ ПРЕДЛАГАЙ ИХ СНОВА): {inp.executed_queries}\n\nСобранные материалы:\n{format_context(truncated_context)}"
    
    # Retry logic for 429 RESOURCE_EXHAUSTED with exponential backoff
    max_retries = int(os.environ.get("LLM_MAX_RETRIES", 3))
    retry_delay = float(os.environ.get("LLM_RETRY_DELAY_SEC", 30.0))
    
    last_exc = None
    for attempt in range(1, max_retries + 1):
        try:
            response_text = await llm.generate_json(
                prompt=user_message,
                system_prompt=system,
                model_name=JUDGE_LLM_MODEL
            )
            return parse_judge_output(response_text, inp)
        except Exception as e:
            err_str = str(e)
            last_exc = e
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                delay_match = re.search(r'retryDelay.*?(\d+)s', err_str)
                wait = float(delay_match.group(1)) + 2.0 if delay_match else retry_delay
                if attempt < max_retries:
                    logger.warning(f"AI-Judge: 429 quota exceeded (attempt {attempt}/{max_retries}). Retrying in {wait:.0f}s...")
                    await asyncio.sleep(wait)
                    continue
                else:
                    logger.error(f"AI-Judge: quota exceeded after {max_retries} retries. Giving up.")
            else:
                logger.error(f"Error during AI-Judge execution: {e}")
            break

    raise last_exc
