# Задача 013: Оптимизация качества поисковых запросов через нативные возможности Jina API

## Контекст

### Текущее состояние кодовой базы (важно прочитать перед реализацией)

В проекте **два файла** содержат функцию `_search_jina`:

| Файл | Роль | Статус Jina-поиска |
|---|---|---|
| `app/modules/execution_engine.py` | Актуальный движок (используется в пайплайне) | `_search_jina` — минимальный, без параметров |
| `app/modules/search_router.py` | Старый роутер (возможно устарел, есть `_search_ddg`, `_search_searxng`) | `_search_jina` — аналогично минимальный |

> **Перед реализацией уточнить:** какой файл реально вызывается из `app/main.py`. Изменять нужно только тот, который используется в активном пайплайне. Если оба используются — обновить оба.

**Текущая реализация `_search_jina` (в обоих файлах):**
```python
url = f"https://s.jina.ai/{query}"  # ← запрос закодирован в path, НЕ в query-параметре
headers = {"Accept": "application/json"}
# Нет: num, hl, gl, nfpr, X-Retain-Images, X-Retain-Links
```

**Текущая реализация `fetch_url` в `app/modules/jina_reader.py`:**
```python
headers = {"Accept": "text/markdown"}  # ← plain-text, нет структуры
jina_url = f"https://r.jina.ai/{url}"  # ← URL в path — корректно
# Нет: X-Retain-Images, X-Retain-Links, X-Remove-Overlay, X-Md-Heading-Style
```

Текущие проблемы пайплайна, решаемые данной задачей:
1. **Шум в контенте** — изображения, навигация, сайдбары, комментарии, footer загрязняют LLM-контекст.
2. **Избыточный объём** — весь текст страницы без фокуса на запросе ведёт к перегрузке контекста.
3. **Нет языковой фильтрации** — поиск возвращает страницы на нерелевантных языках.
4. **Нет управления форматом Markdown** — заголовки в setext-стиле нечитабельны, ссылки inline засоряют текст.
5. **Нет управления количеством результатов поиска** — `s.jina.ai` возвращает дефолтное число без `num`.
6. **Динамический контент не ждётся** — Jina возвращает страницу до загрузки JS-контента.
7. **Поисковой движок не задан** — Jina использует не самый качественный движок по умолчанию.
8. **Кириллица не изолирована** — запросы на русском возвращают смешанную языковую выдачу.

---

## Задача

Рефакторинг модулей `jina_reader.py` и `search_router.py` для максимально чистой и сигнальной доставки контента в LLM-контекст, используя нативные возможности Jina API без сторонних зависимостей.

---

## Детальные требования

### 1. Рефакторинг `app/modules/jina_reader.py` — Jina Reader (`r.jina.ai`)

#### 1.1. Конфигурация через переменные окружения (всё — только через ENV)

Добавить следующие переменные окружения с разумными дефолтами:

```
JINA_API_KEY              — токен авторизации (уже есть)
JINA_MAX_CHARS            — лимит символов (уже есть, default: 20000)
JINA_TIMEOUT_SEC          — таймаут (уже есть, default: 15.0)
JINA_CONCURRENCY          — параллелизм (уже есть, default: 4)
JINA_REMOVE_OVERLAY       — убирать overlay/cookie-баннеры (default: "true")
JINA_TOKEN_BUDGET         — лимит токенов на ответ, если нужна жёсткая обрезка на стороне Jina (default: "")
JINA_LOCALE               — локаль браузера для рендеринга страниц (default: "")
JINA_RESPOND_TIMING       — момент ответа Jina (default: "network-idle")
JINA_REMOVE_SELECTOR      — CSS-селекторы удаляемых элементов (default: см. ниже)
```

#### 1.2. Заголовки запроса к `r.jina.ai`

Сформировать оптимальный набор заголовков и параметров для Reader:

| Заголовок | Значение | Обоснование |
|---|---|---|
| `Accept` | `text/markdown` | Plain-текст Markdown — быстро, без оверхеда JSON-парсинга; структура не нужна, нам важен текст |
| `X-Retain-Images` | `none` | Изображения — шум для LLM-контекста, не несут семантики |
| `X-Retain-Links` | `none` | Убираем inline-ссылки `[text](url)` — остаётся чистый текст |
| `X-Remove-Overlay` | `true` | Удалять cookie-баннеры и поп-апы |
| `X-Remove-Selector` | `header, footer, nav, aside, .sidebar, .comments, #comments, .advertisement, .nav, .menu` | **Удаляем шаблонные блоки страницы до конвертации в Markdown** — навигация, комментарии, реклама не попадают в контекст |
| `X-Md-Heading-Style` | `atx` | Заголовки `# H1` / `## H2` — читаемые для LLM, не setext-подчёркивания |
| `X-Md-Link-Style` | `discarded` | Ссылки полностью выбрасываем из Markdown, только текст |
| `Authorization` | `Bearer {JINA_API_KEY}` | Если ключ задан |
| `X-Token-Budget` | `{JINA_TOKEN_BUDGET}` | Если `JINA_TOKEN_BUDGET` не пуст |
| `X-Locale` | `{JINA_LOCALE}` | Если `JINA_LOCALE` не пуст |

> **Решение конфликта Accept:** `task_013-0` предлагает `text/markdown`, моя первая версия — `application/json`. Выбираем **`text/markdown`**: Reader возвращает контент уже очищенным через Turndown, нам не нужен meta-объект — только текст. JSON-парсинг добавляет сложность без реальной пользы для текущего пайплайна.

#### 1.2.1. Query-параметр `respondTiming`

Добавить к URL Reader параметр `respondTiming` (из ENV `JINA_RESPOND_TIMING`, default `network-idle`):

```python
respond_timing = os.environ.get("JINA_RESPOND_TIMING", "network-idle")
jina_url = f"https://r.jina.ai/{url}?respondTiming={respond_timing}"
```

**Почему `network-idle`:** ждёт полной загрузки страницы включая все XHR/fetch-запросы. Критично для страниц с lazy-load контентом, SPA-приложений, новостных сайтов с подгружаемым телом статьи.

**Допустимые значения** (из OpenAPI): `html`, `visible-content`, `mutation-idle`, `resource-idle`, `media-idle`, `network-idle`.

> **Предупреждение:** `network-idle` увеличивает latency. Если `JINA_TIMEOUT_SEC` мал (< 20s) — можно получать таймауты. Рекомендуемое значение `JINA_TIMEOUT_SEC=25.0` при использовании `network-idle`.

#### 1.2.2. Заголовок `X-Remove-Selector` — детальнее

Дефолтное значение переменной `JINA_REMOVE_SELECTOR`:
```
header, footer, nav, aside, .sidebar, .comments, #comments, .advertisement, .nav, .menu
```

Передавать как заголовок `X-Remove-Selector`. Jina применяет CSS-селекторы **до конвертации HTML → Markdown**, что радикально сокращает «мусор» в финальном тексте. Комментарии под статьей могут содержать тысячи токенов нерелевантного текста.

#### 1.3. Парсинг ответа

При использовании `Accept: text/markdown`:
- Ответ — чистый Markdown-текст (`resp.text()`)
- Без JSON-парсинга — меньше точек отказа
- Передавать в `truncate_content` как раньше

#### 1.4. Сигнатура функций — без изменений

Публичный API модуля (`fetch_url`, `fetch_all`) должен остаться совместимым:
- `fetch_url(session, url) -> Optional[str]` — возвращает чистый Markdown-текст или `None`
- `fetch_all(urls) -> Dict[str, Optional[str]]` — без изменений

Внутри `fetch_url` можно добавить внутренний возврат `tuple[str, Optional[str]]` с title для последующего использования через отдельный `fetch_url_with_meta()`, если потребуется в будущих задачах. *Но в рамках этой задачи публичный контракт не меняется.*

---

### 2. Рефакторинг `_search_jina` в активном поисковом модуле

> **Цель:** обновить `_search_jina` в том файле, который реально используется в пайплайне (`execution_engine.py` и/или `search_router.py` — проверить импорты в `main.py`).

#### 2.1. Конфигурация через ENV

```
JINA_SEARCH_NUM_RESULTS   — количество результатов поиска (default: "5", max: 20)
JINA_SEARCH_LOCALE        — язык результатов (ISO 639-1, например "ru"), default: ""
JINA_SEARCH_COUNTRY       — страна поиска (ISO 3166-1 alpha-2, например "ru"), default: ""
JINA_SEARCH_NO_FIX_PHRASE — отключить автоисправление запроса (default: "true")
```

#### 2.2. Формат URL — ВАЖНО: запрос через path

По документации `s.jina.ai` поддерживает два варианта:
- `GET /s.jina.ai/{q}` — запрос в path (текущий, рабочий)
- `GET /s.jina.ai/search?q=...` — запрос в query-параметре

**Оставить текущий формат `f"https://s.jina.ai/{query}"`** — он корректен. Дополнительные параметры (`num`, `hl`, `gl`, `nfpr`) передавать через **query-параметры** рядом:

```python
import urllib.parse

params = {}
num = int(os.environ.get("JINA_SEARCH_NUM_RESULTS", "5"))
params["num"] = num

locale = os.environ.get("JINA_SEARCH_LOCALE", "")
if locale:
    params["hl"] = locale

country = os.environ.get("JINA_SEARCH_COUNTRY", "")
if country:
    params["gl"] = country

nfpr = os.environ.get("JINA_SEARCH_NO_FIX_PHRASE", "true").lower() == "true"
if nfpr:
    params["nfpr"] = "true"

# URL: https://s.jina.ai/{encoded_query}?num=5&hl=ru&nfpr=true
encoded_query = urllib.parse.quote(query, safe="")
url = f"https://s.jina.ai/{encoded_query}"
```

> **Примечание:** Текущий код НЕ кодирует query через `urllib.parse.quote`. Кириллические запросы и спецсимволы могут ломаться. Добавить кодирование обязательно.

#### 2.3. Заголовки запроса к `s.jina.ai`

| Заголовок | Значение | Обоснование |
|---|---|---|
| `Accept` | `application/json` | Уже есть — оставить |
| `X-Engine` | `google` | **Переключение на Google-поиск** — наиболее качественная выдача по сравнению с дефолтными движками Jina. Значения: `google`, `bing`, `reader`. Из ENV: `JINA_SEARCH_ENGINE` (default: `"google"`) |
| `X-Retain-Images` | `none` | Не нужны изображения в поисковой выдаче |
| `X-Retain-Links` | `none` | Убираем лишние ссылки из сниппетов — чище snippet-текст |
| `Authorization` | `Bearer {JINA_API_KEY}` | Уже есть — оставить |

#### 2.4. Параметры запроса к `s.jina.ai`

Передавать через query-параметры:

| Параметр | Значение | Обоснование |
|---|---|---|
| `num` | `JINA_SEARCH_NUM_RESULTS` (default 5) | Контроль объёма выдачи; начинать с 5, достаточно для первого прохода |
| `hl` | `JINA_SEARCH_LOCALE` если задан | Язык интерфейса поиска (ISO 639-1) |
| `gl` | `JINA_SEARCH_COUNTRY` если задан | Страна поиска — географическая релевантность |
| `nfpr` | `true` | Отключить автоисправление запроса (No Fix Phrase Results) — точность важнее |

> **Важно:** параметры `hl` и `gl` включать только если соответствующие ENV не пусты — иначе не передавать вовсе.

#### 2.5. Автоматическое добавление `lang:ru` для кириллических запросов

> **ОТМЕНЕНО:** Данное требование признано избыточным и прибивающим логику жестко к движку `google`. Автоматическое добавление `lang:ru` реализовывать не нужно (запросы должны уходить "как есть").

#### 2.4. Анти-шумовые фильтры на стороне клиента

После получения результатов от `s.jina.ai` применить фильтрацию URL перед передачей в `r.jina.ai`:

- Исключать URL с расширениями `.pdf`, `.doc`, `.docx`, `.xls`, `.ppt` (если нет спец. задачи на документы)
- Исключать URL социальных сетей и агрегаторов без контента: `twitter.com`, `x.com`, `facebook.com`, `instagram.com`, `t.me`, `vk.com` — они не парсятся через Jina Reader
- Фильтр применять через ENV-переменную `JINA_SEARCH_EXCLUDE_DOMAINS` (список через запятую, default пустой — только жёсткий список соцсетей)

---

### 3. Улучшение детектора заблокированного контента

Текущая функция `is_blocked_content` — expand:

```python
BLOCKED_PHRASES = [
    "Just a moment",
    "Checking your browser", 
    "requires a subscription",
    "Access denied",
    "Enable JavaScript",
    "403 Forbidden",
    "Cloudflare",
    "This content is for subscribers",
    "Please enable cookies",
    "verify you are human",
    "429 Too Many Requests",
]
```

Добавить также:
- Минимальная длина контента: `len(text) < 200` вместо `< 100` (100 байт — слишком мало даже для заглушки)
- Отношение слов к общему числу символов: если среднее слово > 15 символов (признак бинарного мусора) — считать заблокированным

---

### 4. Метрики и логирование

В каждом successful `fetch_url`:
```
logger.info(f"Jina Reader: {url} → {len(content)} chars extracted")
```

При фильтрации:
```
logger.debug(f"Jina Search: excluded {url} (domain filter)")
```

Уровни логирования:
- `INFO` — успешные операции
- `WARNING` — soft failures (timeout, blocked content)  
- `ERROR` — неожиданные исключения

---

## Файлы для изменения

1. **`app/modules/jina_reader.py`** — пункты 1.1 – 1.3 и раздел 3
2. **`app/modules/execution_engine.py`** — пункты 2.1 – 2.5
3. **`app/modules/search_router.py`** — пункты 2.1 – 2.5 аналогично, если файл используется в пайплайне
4. **`app/main.py`** — **только** значение таймаута (см. ниже)

> **Шаг 0 перед кодированием:** проверить `app/main.py` — что именно импортируется: `execution_engine` или `search_router`. Если `search_router.py` уже не используется — обновить только `execution_engine.py`.

### Изменение в `app/main.py`

Найти переменную глобального таймаута (предположительно `GLOBAL_TIMEOUT_SEC` или аналог) и убедиться, что она составляет **не менее 200.0 секунд**:

```python
# Было:
GLOBAL_TIMEOUT_SEC = float(os.environ.get("GLOBAL_TIMEOUT_SEC", "120.0"))

# Должно быть (увеличить дефолт):
GLOBAL_TIMEOUT_SEC = float(os.environ.get("GLOBAL_TIMEOUT_SEC", "200.0"))
```

**Почему 200s:** при использовании `respondTiming=network-idle` каждый запрос к Reader может занять до 15-25 секунд. При 2 итерациях по 5 URL параллельно — теоретический максимум ~50s, но на практике sequential-участки пайплайна (snippet_evaluator, ai_judge) добавляют ещё ~30-60s. 120s может не хватить для сложных запросов второй итерации.

## Файлы только для чтения (не трогать)

- `app/core/llm.py` — абстракция LLM
- `app/modules/ai_judge.py` — Судья/Куратор
- `app/modules/snippet_evaluator.py` — оценщик сниппетов

---

## Архитектурные ограничения (из GEMINI.md)

- Все параметры — только через переменные окружения, без хардкода URL, ключей или таймаутов
- Нет глобальных переменных состояния
- Ни одна ошибка не должна обрушить пайплайн (graceful degradation)
- Прямой импорт SDK провайдеров в бизнес-логике запрещён

---

## Критерии качества

После выполнения задачи:

1. Ответ Jina Reader содержит **только текст** — без `![image]()`, без `[link](url)` шума, без навигации и комментариев
2. Заголовки в Markdown используют ATX-стиль (`# Title`)
3. Поиск возвращает управляемое кол-во результатов (не более `JINA_SEARCH_NUM_RESULTS`)
4. URL соцсетей автоматически исключаются из очереди на скачивание
5. Кириллические запросы автоматически получают оператор `lang:ru` — только русскоязычные результаты
6. Поисковой движок — Google (`X-Engine: google`) — наиболее качественная выдача
7. Reader ждёт загрузки динамического контента (`respondTiming=network-idle`)
8. Все параметры управляются через ENV — можно конфигурировать без перекомпиляции
9. Функция `fetch_all` по-прежнему возвращает `Dict[str, Optional[str]]` — обратная совместимость сохранена
