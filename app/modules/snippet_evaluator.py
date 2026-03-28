import os
import json
import logging
import yaml
from pathlib import Path
from typing import List
from app.core import llm
from app.modules.execution_engine import SearchSnippet

logger = logging.getLogger(__name__)

# Configuration
EVALUATOR_MAX_SELECTED = int(os.environ.get("EVALUATOR_MAX_SELECTED", 4))
EVALUATOR_MIN_SELECTED = int(os.environ.get("EVALUATOR_MIN_SELECTED", 1))

# Default model name for evaluator — строго Gemma (flash запрещён в этом модуле)
provider = os.environ.get("LLM_PROVIDER", "gemini").lower()
if provider == "openai":
    DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")
else:
    DEFAULT_MODEL = os.environ.get("EVALUATOR_LLM_MODEL", "gemma-3-27b-it")

config_path = Path(__file__).resolve().parent.parent / "config" / "prompts.yaml"
with open(config_path, "r", encoding="utf-8") as f:
    prompts_config = yaml.safe_load(f)

SYSTEM_PROMPT = prompts_config.get("snippet_evaluator_system", "").format(
    EVALUATOR_MAX_SELECTED=EVALUATOR_MAX_SELECTED
).strip()

def format_snippets_for_llm(snippets: List[SearchSnippet]) -> str:
    """Formats a list of snippets into a numbered list for the prompt."""
    lines = []
    for i, s in enumerate(snippets):
        lines.append(f"[{i}] {s.title}\nURL: {s.url}\n{s.snippet}\n")
    return "\n".join(lines)

async def evaluate_snippets(goal: str, snippets: List[SearchSnippet]) -> List[str]:
    """Uses LLM to evaluate and select the most relevant snippet URLs."""
    if not snippets:
        return []
        
    formatted_snippets = format_snippets_for_llm(snippets)
    prompt = f"Цель: {goal}\n\nСниппеты:\n{formatted_snippets}"
    
    try:
        response_text = await llm.generate_json(
            prompt=prompt,
            system_prompt=SYSTEM_PROMPT,
            model_name=DEFAULT_MODEL
        )
        
        # Simple JSON loading. Error handling is handled by the caller or raises here.
        data = json.loads(response_text)
        raw_urls = data.get("selected_urls", [])
        
        if not isinstance(raw_urls, list):
            logger.error(f"LLM returned unexpected format for selected_urls: {raw_urls}")
            return []
            
        # Anti-hallucination check
        valid_input_urls = {s.url for s in snippets}
        verified = [url for url in raw_urls if url in valid_input_urls]
        
        # Log hallucinations
        hallucinated = set(raw_urls) - set(verified)
        if hallucinated:
            logger.warning(f"LLM hallucinated {len(hallucinated)} URL(s), which were discarded: {hallucinated}")
            
        return verified
        
    except Exception as e:
        logger.error(f"Error evaluating snippets: {e}")
        # Orchestrator will handle this or we return empty to be safe
        return []
