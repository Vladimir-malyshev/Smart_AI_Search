import os
import time
import json
from duckduckgo_search import DDGS

QUERIES = [
    "Погода в Москве сейчас",
    "Столица Нигерии",
    "Текущая цена Bitcoin и Ethereum",
    "Кто основал группу Black Sabbath",
    "Актуальная стабильная версия Python",
    "Когда прилетают дрозды в Тульской области",
    "Что такое первая космическая скорость",
    "Алгоритмы продвижения в TenChat 2026",
    "Прогноз цен на нефть марки Brent на квартал",
    "Лучшие пачки героев для Гранд Арены в Hero Wars",
    "Обзор новостей ИИ за неделю",
    "Что сейчас происходит вокруг Ирана",
    "Рейтинг роботов-пылесосов 2026",
    "Сравнение стоимости разработки RAG",
    "Лучшие open-source векторные базы данных"
]

RESULTS_DIR = "tests/ddg_results"
DELAY = 3  # Задержка 3 секунды

def run_tester():
    os.makedirs(RESULTS_DIR, exist_ok=True)
    
    print(f"[*] Начинаю тест DuckDuckGo для {len(QUERIES)} запросов.")
    print(f"[*] Интервал: {DELAY} сек. Результаты в: {RESULTS_DIR}")
    print("-" * 50)

    with DDGS() as ddgs:
        for i, query in enumerate(QUERIES, 1):
            filename = f"{RESULTS_DIR}/query_{i:02d}.json"
            print(f"[{i:02d}/{len(QUERIES)}] Запрос: '{query}'...", end=" ", flush=True)
            
            try:
                # Получаем топ-5 результатов
                results = list(ddgs.text(query, max_results=5))
                
                if not results:
                    print("ПУСТО (Нет результатов)")
                else:
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump({
                            "query": query,
                            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "results": results
                        }, f, ensure_ascii=False, indent=2)
                    print(f"OK ({len(results)} сниппетов)")
                
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "ratelimit" in error_msg:
                    print("!!! ТАЙМАУТ/БАН (HTTP 429)")
                elif "captcha" in error_msg:
                    print("!!! КАПЧА (CAPTCHA DETECTED)")
                else:
                    print(f"!!! ОШИБКА: {e}")
            
            if i < len(QUERIES):
                time.sleep(DELAY)

    print("-" * 50)
    print("[*] Тест завершен.")

if __name__ == "__main__":
    run_tester()
