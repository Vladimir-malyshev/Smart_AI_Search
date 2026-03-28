import os
import re
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

        ВАЖНО: Gemma-3 (gemma-3-27b-it) НЕ поддерживает:
          - system_instruction в GenerateContentConfig
          - response_mime_type="application/json"
        Поэтому для Gemini-провайдера оба промпта объединяются в один user-prompt,
        а JSON извлекается из сырого текста ответа через регулярное выражение.
        """
        if self.provider == "gemini":
            from google.genai import types

            # Объединяем system + user prompt, явно требуем чистый JSON в ответе
            combined_prompt = (
                f"System Instruction:\n{system_prompt}\n\n"
                f"User Question:\n{prompt}\n\n"
                "IMPORTANT: Your response MUST be valid JSON only. "
                "Do not include any explanation, markdown, or code fences. "
                "Output raw JSON and nothing else."
            )

            config = types.GenerateContentConfig(temperature=0.3)

            response = await self.gemini_client.aio.models.generate_content(
                model=model_name,
                contents=combined_prompt,
                config=config,
            )
            return self._extract_json(response.text or "")

        elif self.provider == "openai":
            response = await self.openai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
            )
            return response.choices[0].message.content


# Default instance helper — ленивая инициализация singleton
def get_llm_provider() -> LLMProvider:
    if not hasattr(get_llm_provider, "_instance"):
        get_llm_provider._instance = LLMProvider()
    return get_llm_provider._instance


async def generate_json(prompt: str, system_prompt: str, model_name: str) -> str:
    """Convenience wrapper для генерации JSON."""
    provider = get_llm_provider()
    return await provider.generate_json(prompt, system_prompt, model_name)
