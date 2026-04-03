Задача: Интеграция Tavily Search API в движок поиска

Нам необходимо заменить Jina Search на Tavily, реализовав функцию-заглушку в поисковом движке.

Пожалуйста, обнови файл app/modules/execution_engine.py:

1. Реализация _search_tavily
Найди функцию _search_tavily и замени её код на полноценный асинхронный вызов к REST API Tavily.
Логика должна быть следующей:

    - Считать ключ TAVILY_API_KEY из os.environ. Если ключа нет, вывести logger.error и вернуть пустой список.

    - Прочитать лимит из os.environ.get("SEARCH_NUM_RESULTS", "5").

    - Сделать POST запрос через aiohttp.ClientSession() на URL https://api.tavily.com/search.

    - Тело запроса (JSON):
    ```json
    {
        "api_key": "tavily_api_key",
        "query": "query",
        "max_results": "num_results",
        "search_depth": "basic",
        "include_answer": false,
        "include_images": false,
        "include_raw_content": false
    }
    ```

    - Разобрать ответ. Из массива results извлечь title, url и content (в API Tavily сниппет лежит в поле content).

    - Сформировать и вернуть список объектов SearchSnippet(title=..., url=..., snippet=...).

    - Обернуть вызов в блок try/except для перехвата сетевых ошибок и добавить замеры времени через time.monotonic() с логированием (INFO), аналогично тому, как это сделано в _search_jina.

2. Обновление execute_search
В функции execute_search измени значение провайдера по умолчанию, если оно не задано в ENV:
`provider = os.environ.get("SEARCH_PROVIDER", "tavily").lower()`

Изменяй только файл execution_engine.py.
