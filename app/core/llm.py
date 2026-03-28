import os
import re
import time
import asyncio
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Default to gemini if not provided
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "gemini").lower()


class LLMProvider:
    def __init__(self):
        self.provider = LLM_PROVIDER

        if self.provider == "gemini":
            try:
                from google import genai
                # Поддерживаем GEMINI_API_KEY и GOOGLE_API_KEY
                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                self.gemini_client = genai.Client(api_key=api_key)
            except ImportError:
                raise ImportError("Please install google-genai package for Gemini provider")

        elif self.provider == "openai":
            try:
                from openai import AsyncOpenAI
                api_key = os.environ.get("OPENAI_API_KEY")
                base_url = os.environ.get("OPENAI_BASE_URL")
                self.openai_client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            except ImportError:
                raise ImportError("Please install openai package for OpenAI provider")
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {self.provider}")

    def _extract_json(self, raw: str) -> str:
        """Извлекает чистый JSON из текста — защита от markdown-обёрток ```json...```."""
        # Пробуем вырезать блок ```json ... ``` или ``` ... ```
        match = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if match:
            return match.group(1).strip()
        return raw.strip()

    async def generate_json(self, prompt: str, system_prompt: str, model_name: str) -> str:
        """
        Генерирует JSON-ответ через выбранного провайдера.
        Включает автоматический retry с экспоненциальным backoff при 429.
        """
        max_retries = int(os.environ.get("LLM_MAX_RETRIES", 4))

        if self.provider == "gemini":
            from google.genai import types

            combined_prompt = (
                f"System Instruction:\n{system_prompt}\n\n"
                f"User Question:\n{prompt}\n\n"
                "IMPORTANT: Your response MUST be valid JSON only. "
                "Do not include any explanation, markdown, or code fences. "
                "Output raw JSON and nothing else."
            )
            config = types.GenerateContentConfig(temperature=0.3)

            last_exc = None
            for attempt in range(1, max_retries + 1):
                try:
                    start_time = time.monotonic()
                    response = await self.gemini_client.aio.models.generate_content(
                        model=model_name,
                        contents=combined_prompt,
                        config=config,
                    )
                    duration = time.monotonic() - start_time
                    result = self._extract_json(response.text or "")
                    logger.info(f"[llm] Gemini {model_name} responded in {duration:.2f}s. Response: {result[:200]}...")
                    return result
                except Exception as e:
                    last_exc = e
                    err_str = str(e)
                    if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                        # Пытаемся извлечь retryDelay из сообщения об ошибке
                        delay_match = re.search(r'retryDelay.*?(\d+)s', err_str)
                        if delay_match:
                            base_wait = float(delay_match.group(1)) + 2.0
                        else:
                            # Экспоненциальный backoff: 10s, 20s, 40s, ...
                            base_wait = 10.0 * (2 ** (attempt - 1))
                        if attempt < max_retries:
                            logger.warning(
                                f"[llm] Gemini 429 RESOURCE_EXHAUSTED (attempt {attempt}/{max_retries}). "
                                f"Waiting {base_wait:.0f}s before retry..."
                            )
                            await asyncio.sleep(base_wait)
                        else:
                            logger.error(f"[llm] Gemini 429: exhausted {max_retries} retries for model={model_name}.")
                    else:
                        # Не квотная ошибка — не ретраим
                        raise
            raise last_exc

        elif self.provider == "openai":
            start_time = time.monotonic()
            response = await self.openai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            duration = time.monotonic() - start_time
            result = response.choices[0].message.content
            logger.info(f"[llm] OpenAI {model_name} responded in {duration:.2f}s. Response: {result[:200]}...")
            return result


# Default instance helper — ленивая инициализация singleton
def get_llm_provider() -> LLMProvider:
    if not hasattr(get_llm_provider, "_instance"):
        get_llm_provider._instance = LLMProvider()
    return get_llm_provider._instance


async def generate_json(prompt: str, system_prompt: str, model_name: str) -> str:
    """Convenience wrapper для генерации JSON."""
    provider = get_llm_provider()
    return await provider.generate_json(prompt, system_prompt, model_name)
