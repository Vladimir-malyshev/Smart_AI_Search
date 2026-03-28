from duckduckgo_search import DDGS
import json

def test():
    backends = ["api", "html", "lite"]
    q = "Capital of Nigeria"
    print(f"[*] Query: {q}")
    
    with DDGS() as ddgs:
        for backend in backends:
            print(f"[*] Пробуем backend='{backend}'...", end=" ")
            try:
                results = list(ddgs.text(q, max_results=3, region="wt-wt", backend=backend))
                print(f"[+] Найдено {len(results)} результатов")
                if results and len(results) > 0:
                    print(json.dumps(results[0], indent=2, ensure_ascii=False))
                    break
            except Exception as e:
                print(f"[!] Ошибка: {e}")

if __name__ == "__main__":
    test()
