# Задача 3: Сетевой движок параллельного поиска (Smart Execution Engine)

## Контекст и цель

Ядро роутинга. Принимает список поисковых запросов, запрашивает у Redis лучшие ноды, асинхронно рассылает запросы, обрабатывает таймауты, начисляет репутацию и возвращает агрегированные результаты.

---

## Конфигурация

```
SEARCH_TIMEOUT_FAST_SEC=1.0      # порог "быстро" для начисления бонуса
SEARCH_TIMEOUT_SLOW_SEC=2.0      # порог "медленно" для штрафа
SEARCH_TIMEOUT_HARD_SEC=5.0      # жёсткий таймаут запроса
SEARCH_FALLBACK_MAX_ATTEMPTS=2   # максимум попыток на один запрос
```

---

## Входные / выходные данные

- **Вход:** массив строк — поисковые запросы, например `["AI tools 2026", "AI enterprise solutions"]`
- **Выход:** сводный список сниппетов — агрегация из всех успешных ответов, без дубликатов по URL

```python
@dataclass
class SearchSnippet:
    url: str
    title: str
    snippet: str
    source_node: str  # URL ноды, которая вернула результат
```

---

## Основная логика

### Шаг 1: Подготовка (назначение нод)

Для каждого запроса из входного массива взять **одну уникальную** топовую ноду из Redis.

**Проблема малого пула:** если активных нод меньше, чем запросов (после карантинов), уникальность не может быть соблюдена. В этом случае:
- Залогировать предупреждение
- Разрешить повторное использование нод (round-robin по доступному списку)
- Не прерывать выполнение

```python
async def assign_nodes(queries: list[str]) -> list[tuple[str, str]]:
    top_nodes = await get_top_nodes(limit=len(queries) * 2)  # с запасом
    if not top_nodes:
        raise RuntimeError("Пул нод пуст: Redis недоступен или все ноды в карантине")
    
    assignments = []
    for i, query in enumerate(queries):
        node = top_nodes[i % len(top_nodes)]  # round-robin если нод меньше запросов
        assignments.append((query, node))
    return assignments
```

### Шаг 2: Исполнение (Fan-out)

Запустить все запросы параллельно через `asyncio.gather(return_exceptions=True)`.

```python
async def execute_search(query: str, node_url: str, attempt: int = 1) -> list[SearchSnippet]:
    start_time = asyncio.get_event_loop().time()
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                node_url,
                params={"q": query, "format": "json"},
                timeout=aiohttp.ClientTimeout(total=SEARCH_TIMEOUT_HARD_SEC)
            ) as resp:
                if resp.status != 200:
                    raise aiohttp.ClientResponseError(...)
                
                data = await resp.json()
                elapsed = asyncio.get_event_loop().time() - start_time
                
                # Обратная связь по скорости
                await update_reputation(node_url, elapsed)
                
                return parse_snippets(data, source_node=node_url)
    
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        await quarantine(node_url)
        
        if attempt < SEARCH_FALLBACK_MAX_ATTEMPTS:
            fallback_nodes = await get_top_nodes(limit=attempt + 2)
            next_node = next((n for n in fallback_nodes if n != node_url), None)
            if next_node:
                return await execute_search(query, next_node, attempt + 1)
        
        logger.warning(f"Все попытки исчерпаны для запроса '{query}'")
        return []  # не прерываем общую работу
```

### Шаг 3: Обратная связь (обновление репутации)

```python
async def update_reputation(node_url: str, elapsed_sec: float):
    if elapsed_sec < SEARCH_TIMEOUT_FAST_SEC:
        await add_score(node_url, 2)       # быстро — бонус
    elif elapsed_sec > SEARCH_TIMEOUT_SLOW_SEC:
        await reduce_score(node_url, 5)    # медленно — штраф
    # в диапазоне [1, 2] сек — репутация не меняется
```

### Шаг 4: Агрегация (Fan-in)

Собрать все результаты из `asyncio.gather`, дедуплицировать по URL, вернуть плоский список.

```python
def deduplicate(snippets: list[SearchSnippet]) -> list[SearchSnippet]:
    seen_urls = set()
    result = []
    for s in snippets:
        if s.url not in seen_urls:
            seen_urls.add(s.url)
            result.append(s)
    return result
```

---

## Обработка исключений

### Все попытки Fallback провалились

Если для одного запроса исчерпаны все попытки (нода в карантине, fallback тоже упал):
- Вернуть пустой список для этого запроса
- Продолжить обработку остальных запросов
- Залогировать WARNING с указанием запроса

Общий результат будет неполным, но функция **не бросает исключение**.

---

## План тестирования (Критерии приёмки)

### Тест 1: Параллельность

```
Дано: 3 мок-ноды, каждая отвечает за 1.5 секунды
Действие: запустить execute_all(["query1", "query2", "query3"])

Ожидаемый результат:
  - общее время выполнения ~1.5 сек (не 4.5 сек)
  - результаты получены от всех трёх нод
```

### Тест 2: Fallback-механика

```
Дано:
  - нода A настроена возвращать 502 Bad Gateway
  - нода B настроена возвращать 200 OK с валидным JSON

Действие: выполнить поисковый запрос, роутер назначил ноду A первой

Ожидаемый результат:
  1. нода A отправлена в карантин Redis
  2. автоматически выбрана нода B
  3. запрос успешно выполнен через ноду B
  4. результат возвращён
```

### Тест 3: Дедупликация

```
Дано: два ответа от разных нод, оба содержат сниппет с URL https://en.wikipedia.org/wiki/Test

Ожидаемый результат:
  - итоговый список содержит этот URL ровно один раз
```
