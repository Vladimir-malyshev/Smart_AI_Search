Задача: Внедрение Capability Analyzer (Умного маршрутизатора) для абстракции LLM

Нам необходимо обновить слой абстракции app/core/llm.py, чтобы система могла динамически выбирать способ получения структурированных данных (JSON) в зависимости от возможностей конкретной модели. Мы добавляем поддержку новых моделей (Gemma 4), которые умеют делать это нативно, но должны сохранить обратную совместимость с Gemma 3 (через Prompt Engineering).

Пожалуйста, модифицируй файл app/core/llm.py по следующему плану:

1. Создание Матрицы Возможностей (Capability Registry)
Добавь словарь (или dataclass) MODEL_CAPABILITIES на уровне модуля, который описывает фичи моделей (можно использовать префиксы для матчинга):

    gemma-4: {"native_json_schema": True, "native_tools": True}

    gemini-3.1-flash: {"native_json_schema": True, "native_tools": True}

    gemini-exp: {"native_json_schema": True, "native_tools": True}

    gemma-3: {"native_json_schema": False, "native_tools": False}

    Дефолтное значение для неизвестных моделей: False для обеих фич.

2. Обновление сигнатуры generate_json
Измени метод generate_json (и в классе, и в хелпере-обертке), чтобы он мог принимать желаемую структуру. Добавь опциональный параметр response_schema (тип Any, чтобы принимать Pydantic-модели или dict-схемы).

3. Логика ветвления (Strategy) для провайдера gemini
Внутри метода generate_json, перед вызовом API, проверяй возможности модели по имени:

    Путь А (Нативная поддержка): Если native_json_schema == True:

        НЕ добавляй хардкод-инструкцию "IMPORTANT: Your response MUST be valid JSON only..." в промпт.

        В types.GenerateContentConfig передай параметры: response_mime_type="application/json" и response_schema=response_schema (если схема передана в функцию).

        Не прогоняй результат через self._extract_json, так как ответ уже гарантированно будет чистым JSON.

    Путь Б (Фолбэк / Prompt Engineering): Если native_json_schema == False:

        Оставь текущую логику: склеивай промпт с жесткой текстовой инструкцией про валидный JSON.

        Обязательно прогоняй ответ response.text через существующий метод self._extract_json(raw) для очистки от Markdown-оберток (json...).

4. Жесткие ограничения

    Ни в коем случае не трогай и не ломай логику экспоненциального ретрая (ошибки 429 RESOURCE_EXHAUSTED). Она должна работать для обоих путей.

    Не сломай ветку elif self.provider == "openai":.

    Сохрани асинхронность методов.