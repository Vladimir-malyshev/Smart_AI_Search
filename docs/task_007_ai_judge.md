# Задача 7: AI-Судья (Reflection, Evaluation & Synthesis)

## Контекст и цель

Ядро логики Agentic RAG. Читает полные тексты страниц и принимает решение: достаточно ли собранной информации для формирования ответа, или нужен ещё один круг поиска. При последней итерации — принудительно синтезирует ответ из того, что есть.

---

## Конфигурация

```
GEMINI_API_KEY=...
GEMINI_MODEL=gemma-3-27b-it    # старшая модель линейки Gemma 3; Судья — критическая точка, нужна максимальная мощность
MAX_ITERATIONS=3               # максимум итераций поиска (передаётся из оркестратора)
```

---

## Входные / выходные данные

**Вход:**
```python
@dataclass
class JudgeInput:
    original_query: str           # исходный запрос пользователя
    goal: str                     # цель
    context: dict[str, str]       # {url: markdown_content} из Задачи 6
    current_iteration: int        # номер текущей итерации (начиная с 1)
    max_iterations: int           # максимум итераций
```

**Выход:** строгий JSON одной из двух форм:

```json
// Если информации достаточно:
{
  "status": "complete",
  "final_answer": "Подробный синтезированный ответ...",
  "missing_info": null,
  "new_queries": []
}

// Если нужен ещё один круг:
{
  "status": "incomplete",
  "final_answer": null,
  "missing_info": "Не найдено данных о конкретных ценах и методологии расчёта",
  "new_queries": ["запрос1", "запрос2"]
}
```

---

## Основная логика

### Системный промпт

```
Ты — аналитик-синтезатор. Твоя задача — оценить собранные материалы и принять решение.

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
  - В "new_queries" дай 2-3 новых поисковых запроса для восполнения пробелов

[СПЕЦИАЛЬНОЕ ПРАВИЛО — ТОЛЬКО ПРИ current_iteration == max_iterations]
Это последняя попытка. Статус ОБЯЗАТЕЛЬНО "complete".
Синтезируй лучший возможный ответ из имеющихся данных.
Если по каким-то аспектам информации нет — честно укажи это в final_answer.
Никогда не оставляй пользователя без ответа.

Ответ строго в формате JSON, без пояснений и преамбулы.
```

### Формирование контекста

Подготовить компактное представление собранных текстов:

```python
def format_context(context: dict[str, str | None]) -> str:
    parts = []
    for url, content in context.items():
        if content:
            parts.append(f"=== Источник: {url} ===\n{content}\n")
        else:
            parts.append(f"=== Источник: {url} ===\n[Контент недоступен]\n")
    return "\n".join(parts)
```

### Вызов API

```python
async def judge(inp: JudgeInput) -> JudgeOutput:
    is_final = inp.current_iteration >= inp.max_iterations
    
    system = build_system_prompt(
        current_iteration=inp.current_iteration,
        max_iterations=inp.max_iterations,
        is_final=is_final
    )
    
    user_message = f"""
Запрос: {inp.original_query}
Цель: {inp.goal}

Собранные материалы:
{format_context(inp.context)}
"""
    
    response = await call_gemini(
        user_message,
        system=system,
        model=GEMINI_MODEL,
        response_mime_type="application/json"
    )
    
    return parse_judge_output(response)
```

### Валидация ответа

```python
def parse_judge_output(raw: str) -> JudgeOutput:
    data = json.loads(raw)
    
    status = data.get("status")
    if status not in ("complete", "incomplete"):
        raise ValueError(f"Неожиданный статус: {status}")
    
    return JudgeOutput(
        status=status,
        final_answer=data.get("final_answer"),
        missing_info=data.get("missing_info"),
        new_queries=data.get("new_queries", [])
    )
```

---

## Обработка исключений

### Битый JSON в ответе

Аналогично Задаче 4 — попытка извлечь JSON регулярным выражением. Если не получилось — исключение вверх, оркестратор завершит цикл с частичным ответом.

### Модель вернула `incomplete` на последней итерации

После парсинга проверить: если `current_iteration >= max_iterations` и статус `incomplete` — принудительно изменить на `complete`, залогировать `WARNING`. Это защита от нарушения инструкции моделью.

---

## План тестирования (Критерии приёмки)

### Тест 1: Сценарий «Успех» (Complete)

```
Дано:
  context = {"https://blog.google/...": "<статья о релизе Gemma 3 с датой>"}
  goal = "Когда вышла Gemma 3?"
  current_iteration = 1, max_iterations = 3

Ожидаемый результат:
  - status = "complete"
  - final_answer содержит дату релиза
  - new_queries = []
```

### Тест 2: Сценарий «Неудача» (Incomplete)

```
Дано:
  context = {"https://blog.google/...": "<статья о релизе Gemma 3 с датой>"}
  goal = "Какая архитектура у GPT-5?"
  current_iteration = 1, max_iterations = 3

Ожидаемый результат:
  - status = "incomplete"
  - missing_info содержит упоминание GPT-5
  - new_queries содержит запросы про архитектуру GPT-5
```

### Тест 3: Сценарий «Последний шанс»

```
Дано: те же данные, что в Тесте 2
  current_iteration = 3, max_iterations = 3  (последняя итерация)

Ожидаемый результат:
  - status = "complete" (принудительно)
  - final_answer явно сообщает, что данных о GPT-5 не найдено
  - new_queries = [] или отсутствует
```
