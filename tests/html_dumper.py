import asyncio
import aiohttp
import os

# Список целей для тестирования
TARGETS = [
    {"name": "searxng_site", "url": "https://searxng.site/searxng/search"},
    {"name": "rhscz_eu", "url": "https://search.rhscz.eu/search"}
]

QUERY = "столица Нигерии"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
    "Origin": "null",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1"
}

async def fetch_node(session, name, url):
    print(f"[*] Проверка {name} ({url})...")
    data = {
        "q": QUERY,
        "language": "all",
        "categories": "general"
    }
    
    try:
        async with session.post(url, data=data, timeout=15) as response:
            print(f"[{name}] Статус: {response.status}")
            if response.status == 200:
                html = await response.text()
                filename = f"tests/raw_{name}.html"
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(html)
                print(f"[{name}] Сохранено: {filename} ({len(html)} байт)")
                
                # Быстрая проверка на наличие результатов в HTML
                if "result-default" in html or "article" in html:
                    print(f"[{name}] ВАЖНО: Кажется, результаты найдены!")
                else:
                    print(f"[{name}] ПРЕДУПРЕЖДЕНИЕ: В выдаче не найдено блоков результатов.")
            else:
                print(f"[{name}] Ошибка HTTP {response.status}")
    except Exception as e:
        print(f"[{name}] Ошибка: {e}")

async def main():
    os.makedirs("tests", exist_ok=True)
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        tasks = [fetch_node(session, t["name"], t["url"]) for t in TARGETS]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
