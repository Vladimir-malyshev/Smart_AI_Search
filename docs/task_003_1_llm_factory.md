# Задача 3.1: Абстрактный слой LLM (Фабрика Провайдеров)

## Контекст и цель
Архитектурный фундамент для работы с нейросетями. Модуль предоставляет единый интерфейс для генерации ответов, скрывая под капотом разницу между официальным API Google Gemini и OpenAI-совместимыми API (OpenAI, Groq, DeepSeek, vLLM, Ollama). 

---

## Конфигурация

```env
LLM_PROVIDER=gemini               # "gemini" или "openai"

# Настройки для Gemini (новый SDK)
GEMINI_API_KEY=...
GEMINI_MODEL=gemini-2.5-flash     # или gemma-3...

# Настройки для OpenAI-совместимых API
OPENAI_API_KEY=...
OPENAI_BASE_URL=[https://api.openai.com/v1](https://api.openai.com/v1)  # можно менять для Groq/Ollama
OPENAI_MODEL=gpt-4o

Входные / выходные данные

Модуль должен экспортировать глобальный экземпляр провайдера (или интерфейс), который поддерживает метод:

    Вход: prompt (str), system_prompt (str), model_name (str, опционально, берется из env по дефолту)

    Выход: Строка, содержащая валидный JSON.

Основная логика (app/core/llm.py)
1. Выбор провайдера

При инициализации модуль читает LLM_PROVIDER. В зависимости от значения, инициализируется нужный клиент.
2. Реализация Gemini (google-genai)

Использовать строго новый пакет google-genai (не google-generativeai).
Асинхронная генерация выполняется через client.aio.models.generate_content.
Для гарантии JSON необходимо передавать конфигурацию:
config = {"response_mime_type": "application/json", "system_instruction": system_prompt}
3. Реализация OpenAI (openai)

Использовать пакет openai и класс AsyncOpenAI.
Для гарантии JSON передавать response_format={"type": "json_object"}.
4. Унифицированный метод generate_json

Оба провайдера оборачиваются в единый метод async def generate_json(...) -> str. Любой код бизнес-логики (Задачи 4, 5, 7) будет вызывать только этот метод, ничего не зная о том, какой провайдер активен под капотом.