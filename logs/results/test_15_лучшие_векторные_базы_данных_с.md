# Query: Лучшие векторные базы данных с открытым исходным кодом для локального RAG
# Goal: Сравнить Chroma, PGvector и другие аналоги по производительности, удобству интеграции с Python и потреблению памяти

### Источник: https://habr.com/ru/articles/961088/
Title: Выбираем векторную БД для AI-агентов и RAG: большой обзор баз данных и поиск смысла

URL Source: https://habr.com/ru/articles/961088/

Published Time: 2025-10-29T11:18:57+03:00

Markdown Content:
В этой статье я сделал обзор основных векторных баз данных: Milvus, Qdrant, Weaviate, ChromaDB, pgvector, Redis, pgvectorscale, LanceDB, ClickHouse, Vespa, Marqo, ElasticSearch.

Если вы запутались в разнообразии векторных баз данных или хочется верхнеуровнево понимать как они устроены, чем отличаются и для чего вообще нужны, то эта статья будет очень полезна. Мы пошагово соберем все ожидания от векторных БД, посмотрим бенчмарки, а затем попробуем собрать все воедино.

![Image 1: А ты выбрал базу для RAG или AI-агентов?](https://habrastorage.org/r/w1560/getpro/habr/upload_files/0e0/7b4/837/0e07b48378a8f954cbe31aa26f3ba18d.jpeg)

А ты выбрал базу для RAG или AI-агентов?

Звучит немного тавталогично, но на самом деле выбор подходящей векторной базы начинается даже до момента непосредственно самого выбора базы данных. Потому что очень важно не только выбрать ГДЕ хранить, но и ЧТО. Векторные БД хранят вектора (сюрприз), но сами вектора — явление широкое и потому про них стоит сделать важное вступление.

## Поиски смысла и вектора (эмбединги)

_Да, если вы все это хорошо знаете, то можно переходить непосредственно к бенчмаркам, но эта часть_—_супер важная._

**Эмбединги (embeddings)** — это числовые векторные представления данных (текста, изображений, аудио, кода, видео и чего угодно), полученные с помощью специализированной модельки, которая называется энкодером (или эмбеддером). Такая модель — фактический «запаковщик смысла»: она преобразует любые входные данные в массив чисел фиксированной длины (вектор), где семантически похожие объекты располагаются близко друг к другу в многомерном пространстве.

_Пример: фраза_«_клиент просил вернуть деньги_»_преобразуется в условный вектор [0.23, -0.15, 0.89, ...], фраза_«_заказчик хотел получить возврат средств_»_в вектор [0.21, -0.14, 0.87, ...]. Косинусное_ сходство _между векторами_—_0.95, то есть обе фразы очень близки по смыслу, хотя и написаны совершенно разными словами. Если мы возьмем_«_котик прыгает по столу_»_, то будет другой вектор, маленькое косинусное_ сходство _и, как следствие, очень далекий смысл от первых двух._

Эмбединг = смысл. Но все мы работаем с разными смыслами и это — большая проблема. Понятие смысла субъективно и сильно зависит от предметной области. Даже под одними и теми же словами можно подразумевать разное: реверс (двигателя, монеты или инжиниринг?), артефакт (искажение или объект?) или же относиться к самым разным индустриям (например, слово «протокол» — оно про IT, медицину или криминалистику?).

Поэтому эмбединги, а точнее, модели которые их генерируют, можно условно разделить на две большие группы: общего назначения (обученные на всем корпусе языка) или же специализированные. Конечно, специализированные будут работать лучше: если мы делаем медицинский RAG, то «_аспирин_» должен скорее ассоциироваться с «_циклооксигеназа-1_», чем с просто головной болью. Но специализированные модели — недешевое во всех смыслах удовольствие.

У эмбедингов есть размерность (к ней мы еще вернемся) и, если упростить, чем она больше, тем больше информации в него зашито, но и тем больше памяти для этого требуется.

И векторные базы данных предназначены для хранения этих самых эмбедингов. Но не только хранения, но еще и различных операций.

Давайте сначала поговорим про само хранение.

## Хранение эмбедингов в БД

Эмбединг — это сжатое числовое представление чего угодно, например, кусочка текста или видео. Мы оперируем этими векторами потому что над ними удобно проделывать математические операции, но в конечном итоге нам нужны исходные данные. Например, мы по векторам уже нашли 10 похожих видео на наше, но мы не можем отдать эти вектора клиенту, нам нужны именно видосики.

Поэтому помимо самого хранения эмбединга нужно хранить мета-информацию — кем загружно, категорию, название, сам файл и так далее. И тут есть два пути:

**1. Хранение в самой векторной БД (встроенное)**

```
{
  "id": "doc_123",
  "vector": [0.1, 0.2, ...],  // 768 чисел
  "metadata": {
    "text": "Полный текст документа или чанка",  // ← оригинал здесь
    "title": "Название",
    "date": "2025-07-05",
    "category": "tech"
  }
}
```
```

Из плюсов — одна система, одна точка отказа, атомарность операций, минусы — векторные БД в первую очередь оптимизированы под вектора и хранить большое количество мета-информации будет дороже по I/O и латенси. Такое уместно в небольших RAG-системах (<1M документов), прототипы или системы с короткими чанками (<1000 условных токенов)

**2. Внешнее хранилище + reference**

Векторная БД хранит только эмбединги, ID и опционально — краткие метаданные, а все оригиналы — в привычной базе. Из плюсов здесь то, что каждый инструмент делает свою работу, из минусов — нужна синхронизация.

Есть еще один частный способ в виде гибридного решения: вектор в PostgreSQL, blob в S3.

С хранением — плюс-минус разобрались, теперь — с операциями.

## Операции над эмбедингами

Основная операция — **векторный поиск** (ANN search): «найди K наиболее похожих векторов на запрос». Это _не точное_ совпадение как в SQL (`WHERE id = 5`), а поиск по близости — топ-10, топ-100 самых семантически близких объектов. Результат возвращается по мере близости/расстояния, отсортированный по релевантности.

**CRUD-операции**: Insert (добавить новые векторы), Update (обновить метаданные, сам вектор обычно не меняется), Delete (удалить), Upsert (обновить или создать, если не существует). При вставке вектор автоматически добавляется в индекс для быстрого поиска. Про индекс мы еще поговорим.

**Фильтрация по метаданным**: векторный поиск + условия на метаданные в одном запросе. Например: «найди похожие документы, но только category='tech' AND date >= 2025". Критически важно, чтобы фильтры применялись **во время** поиска (pre-filtering), а не после (post-filtering), иначе теряется точность.

**Гибридный поиск**: например, комбинация векторного поиска + полнотекствого (BM25) + фильтрация метаданных. Векторный находит по смыслу, BM25 усиливает точные ключевые слова, фильтры отсекают по метаданным.

**Batch-операции**: массовая загрузка тысяч/миллионов векторов за раз (bulk insert), массовое удаление, переиндексация. Критично для первоначальной загрузки больших датасетов или периодической синхронизации.

**Реиндексация**: пересоздание индекса с другими параметрами (тип индекса, метрики сходства/расстояния, квантизация) без перезагрузки оригинальных векторов. Позволяет экспериментировать с настройками производительности.

Все эти операции должны работать быстро даже на миллионах векторов — это главное отличие специализированных векторных БД от «просто хранилища массивов чисел».

### Что общего у всех векторных БД

Базовая архитектура векторных БД похожа на реляционные, но с векторной спецификой:

*   **Коллекции** (collections/tables) — аналог таблиц в SQL, каждая коллекция хранит векторы одной размерности.

*   **Документы/точки** (points/documents) — аналог строк. Каждый документ содержит: вектор (массив чисел) + метаданные (JSON-подобная структура с категориями, датами, тегами и тд)

*   **Индексы** — обязательная структура для быстрого поиска, про них мы поговорим

*   **Метрики близости вместо JOIN'ов.** Векторные БД используют математические меры для поиска: меры сходства (больше = лучше) — Cosine Similarity и Dot Product, и меры расстояния (меньше = лучше) — L2/Euclidean. Метрика фиксируется при создании коллекции — смена требует переиндексации

*   **Векторный поиск** вместо SELECT. Базовая операция: «найди K ближайших векторов к запросу» (вместо «выбери строки WHERE условие»). Результат — отсортированный список по similarity score

Отличие от реляционных БД: вместо точного поиска (WHERE id = 5) — приблизительный поиск (топ-10 похожих). Вместо нормализации (связи между таблицами) — денормализация (всё в одном документе). Многие векторные БД ориентированы на масштабируемость, и поведение согласованности может быть менее строгим, чем у классических реляционных БД.

## Индексы в векторных БД

Я упомянул слово «индекс» — они для векторов бывают разные, и от выбора индекса зависит скорость поиска, потребление памяти и точность результатов:

*   **HNSW (Hierarchical Navigable Small World)** — многослойный граф навигации, золотой стандарт для скорости и точности

*   **IVF (Inverted File Index)** — семейство индексов, разбивает пространство на кластеры, быстрая индексация и работа с диском

*   **DiskANN** — индекс для SSD (NVMe), позволяет работать с терабайтами векторов при минимальной RAM

*   **Flat (Brute Force)** — точный поиск без индекса, сравнение со всеми векторами, используется для малых датасетов (<100K)

*   **Product Quantization (PQ)** — сжимающий индекс, экономит память в 8-32 раза за счет небольшой потери точности

Каждая векторная БД не просто поддерживает свой набор индексов, а _оптимизирует их под свое хранилище и движок_ — например, Qdrant модифицировал HNSW для лучшей работы с фильтрами, а Timescale создал свой StreamingDiskANN специально под PostgreSQL. Эти оптимизации дают преимущество в 20-40% по производительности против универсальных реализаций.

Квантизация индексов — еще один способ оптимизации. Векторы хранятся в float32 (4 байта на число), а квантизация сжимает их до int8 или даже битов. БД со встроенной квантизацией (Qdrant, Milvus, pgvectorscale) позволяют экспериментировать: загрузили векторы один раз (они хранятся как есть) → пересоздаем индекс с разной квантизацией → сравниваем память/скорость/точность. Оптимизированные под движок версии могут работать гораздо лучше самописных — например, Binary Quantization от Qdrant с oversampling _по их заявлениям_ дает recall 95%+ против 70-80% у наивной реализации.

Это было перечисление, скажем так, физических операций и оптимизаций в них, а теперь попробуем составить требования именно под RAG и агентов.

## Операции с БД в RAG и AI-агентах

**RAG**

Суть RAG — это поиск, а «R» в аббревиатуре в сто раз важнее «G». RAG так хорошо зашел не потому, что это новая технология, а потом что LLM умеют разрозненную информацию единообразно подать.

Процесс: документы разбиваются на фрагменты, каждый преобразуется в эмбединг; запрос пользователя векторизуется и ищутся похожие фрагменты; найденные фрагменты передаются LLM как контекст.

**Задачи векторной БД в RAG:**семантический поиск (основная задача), фильтрация метаданных (например, дата, автор, тип документа), гибридный поиск (векторный + BM25), переранжирование результатов (reranking), работа с большим объемом документов, инкрементальная индексация.

**AI-Агенты**

Агенты используют векторные БД иначе: долгосрочная память (история взаимодействий), планирование действий (поиск примеров из прошлого) и динамический контекст.

Их специфические требования:

*   Быстрые вставки (агенты часто пополняют базу)

*   Версионирование (отслеживание изменений знаний)

*   Множественные коллекции (разные типы памяти: эпизодическая, семантическая, процедурная)

*   Транзакционность для согласованности

Ну, кажется, можно переходить к кандидатам.

## Бенчмаркинг векторных БД и VectorDBBench

Когда я вообще делал первый подход к снаряду выбора векторной БД, то мне показалось уместным пойти посмотреть публичные бенчмарки. Но в публичных бенчмарках от самих разработчиков часто оказывалось так, что их решение — лучшее. А значит у нас есть примерно 15 лучших баз данных. _[можно выбрать любую из них_—_расходимся, хаха]_

В целом, скорее всего, там никто не врет, но у всех разные данные, разное железо и немного разные способы подсчета.

А если в публичные бенчи мы не верим, значит надо делать свой, ведь других-то у меня для вас нет. Или есть? В бездонных просторах ресерчей я нашел инструмент, который придумали разработчики одной популярной векторной БД, и который подхватило векторное коммьюнити. Имя ему — [VectorDBBench](https://github.com/zilliztech/VectorDBBench). И это очень крутая штука, которая позволяет сделать фиксированные тесты не на какой-либо там синтетике.

Ставится себе на локалку и выглядит вот так:

![Image 2](https://habrastorage.org/r/w1560/getpro/habr/upload_files/303/3eb/d8d/3033ebd8dd9432b46463140b855faba6.png)
Круто? Круто. Выбираем БД, выбираем датасет (можно свой или публичный), запускаем тест и получаем все классные метрички типа QPS, latency (P50/P95/P99), recall, indexing time.

Инструмент открытый, методология открытая, если уже есть данные и встает вопрос выбора векторной БД, то прогнать всевозможные тесты здесь — правильный и скорее обязательный путь.

Все очень классно сделано — то, что называется «люди подумали». Единственное, по их публичной стате в топ почти всего часто влетает ZilizCloud (их протюненная облачная версия Milvus), что, возможно, намекает на то что они все же под бенчмарк оптимизировались. Но наличие официальных контрибьюторов из других БД доверие все же внушает, плюс, опять же, все тесты надо делать на своей инфре, своих задачах и своих данных — только так оно будет что-то реально показывать.

![Image 3: Streaming Performance](https://habrastorage.org/r/w1560/getpro/habr/upload_files/f36/b5f/598/f36b5f598269f4232b39ce597f377132.png)

Streaming Performance

![Image 4: Performance vs Recall](https://habrastorage.org/r/w1560/getpro/habr/upload_files/4fb/794/d60/4fb794d601c70e686c16985507d6017a.png)

Performance vs Recall

#### Типы тестов в VectorDBBench

1.   **Search Performance Test** — чистый векторный поиск без фильтров. Базовая метрика для всех БД

2.   **Int-Filter Search Performance Test** — векторный поиск + числовые фильтры (year >= 2020, price < 1000), показывает деградацию при фильтрации

3.   **New-Int-Filter Search Performance Test** — сложные комбинации числовых фильтров, имитирует production-запросы

4.   **Label-Filter Search Performance Test** — векторный поиск + категориальные фильтры (category="tech", status="active"), выявляет post-filtering vs pre-filtering

5.   **Capacity Test** — максимальное количество векторов до критической деградации., показывает реальные лимиты масштабируемости

6.   **Streaming Test** — производительность поиска при непрерывной вставке новых данных, критично для систем с постоянными обновлениями

7.   **Custom Search Performance Test** — тестирование на наших данных с нашими паттернами запросов

Максимально рекомендую для серьезных исследование, а мы переходим к самим БД!

## Список векторных БД под микроскопом

Надеюсь, я донес основную идею, что все очень сложно и специфично и сначала нужно декомпозировать задачу, зафиксировать способ получения эмбедингов и именно под это уже выбирать БД. Поэтому пересказывать публичные бенчи смысла нет, а вот пройтись по каждой базе и ее оценить — это правильно.

Продраться сквозь маркетинговые заявления и сравнивания баз между собой на их бенчмарках было непросто, но оно того стоило.

> Здесь стоит учесть, что зафиксировать в моменте все плюсы/минусы, масштабы и сложность — задача крайней сложная, потому что векторные базы — тема горячая и почти все продукты ниже развиваются**очень быстро**. Люди делают бенчмарки, пишут обзоры, а через месяц выходит обновление, которые делает все сделанное устаревшим. Поэтому список и таблицу стоит читать как ориентир и некую точку фиксации развития векторных БД. В описании и таблице _возможны_ локальные неточности, я буду очень рад их исправить.

Да, из списка выброшены все базы, у которых есть vendor-lock (фактически cloud-based), просто потому что в 2025 это очень важный фактор выбора БД.

## 1. Milvus

Философия:

*   Открытая распределенная векторная БД, поддерживает масштабирование кластеров, GPU-ускорение, множество индексов (HNSW, IVF, PQ и др)

*   Спроектирована для управления большими объемами векторов («миллиарды точек») и поддерживает гибридные сценарии

Плюсы:

*   Хорошая масштабируемость (от себя до больших кластеров, распределенность)

*   Поддержка разных режимов индексов и оптимизаций (GPU, диск-индексы)

*   OSS-лицензия Apache 2.0

*   Подходит для серьезных RAG / AI-агентов с большим объемом данных

Минусы:

*   Более высокая сложность настройки и эксплуатации (особенно кластер)

*   Требует серьезного инфраструктурного ресурса при больших нагрузках _(но, с другой стороны, если вы до них доросли, то может оно и ок?)_

*   Может быть оверкилом если объем данных невелик и требования просты

**Идеально для:**Сценариев, когда объём данных велик (сотни миллионов-миллиарды векторов), нужна высокая пропускная способность и гибкость (например, мультимодальные данные, видео/изображения + текст), возможно собственный хостинг, и когда команда готова управлять кластером.

## 2. Qdrant

Философия:

*   OSS-векторная БД с акцентом на payload-фильтры (метаданные) + векторный поиcк

*   Поддержка индексов, фильтрации, гибридных запросов, оптимизаций под реальные приложения

Плюсы:

*   Хороший баланс между производительностью и гибкостью

*   Легкость старта (по сравнению с крупными кластерами)

*   Сильная поддержка фильтрации по метаданным + векторов — важно для RAG

Минусы:

*   Масштабируется, но уступает решениям по very large scale сценариям (например, миллиард+ точек) в плане масштаба или функциональной экосистемы

*   Управление кластером требует усилий

**Идеально для:**проектов сред­него масштаба, где нужен семантический поиск + метаданные-фильтры, например RAG-сценарии, логика агентов (история, память) с числом точек в диапазоне миллионов-десятков миллионов.

## 3. Weaviate

Философия:

*   OSS-векторная БД с «knowledge graph / schema» подходом: позволяет задавать схемы, модули встраивания, гибридный поиск (ключевые слова + векторы)

*   Предлагает GraphQL API + модуль для генерации эмбеддингов внутри (опционально) — упрощает интеграцию

Плюсы:

*   Очень удобно для сложных структур данных, где нужна не просто векторная точка, а богатая схема, связи, категории

*   Гибридный поиск «вектор + ключевые слова» встроен

*   Подходит для RAG/агентов с метаданными и сложными связями

Минусы:

*   Может быть более сложной в настройке, если вы просто хотите «хранить и искать векторы» без схемы

*   При очень больших объёмах и сверхвысоких требованиях по пропускной способности и может уступать специально оптимизированным решениям

*   Возможна избыточность функционала, если требования просты

**Идеально для:**

Сценариев, где данные имеют богатую структуру (например, знания, графы, сложные связи): RAG системы с метаданными, AI-агенты с памятью, где нужна не только «найти похожий фрагмент», но «найти похожий + связанный + в фильтре».

## 4. ChromaDB

Философия:

*   Легкая и удобная векторная БД для прототипов, небольших проектов.

*   Часто используется как стартовое векторное хранилище, меньше фокус на «миллиарды точек», больше на «быстро запустить»

Плюсы:

*   Простота, скорость старта, низкий порог входа

*   Отлично подходит для прототипов, экспериментов, RAG PoC

*   Обычно легче интегрировать, меньше инфраструктурной нагрузки

Минусы:

*   Менее производительная или масштабируемая по сравнению с крупными решениями

*   Может не столько подходить для production с десятками миллионов или больше точек, или с высокими требованиями к пропускной способности/латенси

*   Возможны ограничения в функциональности (индексы, масштабирование, enterprise-фичи)

**Идеально для:**

Прототипов, PoC RAG/агентов, стартапов, когда число документов/векторов ещё умеренное (например < 10 м), когда важна скорость разработки, а не максимальная производительность или распределенный кластер.

## 5. pgvector (расширение для PostgreSQL)

Философия:

*   Расширение для PostgreSQL, которое позволяет хранить и искать векторы внутри знакомой реляционной БД (SQL) среды

*   Подходит когда уже используется PostgreSQL и хочется добавить семантический поиск без отдельной системы

Плюсы:

*   Используется уже существующая инфраструктура, знакомая среда

*   Нет необходимости внедрять новую систему, команда может продолжать работать с SQL + векторы

*   Отлично для интеграции структ

[...ТЕКСТ ОБРЕЗАН — достигнут лимит контекста...]

### Источник: https://encore.dev/articles/best-vector-databases
Title: Best Vector Databases in 2026: Complete Comparison Guide

URL Source: https://encore.dev/articles/best-vector-databases

Published Time: 2026-03-09T00:00:00.000Z

Markdown Content:
Every AI feature that works with your own data (semantic search, RAG pipelines, recommendation engines, document classifiers) needs somewhere to store and query vector embeddings. The vector database market has grown from a handful of options to dozens, each with different tradeoffs around performance, operational complexity, cost, and scale.

This guide compares seven vector databases that cover the spectrum: from extending PostgreSQL with an extension to fully managed cloud services to embedded databases that run in-process. The right choice depends on your existing infrastructure, the scale of your workload, and how much operational overhead you're willing to take on.

## [Quick Comparison](https://encore.dev/articles/best-vector-databases#quick-comparison)

| Database | Type | Hosting | Open Source | Best Scale | Standout Feature |
| --- | --- | --- | --- | --- | --- |
| **pgvector** | Postgres extension | Self-hosted / managed Postgres | Yes | Millions | Same DB as your app data |
| **Pinecone** | Managed SaaS | Pinecone cloud | No | Billions | Zero-ops serverless |
| **Qdrant** | Dedicated vector DB | Self-hosted / Qdrant Cloud | Yes (Apache 2.0) | Hundreds of millions | Payload filtering + Rust perf |
| **Weaviate** | Dedicated vector DB | Self-hosted / Weaviate Cloud | Yes (BSD-3) | Hundreds of millions | Built-in vectorization modules |
| **Milvus** | Dedicated vector DB | Self-hosted / Zilliz Cloud | Yes (Apache 2.0) | Billions | GPU-accelerated, enterprise scale |
| **Chroma** | Embedded / client-server | In-process or self-hosted | Yes (Apache 2.0) | Hundreds of thousands | Developer experience, prototyping |
| **LanceDB** | Embedded | In-process (serverless cloud in beta) | Yes (Apache 2.0) | Millions | Zero-copy, columnar storage |

## [pgvector: Best for Teams Already Running Postgres](https://encore.dev/articles/best-vector-databases#pgvector-best-for-teams-already-running-postgres)

[pgvector](https://github.com/pgvector/pgvector) is a PostgreSQL extension that adds a `vector` column type with support for cosine similarity, L2 distance, and inner product operations. It supports both HNSW and IVFFlat indexing.

**Key features:**

*   Vectors and application data in the same table, same transaction
*   Standard SQL for queries, filtering, and joins
*   HNSW and IVFFlat index types
*   Works with every managed Postgres provider (RDS, Cloud SQL, Supabase, Neon)
*   No additional service to deploy, monitor, or pay for

**Best for:**

*   Teams that already run Postgres and want to add vector search without adding infrastructure
*   Workloads under 5 million vectors where query latency is acceptable at 5-50ms
*   Applications where transactional consistency between documents and embeddings matters
*   Complex filtering that benefits from SQL joins and subqueries

**Limitations:**

*   Scales vertically (bigger instance = more vectors in memory). No built-in horizontal scaling for vector indexes.
*   Performance tuning at scale requires Postgres expertise (shared_buffers, work_mem, HNSW parameters).
*   Not designed for workloads above tens of millions of vectors on a single instance.

**Example:**

```
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
  id BIGSERIAL PRIMARY KEY,
  content TEXT NOT NULL,
  embedding vector(1536)
);

CREATE INDEX ON documents USING hnsw (embedding vector_cosine_ops);

-- Similarity search with SQL filtering
SELECT id, content, 1 - (embedding <=> $1) AS similarity
FROM documents
WHERE category = 'engineering'
ORDER BY embedding <=> $1
LIMIT 10;
```

pgvector is the default recommendation for teams that already have Postgres in their stack. It avoids the operational complexity of a second data store and gives you transactional consistency that dedicated vector databases can't match. If you want to try it out, see the [getting started section](https://encore.dev/articles/best-vector-databases#getting-started-with-pgvector) below for a working setup in a few lines of code. For a detailed head-to-head comparison, see [pgvector vs Pinecone](https://encore.dev/articles/pgvector-vs-pinecone).

## [Pinecone: Best Managed Vector Database](https://encore.dev/articles/best-vector-databases#pinecone-best-managed-vector-database)

[Pinecone](https://www.pinecone.io/) is a fully managed vector database offered as a cloud service. You get an API key, create an index, and start querying. No instances to size, no indexes to tune, no infrastructure to manage.

**Key features:**

*   Serverless tier that auto-scales with query volume and data size
*   Namespace isolation for multi-tenant applications
*   Metadata filtering on vector results
*   Supports sparse-dense hybrid search
*   SOC 2 Type II compliance

**Best for:**

*   Teams that want zero operational overhead for vector search
*   Multi-tenant applications at scale where per-tenant isolation matters
*   Workloads at hundreds of millions or billions of vectors
*   Organizations that need managed compliance and SLAs

**Limitations:**

*   Proprietary, closed-source. Your data and indexes are in Pinecone's cloud.
*   Eventually consistent. Writes take time to become searchable.
*   Metadata filtering is limited compared to SQL (no joins, no subqueries).
*   Cost can scale quickly at high query volumes.

**Example:**

```
import { Pinecone } from "@pinecone-database/pinecone";

const pc = new Pinecone({ apiKey: process.env.PINECONE_API_KEY });
const index = pc.index("documents");

// Upsert
await index.upsert([{
  id: "doc-1",
  values: embedding,
  metadata: { category: "engineering" },
}]);

// Query
const results = await index.query({
  vector: queryEmbedding,
  topK: 10,
  filter: { category: { $eq: "engineering" } },
  includeMetadata: true,
});
```

Pinecone is the right choice when you need scale and managed infrastructure above everything else. For a detailed comparison with pgvector, see [pgvector vs Pinecone](https://encore.dev/articles/pgvector-vs-pinecone).

## [Qdrant: Best Open-Source Dedicated Vector Database](https://encore.dev/articles/best-vector-databases#qdrant-best-open-source-dedicated-vector-database)

[Qdrant](https://qdrant.tech/) is an open-source vector database written in Rust. It's designed from the ground up for vector search, with a focus on performance, payload filtering, and a rich query API.

**Key features:**

*   Written in Rust with strong single-node performance
*   Rich payload filtering with indexed fields (numeric, keyword, geo, datetime)
*   Supports quantization (scalar and product) for memory efficiency
*   Distributed mode with sharding and replication
*   Available as self-hosted (Docker) or managed cloud (Qdrant Cloud)

**Best for:**

*   Teams that want a dedicated vector database but prefer open-source
*   Workloads that need complex filtering alongside vector similarity
*   Applications that benefit from Qdrant's quantization for large datasets on limited memory
*   Self-hosted deployments where you control the infrastructure

**Limitations:**

*   Another service to deploy, monitor, and maintain (unless using Qdrant Cloud)
*   Data lives separately from your application database, requires sync logic
*   Distributed mode adds operational complexity
*   Smaller ecosystem and community than Postgres-based solutions

**Example:**

```
import { QdrantClient } from "@qdrant/js-client-rest";

const client = new QdrantClient({ url: "http://localhost:6333" });

// Create collection
await client.createCollection("documents", {
  vectors: { size: 1536, distance: "Cosine" },
});

// Upsert
await client.upsert("documents", {
  points: [{
    id: 1,
    vector: embedding,
    payload: { category: "engineering", date: "2026-03-01" },
  }],
});

// Search with filtering
const results = await client.search("documents", {
  vector: queryEmbedding,
  limit: 10,
  filter: {
    must: [{ key: "category", match: { value: "engineering" } }],
  },
});
```

Qdrant is a strong choice if you need a dedicated vector database and want to stay open-source. If you're using Encore, we have a [tutorial for building semantic search with Qdrant](https://encore.dev/blog/building-semantic-search-qdrant-encore). For a comparison with pgvector, see [pgvector vs Qdrant](https://encore.dev/articles/pgvector-vs-qdrant).

## [Weaviate: Best for Built-in Vectorization](https://encore.dev/articles/best-vector-databases#weaviate-best-for-built-in-vectorization)

[Weaviate](https://weaviate.io/) is an open-source vector database that goes beyond storage and search. It includes built-in modules for generating embeddings, so you can insert raw text and Weaviate handles the vectorization.

**Key features:**

*   Vectorization modules for OpenAI, Cohere, Hugging Face, and more (insert text, get vectors automatically)
*   GraphQL and REST APIs
*   Hybrid search combining vector similarity with BM25 keyword search
*   Multi-tenancy support
*   Available self-hosted or as Weaviate Cloud

**Best for:**

*   Teams that want the database to handle embedding generation
*   Applications that need hybrid search (semantic + keyword) built in
*   Use cases where the GraphQL query API is preferred
*   Rapid prototyping where managing embedding pipelines is overhead

**Limitations:**

*   Vectorization modules add latency and API costs (they call the same embedding APIs you'd call yourself)
*   GraphQL API adds a learning curve compared to SQL or simple REST
*   Resource-heavy for self-hosting (Java-based runtime)
*   Operational complexity increases with modules and multi-tenancy

**Example:**

```
import weaviate from "weaviate-client";

const client = await weaviate.connectToLocal();

// Insert raw text, Weaviate vectorizes it
await client.collections.get("Document").data.insert({
  title: "Vector Search Guide",
  content: "pgvector adds vector search to PostgreSQL...",
});

// Semantic search
const results = await client.collections.get("Document")
  .query.nearText("how does vector search work", { limit: 10 });
```

Weaviate is interesting if you want embedding generation baked into the database. But the vectorization modules are calling the same APIs you'd call in your application code, so the convenience comes with the tradeoff of less control over the embedding pipeline.

## [Milvus: Best for Enterprise Scale](https://encore.dev/articles/best-vector-databases#milvus-best-for-enterprise-scale)

[Milvus](https://milvus.io/) is an open-source vector database designed for large-scale deployments. Its managed version, [Zilliz Cloud](https://zilliz.com/), offers enterprise features and GPU-accelerated search.

**Key features:**

*   GPU-accelerated indexing and search (via Zilliz Cloud)
*   Supports billions of vectors across distributed clusters
*   Multiple index types (IVF, HNSW, DiskANN, GPU indexes)
*   Schema enforcement with typed fields
*   Partition keys for multi-tenant data isolation

**Best for:**

*   Enterprise workloads at billions of vectors
*   Teams that need GPU-accelerated search for low-latency at massive scale
*   Applications requiring multiple index types tuned for different query patterns
*   Organizations with dedicated infrastructure teams

**Limitations:**

*   Complex to self-host. Requires etcd, MinIO (or S3), and message queues in distributed mode
*   Steep learning curve compared to simpler options
*   Overkill for most workloads under millions of vectors
*   Resource-intensive even in standalone mode

**Example:**

```
import { MilvusClient } from "@zilliz/milvus2-sdk-node";

const client = new MilvusClient({ address: "localhost:19530" });

await client.createCollection({
  collection_name: "documents",
  fields: [
    { name: "id", data_type: 5, is_primary_key: true, auto_id: true },
    { name: "embedding", data_type: 101, type_params: { dim: 1536 } },
    { name: "category", data_type: 21, max_length: 256 },
  ],
});

const results = await client.search({
  collection_name: "documents",
  vector: queryEmbedding,
  limit: 10,
});
```

Milvus is the heavy-duty option. If you're processing billions of vectors and need GPU acceleration or advanced indexing, it's built for that. For most teams, it's more infrastructure than the workload requires.

## [Chroma: Best for Prototyping and Local Development](https://encore.dev/articles/best-vector-databases#chroma-best-for-prototyping-and-local-development)

[Chroma](https://www.trychroma.com/) is an open-source embedding database focused on developer experience. It runs in-process (embedded) or as a client-server setup, making it the fastest path from zero to a working vector search.

**Key features:**

*   Embeds directly in your Python or JavaScript process, no server to run
*   Automatic embedding generation with pluggable models
*   Simple API: `add`, `query`, `update`, `delete`
*   Persistent storage to disk
*   Also runs as a standalone server for production

**Best for:**

*   Prototyping and experimentation
*   Local development and testing of AI features
*   Small datasets (thousands to hundreds of thousands of vectors)
*   Educational projects and proof of concepts

**Limitations:**

*   Performance degrades above hundreds of thousands of vectors
*   Limited production deployment story (no managed cloud offering yet)
*   No built-in replication or horizontal scaling
*   JavaScript/TypeScript client is less mature than the Python client

**Example:**

```
import { ChromaClient } from "chromadb";

const client = new ChromaClient();
const collection = await client.createCollection({ name: "documents" });

// Add with auto-generated embeddings
await collection.add({
  ids: ["doc-1"],
  documents: ["pgvector adds vector search to PostgreSQL..."],
  metadatas: [{ category: "database" }],
});

// Query
const results = await collection.query({
  queryTexts: ["how does vector search work"],
  nResults: 10,
});
```

Chroma is great for getting started and testing ideas. For production workloads, you'll likely graduate to pgvector (if you want simplicity) or a dedicated vector database (if you need scale).

## [LanceDB: Best Embedded Vector Database](https://encore.dev/articles/best-vector-databases#lancedb-best-embedded-vector-database)

[LanceDB](https://lancedb.com/) is an open-source embedded vector database built on the Lance columnar format. It runs in-process with zero-copy access to data, making it fast for local workloads without a running server.

**Key features:**

*   Zero-copy, columnar storage based on the Lance format
*   In-process operation, no separate server required
*   Supports disk-based indexing (IVF-PQ) for datasets larger than RAM
*   Automatic versioning of data
*   Serverless cloud offering in beta

**Best for:**

*   Applications where an embedded database is preferred (edge, desktop, local-first)
*   Data science workflows that need fast iteration without a server
*   Workloads where disk-based indexing enables larger-than-memory datasets
*   Teams already using the Arrow/Lance ecosystem

**Limitations:**

*   Relatively new, with a smaller community and fewer production deployments
*   Cloud offering is still in beta
*   Multi-process concurrent access has limitations
*   Ecosystem and integrations are still maturing

**Example:**

```
import * as lancedb from "lancedb";

const db = await lancedb.connect("data/lancedb");

const table = await db.createTable("documents", [
  { id: 1, text: "pgvector adds vector search...", vector: embedding },
]);

const results = await table.search(queryEmbedding).limit(10).toArray();
```

LanceDB is worth watching if you're building local-first applications or working in data science workflows where running a server is overhead. For backend services, pgvector or a managed option is usually a better fit.

## [How to Choose](https://encore.dev/articles/best-vector-databases#how-to-choose)

### [Start with pgvector if:](https://encore.dev/articles/best-vector-databases#start-with-pgvector-if)

You already run PostgreSQL (most backend teams do). pgvector adds vector search without adding infrastructure. Documents and embeddings live in the same table, in the same transaction. You use SQL for filtering. There's no sync pipeline, no extra credentials, no new service to monitor. For workloads under 5 million vectors, performance is more than adequate.

### [Add a dedicated vector database if:](https://encore.dev/articles/best-vector-databases#add-a-dedicated-vector-database-if)

Your workload exceeds what a single Postgres instance handles comfortably (hundreds of millions of vectors, high concurrent query throughput, or requirements for auto-scaling and per-tenant isolation). Choose between:

*   **Pinecone** if you want fully managed with zero ops
*   **Qdrant** if you want open-source with strong performance and payload filtering
*   **Milvus** if you need enterprise scale with GPU acceleration
*   **Weaviate** if you want built-in vectorization and hybrid search

### [Use an embedded database if:](https://encore.dev/articles/best-vector-databases#use-an-embedded-database-if)

You're prototyping, building local-first, or don't want to run a server. Chroma for the simplest API and getting started fast. LanceDB for larger-than-memory datasets with disk-based indexing.

### [Decision Matrix](https://encore.dev/articles/best-vector-databases#decision-matrix)

| Consideration | Recommended Option |
| --- | --- |
| Already running Postgres, <5M vectors | pgvector |
| Zero operational overhead, any scale | Pinecone |
| Open-source, dedicated, self-hosted | Qdrant |
| Built-in vectorization, hybrid search | Weaviate |
| Billions of vectors, enterprise | Milvus |
| Prototyping, local dev, learning | Chroma |
| Embedded, local-first, edge | LanceDB |

## [Getting Started with pgvector](https://encore.dev/articles/best-vector-databases#getting-started-with-pgvector)

For most teams adding AI features to an existing backend, pgvector is the simplest path. You avoid a separate service, get transactional consistency, and keep the SQL tooling you already know.

If you're building a TypeScript backend, [Encore](https://encore.dev/) provisions PostgreSQL with pgvector automatically. Databases are declared in code, migrations run on startup, and the same setup works locally and in production:

```
import { api } from "encore.dev/api";
import { SQLDatabase } from "encore.dev/storage/sqldb";

const db = new SQLDatabase("search", {
  migrations: "./migrations",
});

export const search = api(
  { expose: true, method: "POST", path: "/search" },
  async (req: { query: string }): Promise<{ results: SearchResult[] }> => {
    const embedding = await generateEmbedding(req.query);

    const rows = await db.query<SearchResult>`
      SELECT id, title, 1 - (embedding <=> ${embedding}::vector) AS similarity
      FROM documents
      ORDER BY embedding <=> ${embedding}::vector
      LIMIT 5
    `;

    const results: SearchResult[] = [];
    for await (const row of rows) {
      results.push(row);
    }

    return { results };
  }
);
```

For a step-by-step tutorial building a complete RAG pipeline, see [How to Build a RAG Pipeline with TypeScript](https://encore.dev/articles/how-to-build-rag-pipeline). For a head-to-head comparison with the most popular managed alternative, see [pgvector vs Pinecone](https://encore.dev/articles/pgvector-vs-pinecone).

* * *

_Have questions about choosing a vector database? Join our [Discord community](https://encore.dev/discord) where developers discuss architecture decisions daily._


### Источник: https://nikita-interactive.ru/journal/ai/kakie-vektornye-bazy-dannykh-stoit-vybratj
Title: Какие векторные базы данных стоит выбрать?

URL Source: https://nikita-interactive.ru/journal/ai/kakie-vektornye-bazy-dannykh-stoit-vybratj

Markdown Content:
## Какие векторные базы данных стоит выбрать?

Обновлено 16 августа 2023 - 2 года назад.  Источник - **Opensourceforu.com.**

![Image 1](https://cdn.nikita-interactive.com/linery/ujeewash/NOSOTA/NOSOTA-NEWS/02610-aee5a657ad1599cc18abdec2c0b2b39b-00000-a04a9ce2a01a8e7bf2e2e32320e82097.jpg)

Векторные базы данных обеспечивают эффективность и масштабируемость и меняют способы использования потенциала встраивания данных в цифровую эпоху. Существует довольно много векторных баз данных с открытым исходным кодом, которые имеют свои преимущества. Мы рассмотрим их вкратце.

В обработке естественного языка (NLP) вкрапление - это представление текста в виде векторов. Цель встраивания - передать семантическое значение слов или документов таким образом, чтобы его могла понять модель машинного обучения.

Векторная база данных (или база данных вкраплений) в NLP - это специализированная база данных, предназначенная для эффективного хранения, извлечения и выполнения операций с высокоразмерными векторными данными (такими как вкрапления, упомянутые выше). Векторные базы данных оптимизированы для эффективного выполнения операций поиска ближайших соседей, что является общим требованием в приложениях NLP. Они обеспечивают способ организации и поиска в больших объемах данных вкраплений, что может быть полезно в различных задачах, таких как поиск информации, сходство документов, кластеризация и другие.

В качестве примера, допустим, вы вложили большое количество документов с помощью модели Doc2Vec. Теперь, получив новый документ, вы хотите найти наиболее похожие документы в вашей базе данных. Для этого необходимо:

1.    Сначала вложите новый документ в то же самое высокоразмерное пространство.
2.    Далее в базе данных векторов ищем векторы, наиболее близкие к вектору нового документа. Это и есть поиск ближайших соседей.

Из-за высокой размерности данных такой поиск может потребовать больших вычислительных затрат. Однако векторные базы данных используют специализированные алгоритмы индексирования и запросов (например, k-d деревья, шаровые деревья или методы хеширования) для ускорения этих операций. Примерами таких баз данных являются FAISS, разработанная Facebook AI, и Annoy, разработанная Spotify.

## Векторные базы данных с открытым исходным кодом

### Weaviate:

Эта векторная база данных с открытым исходным кодом позволяет хранить и извлекать объекты данных на основе их семантических свойств с помощью векторного индексирования.

*    Он поддерживает различные типы медиа, включая текст, изображения и т.д., и предлагает такие функции, как семантический поиск, извлечение вопросов и ответов, классификация и настраиваемые модели.
*    Он предоставляет GraphQL API для простого доступа к данным и оптимизирован для высокой производительности, что подтверждается бенчмарками с открытым исходным кодом.
*    Среди основных характеристик - быстрые запросы, поддержка нескольких типов медиа с помощью модулей, комбинированный векторный и скалярный поиск, доступ к данным в реальном времени и постоянный доступ, горизонтальная масштабируемость и графоподобные связи между объектами.
*    Weaviate рекомендуется для повышения качества поиска, выполнения поиска по сходству с моделями машинного обучения (ML), эффективного сочетания векторного и скалярного поиска, масштабирования ML-моделей для производства и выполнения задач быстрой классификации.
*    Он находит применение в семантическом поиске, поиске по изображениям, обнаружении аномалий, рекомендательных системах, поиске в электронной коммерции, классификации данных, анализе киберугроз и т. д.

### Pgvector:

Это расширение PostgreSQL с открытым исходным кодом, позволяющее осуществлять поиск по векторному сходству в базе данных. Оно позволяет эффективно хранить и запрашивать высокоразмерные векторы, что делает его подходящим для таких приложений, как рекомендательные системы, обработка естественного языка и анализ изображений.

*    Pgvector предлагает функции и операторы для поиска сходства векторов, например, для нахождения ближайших соседей на основе расстояний между векторами или для выполнения соединений сходства между векторами. Процесс поиска оптимизирован с использованием индексных структур, таких как K-d деревья или Annoy.
*    С помощью pgvector векторные данные можно хранить непосредственно в таблицах PostgreSQL, что позволяет легко интегрировать поиск векторных подобий в существующие рабочие процессы баз данных. Он также обеспечивает поддержку индексации и запросов для нескольких векторных полей в одной таблице.
*    Расширение реализовано на языке C и поддерживает множество типов векторных данных, таких как float4, float8 и integer. Оно предлагает простой SQL-интерфейс для векторных операций и может быть легко интегрировано с другими функциями и расширениями PostgreSQL.
*    Pgvector расширяет возможности PostgreSQL, добавляя функциональность поиска векторного сходства, позволяя разработчикам проводить эффективный и масштабируемый поиск сходства в высокоразмерных векторных данных непосредственно в базе данных.

### Chroma DB:

Chroma - это база данных с открытым исходным кодом для встраивания. Она облегчает разработку приложений LLM, позволяя встраивать в LLM знания, факты и навыки.

Chroma предоставляет средства для:

*   Храните вкрапления и связанные с ними метаданные
*   Вставка документов и запросов
*   Поиск встроенного содержимого

### Milvus:

Milvus был разработан в 2019 году для хранения, индексации и управления массивными векторами встраивания, генерируемыми глубокими нейронными сетями и другими ML-моделями.

*    Она предназначена для обработки запросов к векторным данным и способна индексировать векторы в триллионном масштабе. Milvus может работать с встраиванием векторов, полученных из неструктурированных данных, в отличие от реляционных баз данных, которые работают со структурированными данными.
*    В Интернете все большее распространение получают неструктурированные данные, такие как электронные письма, документы, данные датчиков IoT, фотографии и структуры белков. Milvus хранит и индексирует эти векторы, позволяя компьютерам интерпретировать неструктурированные данные.
*    Milvus способен анализировать корреляцию между двумя векторами, вычисляя расстояние их сходства, которое указывает на сходство исходных данных, если векторы чрезвычайно похожи.

### QDrant:

Эта векторная база данных с открытым исходным кодом предназначена для быстрого и масштабируемого хранения и поиска высокоразмерных данных.

*    В нем используются передовые методы индексирования, включая приближенные ближайшие соседи (ANN) и квантование продукта, для эффективного поиска и извлечения данных.
*    QDrant поддерживает вычисления на базе CPU и GPU, обеспечивая гибкость и адаптацию к различным аппаратным конфигурациям.
*    База данных обладает высокой масштабируемостью и способна обрабатывать большие объемы данных и высокий пользовательский параллелизм.
*    Уникальной особенностью QDrant является возможность хранения и поиска геопространственных данных, что делает его хорошо подходящим для приложений, основанных на определении местоположения.

У каждой из этих векторных баз данных есть свои сильные стороны и области применения. Weaviate выделяется возможностями семантического поиска и поддержкой различных типов носителей. Pgvector легко интегрируется с PostgreSQL и обеспечивает эффективный поиск по сходству векторов. Chroma DB фокусируется на хранении и поиске встраиваемых данных для LLM-приложений. Milvus специализируется на работе с массивными векторами вкраплений и неструктурированными данными. QDrant отличается быстрым и масштабируемым хранением и поиском высокоразмерных данных, а также поддержкой геопространственных данных. Выбор базы данных зависит от конкретных требований и сценариев использования приложения.

Эта статья является экземпляром [CROSS-текста](https://nikita-interactive.ru/cross). Такие тексты отлично продвигают сайты в ТОП органического поиска Яндекс и Google. [Здесь](https://nikita-interactive.ru/cross) я пишу об этом более подробно.

![Image 2: Nikita Interactive, founder](https://nikita-interactive.ru/assets/images/nikita/photo.webp)

Искренне Ваш,

Nikita Interactive

### Это реальная история!

Раздел с **CROSS-текстами** дополнительно привлек 18 090 пользователей за 9 месяцев.

На новом сайте. Без ссылок.

[](https://nikita-interactive.ru/journal/ai/kakie-vektornye-bazy-dannykh-stoit-vybratj#)
