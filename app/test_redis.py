import redis

# Подключаемся так, будто Redis стоит прямо на твоем компьютере
r = redis.Redis(host='localhost', port=6379, db=0)

try:
    if r.ping():
        print("✅ Успешно! Туннель работает, Redis отвечает.")
except Exception as e:
    print(f"❌ Ошибка подключения: {e}")