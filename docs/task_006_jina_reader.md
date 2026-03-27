# Задача 6: Экстрактор чистого контента (Jina Reader Integration)

## Контекст и цель

Модуль-преобразователь. Берёт отфильтрованные URL из Задачи 5 и скачивает их содержимое через сервис Jina Reader (`r.jina.ai`), превращая веб-страницы в чистый Markdown для передачи в LLM-Судью.

---

## Конфигурация

```
JINA_API_KEY=...                        # если используется платный tier
JINA_MAX_CHARS=20000                    # лимит символов на один документ
JINA_TIMEOUT_SEC=15.0                   # таймаут на запрос к Jina
JINA_CONCURRENCY=4                      # параллелизм (обычно 2-4 URL)
```

---

## Входные / выходные данные

- **Вход:** массив из 2–4 проверенных URL
- **Выход:** словарь `{url: markdown_content}` (значение `None` если страница недоступна)

---

## Основная логика

### Шаг 1: Запрос к Jina

Для каждого URL отправить GET-запрос:

```
GET https://r.jina.ai/{url}
Headers:
  Authorization: Bearer {JINA_API_KEY}   # если есть
  Accept: text/markdown
```

Запросы выполняются параллельно через `asyncio.gather` с семафором `JINA_CONCURRENCY`.

### Шаг 2: Контроль размера (Truncation)

Если длина полученного Markdown превышает `JINA_MAX_CHARS`:
1. Обрезать текст до `JINA_MAX_CHARS` символов
2. Добавить в конец маркер: `\n\n[...ТЕКСТ ОБРЕЗАН — достигнут лимит контекста...]`

```python
def truncate_content(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[...ТЕКСТ ОБРЕЗАН — достигнут лимит контекста...]"
```

### Шаг 3: Обработка ошибок Jina

Признаки недоступного контента (проверять в ответе Jina):
- HTTP статус 404, 403, 429, 5xx
- Тело ответа содержит признаки пейволла: `"This page requires a subscription"`, `"Access denied"`
- Тело ответа содержит признаки Cloudflare-капчи: `"Just a moment"`, `"Checking your browser"`
- Тело ответа пустое или короче 100 символов

В любом из этих случаев — вернуть `None` для данного URL и залогировать причину.

```python
async def fetch_url(url: str) -> str | None:
    try:
        async with session.get(
            f"https://r.jina.ai/{url}",
            timeout=aiohttp.ClientTimeout(total=JINA_TIMEOUT_SEC)
        ) as resp:
            if resp.status != 200:
                logger.warning(f"Jina: {url} → HTTP {resp.status}")
                return None
            
            content = await resp.text()
            
            if is_blocked_content(content):
                logger.warning(f"Jina: {url} → пейволл или капча")
                return None
            
            return truncate_content(content, JINA_MAX_CHARS)
    
    except asyncio.TimeoutError:
        logger.warning(f"Jina: {url} → таймаут {JINA_TIMEOUT_SEC}с")
        return None
    except aiohttp.ClientError as e:
        logger.warning(f"Jina: {url} → ошибка сети: {e}")
        return None


def is_blocked_content(text: str) -> bool:
    if len(text) < 100:
        return True
    blocked_phrases = [
        "Just a moment", "Checking your browser",
        "requires a subscription", "Access denied",
        "Enable JavaScript", "403 Forbidden"
    ]
    return any(phrase.lower() in text.lower() for phrase in blocked_phrases)
```

### Сборка результата

```python
async def fetch_all(urls: list[str]) -> dict[str, str | None]:
    sem = asyncio.Semaphore(JINA_CONCURRENCY)
    
    async def fetch_with_sem(url):
        async with sem:
            return url, await fetch_url(url)
    
    results = await asyncio.gather(*[fetch_with_sem(u) for u in urls])
    return dict(results)
```

---

## Обработка исключений

Модуль **никогда не бросает исключение** наружу за пределы `fetch_all`. Любая ошибка по конкретному URL → `None` в словаре + запись в лог. Оркестратор (Задача 8) обработает пустые значения.

---

## План тестирования (Критерии приёмки)

### Тест 1: Корректная обработка смешанного входа

```
Дано: два URL
  - url_A: реальная статья (например, с Хабра)
  - url_B: несуществующий URL (404)

Ожидаемый результат:
  - result[url_A]: непустая строка Markdown с содержимым статьи
  - result[url_B]: None
  - процесс не упал с исключением
```

### Тест 2: Обрезка контента

```
Дано: Jina возвращает текст длиной 50 000 символов
JINA_MAX_CHARS = 20 000

Ожидаемый результат:
  - len(result[url]) <= 20 000
  - в конце строки присутствует маркер "[...ТЕКСТ ОБРЕЗАН...]"
```
