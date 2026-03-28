Кардинальное упрощение архитектуры пайплайна в app/main.py. Мы отказываемся от предварительного расширения запросов (query expansion) на первой итерации. Пусть первичный поиск идет точно по запросу пользователя, а если данных не хватит — Судья сам сгенерирует новые запросы для второй итерации.

Пожалуйста, обнови app/main.py:

1. Отключение Планировщика на старте:
Найди этот блок в функции run_research_pipeline:
Python

if current_queries is None:
    current_queries = await expand_query(query, goal)

Замени его на:
Python

if current_queries is None:
    current_queries = [query]
    logger.info(f"Iteration 1: Using exact user query: {current_queries}")

Удали импорт expand_query в начале файла, этот модуль больше не нужен для старта.

2. Отключение Harvester (устранение спама):
Если не используется поиск через searxng, то можно отключить harvester.
Просто не запускать его!

Вноси изменения только в файл app/main.py.