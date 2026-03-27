import os
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
                # Rely on GEMINI_API_KEY or GOOGLE_API_KEY
                api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
                
                # We can initialize the client gracefully. 
                # If api_key is None, genai.Client uses GOOGLE_API_KEY by default internally if we just pass None.
                # However we want to explicitly support GEMINI_API_KEY from TZ.
                self.gemini_client = genai.Client(api_key=api_key)
            except ImportError:
                raise ImportError("Please install google-genai package for Gemini provider")
            
        elif self.provider == "openai":
            try:
                from openai import AsyncOpenAI
                
                api_key = os.environ.get("OPENAI_API_KEY")
                base_url = os.environ.get("OPENAI_BASE_URL")
                
                self.openai_client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=base_url
                )
            except ImportError:
                raise ImportError("Please install openai package for OpenAI provider")
        else:
            raise ValueError(f"Unsupported LLM_PROVIDER: {self.provider}")

    async def generate_json(self, prompt: str, system_prompt: str, model_name: str) -> str:
        """
        Generates text using the chosen provider and strictly enforces JSON output.
        """
        if self.provider == "gemini":
            from google.genai import types
            
            # According to new SDK: client.aio.models.generate_content
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                temperature=0.3
            )
            
            response = await self.gemini_client.aio.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config
            )
            return response.text
            
        elif self.provider == "openai":
            response = await self.openai_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.3
            )
            return response.choices[0].message.content

# Default instance helper
def get_llm_provider() -> LLMProvider:
    # Could be lazy initialized or cached
    if not hasattr(get_llm_provider, "_instance"):
        get_llm_provider._instance = LLMProvider()
    return get_llm_provider._instance

async def generate_json(prompt: str, system_prompt: str, model_name: str) -> str:
    """Convenience wrapper for json generation."""
    provider = get_llm_provider()
    return await provider.generate_json(prompt, system_prompt, model_name)
