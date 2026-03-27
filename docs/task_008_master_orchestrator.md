# Задача 8: Master-Оркестратор и API Шлюз (State Machine & FastAPI)

## Контекст и цель

Сборка всех модулей (Задачи 1–7) в единый пайплайн. Управляет итерационным циклом поиска и синтеза, выставляет REST API наружу, запускает фоновый воркер обновления нод.

---

## Конфигурация

```
REDIS_URL=redis://localhost:6379      # туннель в dev, прямой в prod — код одинаков
GEMINI_API_KEY=...
JINA_API_KEY=...
MAX_ITERATIONS=3                      # максимум циклов поиска
GLOBAL_TIMEOUT_SEC=45                 # таймаут всего пайплайна на один запрос
HARVESTER_INTERVAL_SEC=3600           # период обновления пула нод
```

**Важно:** все параметры через env-переменные. Нет ни одной строки с хардкодом IP, портов, ключей или таймаутов.

---

## Входные / выходные данные

**Запрос:**
```
POST /api/v1/research
Content-Type: application/json

{
  "query": "Какие AI-фреймворки используют крупные компании в 2026?",
  "goal": "Сформировать шорт-лист фреймворков для корпоративного внедрения"
}
```

**Ответ:**
```json
{
  "status": "complete",
  "answer": "По данным собранных источников...",
  "iterations_used": 2,
  "sources": ["https://...", "https://..."],
  "elapsed_sec": 18.4
}
```

---

## Структура FastAPI-приложения

### Жизненный цикл (Lifespan)

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Старт: запустить фоновый воркер обновления нод
    harvester_task = asyncio.create_task(harvester_loop())
    yield
    # Завершение: остановить воркер
    harvester_task.cancel()

app = FastAPI(lifespan=lifespan)
```

### API Endpoint

```python
@app.post("/api/v1/research")
async def research(request: ResearchRequest) -> ResearchResponse:
    start_time = asyncio.get_event_loop().time()
    
    try:
        result = await asyncio.wait_for(
            run_research_pipeline(request.query, request.goal),
            timeout=GLOBAL_TIMEOUT_SEC
        )
        return result
    
    except asyncio.TimeoutError:
        # Глобальный таймаут: вернуть то, что успели собрать
        logger.warning(f"Глобальный таймаут {GLOBAL_TIMEOUT_SEC}с для запроса: {request.query}")
        return ResearchResponse(
            status="timeout",
            answer="Превышено время ожидания. Частичный результат: " + get_partial_context(),
            iterations_used=-1,
            elapsed_sec=GLOBAL_TIMEOUT_SEC
        )
```

---

## Контроллер цикла (Research Pipeline)

```python
async def run_research_pipeline(query: str, goal: str) -> ResearchResponse:
    # Каждый вызов имеет изолированный контекст — никаких глобальных переменных
    accumulated_context: dict[str, str] = {}
    current_queries: list[str] | None = None
    
    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info(f"Итерация {iteration}/{MAX_ITERATIONS}")
        
        # Шаг 1: Генерация поисковых запросов
        if current_queries is None:
            # Первая итерация — AI планировщик
            current_queries = await expand_query(query, goal)          # Задача 4
        # else: current_queries уже содержит new_queries от Судьи
        
        # Шаг 2: Параллельный поиск
        snippets = await execute_searches(current_queries)              # Задача 3
        
        # Шаг 3: Триаж сниппетов
        selected_urls = await evaluate_snippets(goal, snippets)        # Задача 5
        
        if not selected_urls:
            logger.warning(f"Итерация {iteration}: триаж не выбрал ни одного URL")
            continue
        
        # Шаг 4: Извлечение контента
        new_content = await fetch_all(selected_urls)                   # Задача 6
        accumulated_context.update(new_content)
        
        # Шаг 5: Оценка Судьи
        judge_result = await judge(JudgeInput(
            original_query=query,
            goal=goal,
            context=accumulated_context,
            current_iteration=iteration,
            max_iterations=MAX_ITERATIONS
        ))                                                              # Задача 7
        
        if judge_result.status == "complete":
            return ResearchResponse(
                status="complete",
                answer=judge_result.final_answer,
                iterations_used=iteration,
                sources=list(accumulated_context.keys()),
                elapsed_sec=get_elapsed()
            )
        
        # Неполный результат — готовим запросы для следующей итерации
        current_queries = judge_result.new_queries
        logger.info(f"Итерация {iteration}: неполный результат, новые запросы: {current_queries}")
    
    # Цикл завершён (не должны сюда попасть — Судья принудит complete на MAX_ITERATIONS)
    return ResearchResponse(status="complete", answer="Исчерпан лимит итераций", ...)
```

---

## Изоляция контекстов параллельных запросов

**Критически важно:** `accumulated_context` и `current_queries` — локальные переменные функции `run_research_pipeline`. Никаких глобальных переменных, которые могли бы смешать контексты двух одновременных запросов.

Каждый POST-запрос к API создаёт независимый стек вызовов через `asyncio`.

---

## Обработка исключений

### Глобальный таймаут (45 секунд)

`asyncio.wait_for` оборачивает весь пайплайн. При таймауте — возврат частичного результата (см. endpoint выше), не 500-ошибка.

### Пустой пул нод при старте

Если сервис стартует, а Redis пуст (первый запуск, Harvester ещё не успел отработать):
- Harvester запускается при старте (`lifespan`)
- Первый цикл Harvester завершается до того, как начнут приходить запросы (или добавить `await первый_запуск_harvester()` в `lifespan` перед `yield`)

---

## План тестирования (Критерии приёмки)

### Тест 1: End-to-End «Идеальный путь»

```
Действие: POST /api/v1/research {"query": "Что такое LangChain?", "goal": "Базовое понимание"}

Ожидаемый результат:
  - HTTP 200
  - status = "complete"
  - iterations_used = 1
  - answer содержит осмысленный текст о LangChain
  - elapsed_sec < 30
```

### Тест 2: End-to-End «Глубокий ресёрч»

```
Действие: POST /api/v1/research с узкоспециализированным запросом

Проверка по логам:
  - зафиксирована строка "Итерация 2/3"
  - на второй итерации использованы new_queries от Судьи (не исходный запрос)
  - итоговый ответ содержательнее, чем мог бы быть за одну итерацию
```

### Тест 3: Изоляция параллельных запросов

```
Действие: отправить 5 разных POST-запросов одновременно (asyncio.gather на клиенте)

Ожидаемый результат:
  - все 5 запросов получили ответ
  - контент ответов соответствует своим запросам (не перемешаны)
  - в логах сервера нет ошибок типа KeyError или смешения контекстов
```
