# Задача 1: Модуль управления состоянием нод (Redis State Manager)

## Контекст и цель

Базовый слой абстракции для работы с Redis. Хранит «репутацию» публичных серверов SearXNG. Модуль ничего не знает о поиске — он предоставляет интерфейс для CRUD-операций с оценками нод и управляет «карантином» ненадёжных серверов.

---

## Конфигурация подключения к Redis

**Критически важно:** строка подключения берётся исключительно из переменной окружения `REDIS_URL`. Менять код при смене окружения запрещено.

```
# Разработка (Redis на удалённом сервере через SSH-туннель):
REDIS_URL=redis://localhost:6379   # туннель пробрасывает удалённый Redis на локальный порт

# Продакшн (Redis на том же сервере):
REDIS_URL=redis://localhost:6379   # строка идентична, туннель не нужен
```

Пример инициализации пула соединений:
```python
import redis.asyncio as aioredis
import os

REDIS_URL = os.environ["REDIS_URL"]  # обязательно, без дефолта

pool = aioredis.ConnectionPool.from_url(REDIS_URL, max_connections=20)
redis_client = aioredis.Redis(connection_pool=pool)
```

---

## Входные / выходные данные

- **Вход:** URL ноды + метрика (время ответа в мс) или флаг ошибки (таймаут, 502)
- **Выход:** списки URL (Топ-N лучших), подтверждения записи

---

## Основная логика

### Ключи Redis

| Структура | Ключ | Назначение |
|-----------|------|------------|
| Sorted Set | `searx:nodes:score` | Репутация нод: URL → score |
| String + TTL | `searx:quarantine:{url}` | Карантин: присутствие ключа = нода заблокирована |

### Хранение репутации (ZSET)

- Базовый рейтинг новой ноды: **100**
- Методы `add_score(url, delta)` и `reduce_score(url, delta)` используют атомарную операцию `ZINCRBY`
- Минимальный порог score: **0** (не уходить в отрицательные значения)

```python
async def add_score(url: str, delta: float):
    await redis_client.zincrby("searx:nodes:score", delta, url)

async def reduce_score(url: str, delta: float):
    current = await redis_client.zscore("searx:nodes:score", url) or 0
    new_score = max(0.0, current - delta)
    # Атомарно установить новое значение через ZADD с опцией GT/LT или pipeline
    async with redis_client.pipeline() as pipe:
        await pipe.zadd("searx:nodes:score", {url: new_score}, xx=True)
        await pipe.execute()
```

### Управление карантином (TTL)

Если нода падает:
1. Удалить URL из ZSET
2. Записать ключ `searx:quarantine:{url}` с TTL = **3600 секунд**
3. По истечении TTL Redis сам удалит ключ — нода снова доступна для добавления

```python
async def quarantine(url: str, ttl: int = 3600):
    async with redis_client.pipeline() as pipe:
        await pipe.zrem("searx:nodes:score", url)
        await pipe.set(f"searx:quarantine:{url}", "1", ex=ttl)
        await pipe.execute()

async def is_quarantined(url: str) -> bool:
    return await redis_client.exists(f"searx:quarantine:{url}") > 0
```

### Выборка (Routing Pool)

Метод `get_top_nodes(limit=10)`:
1. `ZREVRANGE searx:nodes:score 0 (limit*2 - 1)` — взять с запасом
2. Для каждого URL проверить `is_quarantined(url)`
3. Вернуть первые `limit` не заблокированных URL

---

## Обработка исключений

### Обрыв связи с Redis (Circuit Breaker)

Если Redis недоступен, модуль переходит на **in-memory fallback**:
- Словарь `_fallback_scores: dict[str, float]` в памяти процесса
- Логировать каждое обращение к fallback на уровне `WARNING`
- При восстановлении соединения (следующий успешный запрос к Redis) — синхронизировать накопленные изменения обратно

```python
_fallback_scores: dict[str, float] = {}
_redis_available: bool = True

async def get_top_nodes(limit: int = 10) -> list[str]:
    try:
        # ... основная логика через Redis
        _redis_available = True
    except (aioredis.ConnectionError, aioredis.TimeoutError) as e:
        logger.warning(f"Redis недоступен, используется fallback: {e}")
        _redis_available = False
        return sorted(_fallback_scores, key=_fallback_scores.get, reverse=True)[:limit]
```

**Важно:** при нескольких параллельных воркерах (продакшн) fallback-словарь изолирован в рамках одного процесса. Для многопроцессного деплоя — только Redis, fallback является временной мерой.

### Отрицательный Score

Score не может опускаться ниже 0. Проверка выполняется в `reduce_score` перед записью.

---

## План тестирования (Критерии приёмки)

### Тест 1: Атомарность параллельного начисления очков

```
Дано: нода X с базовым score 100
Действие: параллельно (asyncio.gather) передать ноде +5 очков три раза
Ожидаемый результат: итоговый score ровно 115
Проверяет: отсутствие race condition при использовании ZINCRBY
```

### Тест 2: Жизненный цикл карантина

```
Дано: нода Y в пуле
Действие: вызвать quarantine(url_Y)
Проверка 1: Y присутствует в ключах quarantine, отсутствует в ZSET
Действие: замокать время Redis (fakeredis или time travel) на +3601 секунду
Проверка 2: ключ quarantine для Y пропал, is_quarantined(url_Y) = False
Проверка 3: Y можно снова добавить в ZSET
```

### Тест 3: Ранжирование

```
Дано: 5 нод со scores [10, 50, 20, 100, 5]
Действие: get_top_nodes(3)
Ожидаемый результат: список строго из трёх URL в порядке [100, 50, 20]
```
