# Задача 2: Discovery-воркер и прогрев пула (SearXNG Harvester)

## Контекст и цель

Автономный фоновый процесс. Отвечает за актуализацию списка поисковых серверов: скачивает телеметрию с `searx.space`, фильтрует мусорные узлы, проводит Health-check и передаёт чистые данные в модуль управления репутацией (Задача 1).

Запускается как фоновая задача FastAPI при старте сервиса (через `lifespan` events) и периодически повторяется раз в час.

---

## Конфигурация

Все параметры берутся из переменных окружения или имеют разумные дефолты:

```
REDIS_URL=redis://localhost:6379          # передаётся в Задачу 1
HARVESTER_INTERVAL_SEC=3600               # период между запусками (по умолчанию 1 час)
HEALTH_CHECK_TIMEOUT_SEC=2.0              # жёсткий таймаут проверки ноды
HEALTH_CHECK_CONCURRENCY=20              # максимум параллельных health-check запросов
```

---

## Входные / выходные данные

- **Вход:** триггер по расписанию (раз в час) или при старте системы
- **Выход:** запись в Redis новых валидных узлов через интерфейс Задачи 1

---

## Основная логика

### Шаг 1: Парсинг списка нод

Асинхронный GET-запрос к `https://searx.space/data/instances.json`.

### Шаг 2: Первичный фильтр

Из полученного массива отбросить все ноды, где выполняется хотя бы одно условие:
- `network_type != "normal"` (Tor, I2P и прочее)
- `uptime < 90%`
- `http.grade` ниже `"B"` (допустимые значения: `"A+"`, `"A"`, `"A-"`, `"B+"`, `"B"`)

### Шаг 3: Health-check (Триаж нод)

Взять прошедшие фильтр URL (обычно 30–50 штук) и параллельно отправить тестовые запросы:

```
GET {node_url}?q=test&format=json
```

Ограничения:
- Таймаут на каждый запрос: **2.0 секунды** (жёстко)
- Семафор параллелизма: `asyncio.Semaphore(HEALTH_CHECK_CONCURRENCY)`
- Валидный ответ: HTTP 200 + тело парсируется как JSON без ошибок

### Шаг 4: Синхронизация состояния

Для каждой ноды, прошедшей Health-check:
- Проверить через интерфейс Задачи 1, есть ли она уже в ZSET
- Если нет — добавить с базовым score **100**
- Если есть — не трогать (не обнулять существующий score)

```python
async def sync_node(url: str):
    existing_score = await redis_client.zscore("searx:nodes:score", url)
    if existing_score is None:
        await redis_client.zadd("searx:nodes:score", {url: 100.0}, nx=True)
    # nx=True гарантирует идемпотентность: не перезапишет существующий score
```

---

## Обработка исключений

### searx.space недоступен (503 / Таймаут)

```
Действие: залогировать ошибку на уровне ERROR
Результат: воркер засыпает на HARVESTER_INTERVAL_SEC
Запрет: НЕ удалять и НЕ изменять существующие записи в Redis
```

### Ни одна нода не прошла Health-check

```
Действие: вывести в лог CRITICAL-сообщение с пояснением
Пример: "CRITICAL: Все ноды провалили health-check. Возможен IP-бан хостинга или недоступность сети."
Результат: существующий пул в Redis остаётся без изменений
```

---

## Структура фонового воркера

```python
async def harvester_loop():
    while True:
        try:
            await run_harvest_cycle()
        except Exception as e:
            logger.error(f"Harvest cycle failed: {e}")
        await asyncio.sleep(HARVESTER_INTERVAL_SEC)

async def run_harvest_cycle():
    instances = await fetch_instances()          # Шаг 1
    if instances is None:
        return                                    # searx.space недоступен — выходим тихо
    
    filtered = apply_primary_filter(instances)  # Шаг 2
    healthy = await health_check_all(filtered)  # Шаг 3
    
    if not healthy:
        logger.critical("CRITICAL: ни одна нода не прошла health-check")
        return
    
    for url in healthy:
        await sync_node(url)                     # Шаг 4
    
    logger.info(f"Harvest complete: {len(healthy)} живых нод синхронизировано")
```

---

## План тестирования (Критерии приёмки)

### Тест 1: Фильтрация мок-данных

```
Дано: мок-сервер отдаёт JSON с тремя нодами:
  - нода A: network_type="tor" (должна быть отброшена)
  - нода B: uptime=85%, http.grade="C" (должна быть отброшена)
  - нода C: network_type="normal", uptime=99%, http.grade="A" (должна пройти)
  
Мок health-check: нода C отвечает 200 OK + валидный JSON за 0.5 сек

Ожидаемый результат: в Redis добавлена только нода C со score 100
```

### Тест 2: Таймаут Health-check

```
Дано: нода D настроена отвечать за 3 секунды
HEALTH_CHECK_TIMEOUT_SEC = 2.0

Ожидаемый результат:
  - воркер отбрасывает ноду D (таймаут)
  - процесс не зависает и не падает
  - в Redis нода D не появляется
```

### Тест 3: Идемпотентность

```
Дано: нода E уже в Redis со score 150 (заработанным ранее)
Действие: запустить полный цикл harvester дважды подряд

Ожидаемый результат после двух запусков:
  - score ноды E остаётся 150 (не сбрасывается в 100)
  - нода E не дублируется в ZSET
```
