---
created: 2026-10-05
status: approved
size: L
branch: dev
---

# Tech Spec: локальный агент сравнения розничных продуктов банков в ЛНР (MVP)

## Overview

Python-агент на VPS в РФ с Ubuntu (основная платформа; также поддерживаются Linux и macOS) с установленным корневым сертификатом Минцифры. Раз в неделю и по команде он:
- открывает официальные сайты Сбера, ВТБ, ПСБ и Т-Банка в браузере Chromium (Playwright);
- выбирает ЛНР и собирает страницы продуктов и PDF-тарифы;
- извлекает параметры через GigaChat и проверяет, что каждая цитата дословно есть в источнике;
- считает типовые сценарии и записывает срез в SQLite;
- сравнивает срез с прошлым, считает позицию Сбера;
- выпускает Excel и HTML-дашборд, присылает сводку и файлы в Telegram.

Доменные правила (продукты, сценарии, пороги, модель данных, качество, границы) берутся из `prompts/lnr-bank-retail-agent/system-prompt.txt`. Требования — `user-spec.md`, проверенные факты — `code-research.md`.

## Architecture

### Stack

Python 3.11+, Playwright (Chromium), httpx, pydantic v2, pydantic-settings, Typer, Jinja2, openpyxl, pdfplumber, beautifulsoup4 и lxml, gigachat (SDK 0.2.x), SQLite (`sqlite3` из стандартной библиотеки). Тесты: pytest. Качество: ruff, pre-commit, gitleaks. Зависимости: uv с lock-файлом. Графики в HTML: Chart.js, вложенный в файл.

### Project Layout

Новый самостоятельный проект в папке `lnr-bank-agent/` этого репозитория:

```
lnr-bank-agent/
  pyproject.toml, uv.lock, .env.example, .gitignore, .pre-commit-config.yaml, README.md
  config/
    settings.yaml          # банки и домены, регион, блоки, пороги, сценарии, LLM, расписание (без секретов)
    parameters.yaml        # словарь параметров по блокам: имя, единица, better, описание
    site_playbook.yaml     # по банку и разделу: стартовые URL и шаги привязки к ЛНР
  scripts/install_certs.sh # корень Минцифры: скачать, сверить отпечаток, установить
  src/lnrbank/
    cli.py, config.py, pipeline.py, runlock.py
    net/tls.py             # CA-бандл (certifi + корень Минцифры), проверка TLS
    browser/               # engine.py, region.py, robots.py, antibot.py
    adapters/              # base.py, sber.py, vtb.py, psb.py, tbank.py, calculators.py
    llm/                   # base.py, gigachat.py, smoke.py
    extract/               # pipeline.py, clean.py, schema.py, prompts/*.md
    calc/                  # formulas.py, scenarios.py
    quality/rules.py
    storage/               # db.py, schema.sql, models.py
    analysis/              # changes.py, gaps.py, insights.py
    outputs/               # excel.py, html.py, sanitize.py, templates/, static/
    notify/telegram.py
  tests/                   # unit/, integration/, fixtures/, golden/
  data/                    # в .gitignore: lnr_bank.db, raw/{snapshot}/{bank}/, out/{snapshot}/, logs/
```

### Components and Data Flow

1. **CLI** (`lnrbank`) — режимы `check`, `run --mode block|full|update`, `build`, `notify --test`.
2. **Подготовка** — загрузка настроек, проверка TLS к доменам банков и GigaChat, ключевая ставка ЦБ, блокировка от параллельного запуска.
3. **Браузер** — один Chromium на запуск, по контексту на банк, последовательные загрузки с паузами, проверка robots.txt, распознавание антибот-страниц и капчи.
4. **Привязка к ЛНР** — движок выполняет шаги из `site_playbook.yaml` и проверяет, что регион применился. Результат: способ (`selector`, `calc_checkbox`, `regional_tariff`, `federal_confirmed`, `not_confirmed`) и доказательство (скриншот, текст в шапке).
5. **Адаптеры банков** — продуктовая линейка по блокам, загрузка страниц и PDF в архив сырых документов, инфраструктура по городам, калькуляторы для сценариев DEP и MTG.
6. **Извлечение** — очистка текста, вызов LLM со структурированным ответом, валидация по `parameters.yaml`, проверка цитат, кэш по хэшу содержимого.
7. **Сценарии** — результат калькулятора банка или формула (`calc_method`).
8. **Качество** — обязательные поля, правдоподобие относительно ключевой ставки, покрытие. Значения `not_confirmed` и `low` исключаются из анализа.
9. **Хранилище** — запись среза в SQLite, архив сырых документов.
10. **Анализ** — изменения и алерты относительно прошлого среза; место Сбера, отклонения, статусы, светофор; выводы по шаблонам.
11. **Выходы** — Excel и HTML.
12. **Доставка** — Telegram: сводка и файлы. Журнал запуска — `run_log.md`.

### Shared Resources

| Ресурс | Владелец | Потребители | Экземпляров |
|---|---|---|---|
| Chromium (Playwright) | `browser/engine.py` | `browser/region.py`, `adapters/*` | 1 на запуск; 1 контекст на банк |
| Клиент GigaChat | `llm/gigachat.py` | `extract/pipeline.py` | 1 на запуск; токен обновляет SDK |
| Соединение SQLite | `storage/db.py` | `pipeline.py`, `analysis/*`, `outputs/*` | 1 на процесс, режим WAL |
| CA-бандл (certifi + корень Минцифры) | `scripts/install_certs.sh`, `net/tls.py` | httpx, SDK gigachat (`ca_bundle_file`) | 1 файл на диске |

## Data Models

Таблицы из `<data_model>` системного промпта без изменений состава полей: `banks`, `infrastructure`, `products`, `conditions`, `scenarios`, `changes`, `gaps`, `data_quality`. Технические таблицы:

- `runs`: `run_id`, `snapshot_date`, `mode`, `blocks`, `started_at`, `finished_at`, `status` (ok, partial, failed), `key_rate`, `summary_json`;
- `raw_documents`: `doc_id`, `run_id`, `bank`, `url`, `kind` (html, pdf, screenshot, text), `path`, `sha256`, `fetched_at`, `region_method`;
- `llm_cache`: `content_sha256`, `prompt_version`, `model`, `response_json`, `created_at`.

Ключи и правила:
- `conditions` уникальна по (`snapshot_date`, `product_id`, `parameter`). Параметры только из `parameters.yaml`: условия, от которых зависит значение, входят в имя параметра (например, `rate_12m_online`), а `condition` — пояснение текстом.
- `product_id` = `{BANK}-{BLOCK}-{slug}`; slug строится из канонического пути URL продукта. Ручные переопределения — в `site_playbook.yaml`.
- Срезы только дописываются. Сырые документы хранятся за последние N срезов (по умолчанию 8), разобранные данные — всегда.

## Decisions

- **D-1. Детерминированная навигация, LLM только для извлечения.** Обход сайтов и выбор ЛНР выполняют адаптеры по сценариям из `site_playbook.yaml`, а не LLM-агент, который сам решает, куда кликать. Так срезы повторяемы и сопоставимы, а обход не зависит от прихотей модели. *Serves: US-1, US-2, US-6.*
- **D-2. Привязка к ЛНР — декларативный playbook с проверкой.** Шаги выбора региона лежат в YAML по банку и разделу. После шагов движок проверяет, что регион применился: название в шапке, параметр в URL, изменение списка программ. Сайт поменялся — правится конфиг, а не код. *Serves: US-2.*
- **D-3. Значения без подтверждённой ЛНР не участвуют в анализе.** `not_confirmed` и `confidence = low` сохраняются, но фильтруются в `gaps` и выводах. *Serves: US-2, US-3.*
- **D-4. Защита от выдумок LLM.** Каждое извлечённое значение сопровождается цитатой. Цитата должна дословно (после нормализации пробелов) встречаться в тексте источника, иначе значение отбрасывается. Ответ валидируется pydantic-схемой. Разрешены только параметры из `parameters.yaml`, единицы проверяются. Невалидный ответ — один повтор с текстом ошибки, затем «н/д». *Serves: US-3.*
- **D-5. GigaChat за сменным интерфейсом.**
  - Интерфейс `LLMProvider.extract(text, block, schema) -> ExtractionResult`; реализация на SDK `gigachat`.
  - `scope` и `model` берутся из настроек; модель по умолчанию — старшая из доступных по `get_models()`.
  - Структурированный ответ через `response_format` (json_schema). Если модель его не поддерживает — через `functions`.
  - YandexGPT и Ollama подключаются новым классом без изменения конвейера.

  *Serves: US-10.*
- **D-6. TLS с корнем Минцифры, проверка никогда не отключается.**
  - `install_certs.sh` скачивает корень с gu-st.ru и сверяет SHA-256 с закреплённым значением из `code-research.md`.
  - Ставит корень в системное хранилище (Linux: `update-ca-certificates`; macOS: `security add-trusted-cert`), в NSS DB браузера на Linux (`certutil`) и собирает CA-бандл certifi + корень для Python.
  - В коде запрещены `verify=False`, `verify_ssl_certs=False` и `ignore_https_errors=True`; это проверяет тест.

  *Serves: US-3, US-11.*
- **D-7. Вежливый сбор без обхода защит.**
  - Загрузки последовательные, пауза 3–6 с, один браузер.
  - Правила robots.txt (`urllib.robotparser`) соблюдаются.
  - Антибот-страница или капча → статус `blocked`, запись в `run_log` и сообщение в Telegram.
  - Нет stealth-плагинов, подмены отпечатков и решения капч.
  - В формы не вводятся персональные данные: калькуляторы заполняются только суммами, сроками и регионом.
  - Режим браузера настраивается (`headless: true|false`) для запуска на рабочем столе.

  *Serves: US-11.*
- **D-8. SQLite и архив сырых документов.** Один файл без администрирования. Длинный формат таблиц сразу пригоден для будущей BI-выгрузки, сырые документы позволяют перепроверить любую цифру. *[TECHNICAL]* Выбор SQLite — техническое решение; хранение срезов обслуживает US-6.
- **D-9. Кэш извлечения по хэшу содержимого.** Ключ — (`sha256` очищенного текста, версия промпта, модель). Неизменившиеся страницы не отправляются в LLM повторно: это экономит токены и не даёт ложных «изменений» от разброса ответов модели. *[TECHNICAL]*
- **D-10. Сценарии.**
  - Сценарии DEP и MTG считаются в калькуляторах банков, где они есть: там сильнее всего влияют регион и галочка «новые регионы».
  - Остальные сценарии MVP считаются формулами по опубликованным условиям (`calc_method = agent_formula`).
  - Формулы: аннуитет, доход по вкладу с капитализацией и без, эффективная ставка, годовая выгода карты, стоимость кредитной карты.

  *Serves: US-4.* Отклонение — см. User-Spec Deviations.
- **D-11. Выводы в MVP строятся по шаблонам, без LLM.** Сводка формируется из `gaps` по шаблону «факт + цифра + источник». Например: «Вклад 1 млн ₽ на 12 мес: Сбер — 14,2 %, 3-е место из 4; лучший — ПСБ, 15,0 % (+0,8 п.п.)». В выводах не может появиться непроверенная формулировка. *Serves: US-5, US-3.* Отклонение — см. User-Spec Deviations.
- **D-12. Excel на openpyxl, HTML одним файлом.**
  - Вкладки Excel:
    - «Сводка»: дата среза, ключевая ставка, покрытие, выводы, светофор;
    - «Продуктовые линейки»: матрица «продукт × банк» и каталог;
    - по вкладке на каждый блок MVP — таблица и график;
    - «Сценарии», «Gap Сбера», «Изменения» (алерты подсвечены), «Качество данных», «Источники» (кликабельные ссылки), «Справочник полей».
  - Оформление Excel: нативные графики openpyxl, закреплённые заголовки, автофильтр, форматы % и ₽, без объединённых ячеек в таблицах данных.
  - HTML: шаблон Jinja2 с autoescape, данные внутри файла в JSON. Chart.js фиксированной версии лежит в репозитории с проверкой SHA-256 и вкладывается в файл, поэтому дашборд работает без интернета.
  - У каждого банка постоянный цвет во всех графиках.

  *Serves: US-8, US-12.*
- **D-13. Защита выходов от внедрения.** Текст с сайтов экранируется в HTML. Данные внутри `<script>` вставляются через фильтр Jinja2 `tojson`, который экранирует `<`, `>` и `&`: так строка `</script>` из источника не выйдет за пределы блока данных. В Excel значения, начинающиеся с `=`, `+`, `-`, `@`, сохраняются как текст: это защита от формульных инъекций. Сообщения в Telegram отправляются без разметки или с экранированием. *[TECHNICAL]* Безопасность.
- **D-14. Защита от prompt-injection.** Текст страницы передаётся модели только как данные внутри разделителей. У модели нет инструментов, она возвращает только JSON по схеме, и всё проверяется по D-4. *[TECHNICAL]* Безопасность.
- **D-15. Telegram через Bot API напрямую (httpx).** После запуска — `sendMessage` со сводкой, затем `sendDocument` с Excel и HTML. Ошибка или блокировка сайта — отдельное сообщение. Бот только отправляет в заданный `chat_id` и не обрабатывает входящие команды, поэтому у него нет поверхности атаки. Токен и `chat_id` хранятся в `.env` и маскируются в логах. *Serves: US-9.*
- **D-16. Расписание через cron и блокировка запусков.** Запуск раз в неделю (по умолчанию пн 07:00 МСК; на macOS допустим launchd). Lock-файл не даёт двум запускам идти одновременно. *Serves: US-7.*
- **D-17. Режимы повторяют системный промпт.** `check` — этапы 0–1, `run --mode block` — один блок, `run --mode full` — все блоки MVP, `run --mode update` — полный сбор с изменениями и алертами (для cron), `build` — пересборка выходов из БД. *Serves: US-7.*
- **D-18. Код живёт в `lnr-bank-agent/` этого репозитория.** Отдельный `pyproject.toml`, сборку лендинга проект не затрагивает. При желании папку можно вынести в отдельный репозиторий без изменений. *[TECHNICAL]*
- **D-19. Контракт промптов.** Промпты лежат в `extract/prompts/`: `system.md` и `extract_{BLOCK}.md`. Версия промпта указана в первой строке файла и входит в ключ кэша (D-9), поэтому после правки промпта страницы разбираются заново. *[TECHNICAL]*
- **D-20. Общие файлы фиксируются в первой волне.** Зависимости, полная схема `settings.yaml` и словарь `parameters.yaml` создаются в T1 целиком. Параллельные задачи следующих волн их только читают и не конфликтуют. *[TECHNICAL]*
- **D-22. Основная платформа — VPS в РФ с Ubuntu, управление с телефона.** Пользователь работает с телефона, а облачная среда Claude не пускает браузер на сайты с сертификатами Минцифры. Поэтому агент живёт на VPS: установка одной командой (`curl … | bash` или `bash deploy.sh`), настройка `.env` и проверка доступны через SSH-клиент на телефоне (например, Termius). Разработка и офлайн-тесты идут в облачной сессии Claude Code, живой сбор — только на VPS. *Serves: US-7.*
- **D-21. Присутствие банков и watchlist.**
  - Присутствие четырёх банков подтверждается по их официальным сайтам: офисы, МФЦ, банкоматы, онлайн-доступность.
  - Watchlist в MVP — список кандидатов в `settings.yaml` с URL их страниц офисов. Для каждого кандидата агент проверяет, упоминаются ли на этой странице ЛНР или города ЛНР, и пишет результат в `banks`.
  - Автоматического поиска новых банков в MVP нет: надёжного официального перечня банков ЛНР в открытом виде не найдено.

  *Serves: US-13.* Отклонение — см. User-Spec Deviations.

## User-Spec Deviations

1. **US-4.** User-spec: сценарии считаются в калькуляторе банка, если он есть. Tech-spec: в MVP калькуляторы автоматизируются только для DEP и MTG, остальные сценарии считаются формулами по опубликованным условиям, даже если у банка есть калькулятор (`calc_method = agent_formula`). Почему: автоматизация каждого калькулятора — хрупкая работа с интерфейсом конкретного банка, а для DEP и MTG регион влияет сильнее всего. Остальные калькуляторы — в Extension. `[PENDING USER APPROVAL]`
2. **US-5, US-8.** Исходные требования предполагают выводы для руководства. Tech-spec: в MVP выводы на «Сводке» формируются по шаблонам из данных, без текста от LLM. Почему: исключён риск выдуманных формулировок. Текстовый отчёт с выводами от LLM (помечены как гипотезы) — в Extension вместе с docx. `[PENDING USER APPROVAL]`
3. **US-11 (расширение).** Tech-spec дополнительно соблюдает robots.txt: страницы, запрещённые для всех агентов, не собираются. Покрытие данных может снизиться — это видно в `data_quality`. `[PENDING USER APPROVAL]`
4. **US-13.** User-spec: агент сам находит другие банки в ЛНР. Tech-spec: в MVP watchlist — заданный пользователем список кандидатов, агент проверяет их присутствие по страницам офисов (D-21). Почему: надёжного официального перечня банков ЛНР в открытом виде нет, а поиск по СМИ дал бы непроверяемый результат. `[PENDING USER APPROVAL]`

## Technical Acceptance Criteria

- **TAC-1.** `lnrbank check` на целевой машине выдаёт по каждому банку статус TLS, загрузки и привязки к ЛНР (способ или причина) и сохраняет скриншот. TLS к GigaChat — OK.
- **TAC-2.** У 100 % строк `conditions` и `scenarios` заполнены `source_url`, `collected_at`, `region_method`, `evidence`. Каждая цитата найдена в сохранённом тексте источника (проверка в тесте и в `quality`).
- **TAC-3.** Значения `not_confirmed` и `low` не попадают в `gaps` и выводы (unit-тест).
- **TAC-4.** Формулы совпадают с эталонными расчётами с точностью до 1 ₽ (unit-тесты на эталонных примерах).
- **TAC-5.** Повторный запуск на неизменившихся страницах: 0 изменений и 0 вызовов LLM — всё из кэша.
- **TAC-6.** Изменение ставки на 0,25 п.п. и больше (на фикстуре) создаёт запись в `changes` с `alert = yes` и попадает в сообщение Telegram.
- **TAC-7.** Excel открывается без ошибок и содержит все вкладки из D-12. Графики есть, объединённых ячеек в таблицах данных нет, формульные значения обезврежены.
- **TAC-8.** HTML открывается локально без сети, фильтры, KPI, светофор и графики работают. Текст из источников экранирован (тест со строкой `<script>`).
- **TAC-9.** В коде нет отключения проверки TLS (тест-поиск по исходникам). Секреты только в `.env` (в `.gitignore`), gitleaks в pre-commit проходит.
- **TAC-10.** Полный запуск MVP (4 банка × 5 блоков) на целевой машине укладывается в 2 часа. В `run_log.md` есть покрытие по банкам и блокам.
- **TAC-11.** Второй одновременный запуск завершается сразу с сообщением о блокировке. Запуск по cron пишет лог в `data/logs/`.
- **TAC-12.** На эталонном наборе страниц извлечение даёт точность (precision) не ниже 0,9. Полнота (recall) записывается в отчёт проверки.

## Testing Strategy

Размер L: все уровни.

- **Unit:** формулы сценариев, правила качества, проверка цитат, валидация схемы, `product_id`, изменения и алерты, gap-анализ и светофор, шаблоны выводов, санитизация Excel и HTML, конфиг, отсутствие отключений TLS.
- **Integration (офлайн):**
  - адаптеры на сохранённых страницах и PDF каждого банка (`tests/fixtures/{bank}/`);
  - движок привязки к ЛНР на синтетических страницах с селектором, галочкой и сбросом региона;
  - конвейер блока с подменённым LLM;
  - запись и чтение среза;
  - генерация Excel и HTML из фикстурной БД.
- **LLM-оценка:** эталонный набор `tests/golden/` — не меньше 4 страниц или PDF на каждый блок MVP, все 4 банка, значения размечены вручную. Метрики: точность, полнота, доля найденных цитат (должна быть 100 %). Запуск: `python -m lnrbank.llm.smoke --golden`.
- **Live:** `lnrbank check` и один блок на целевой машине по Agent Verification Plan.

Все тесты, кроме live и LLM-оценки, идут без сети. В pre-commit — ruff, gitleaks и быстрые unit-тесты.

## Agent Verification Plan

Tools required: bash, Playwright (локально, для HTML-дашборда), Telegram (пользователь подтверждает получение).

1. **bash:** `lnrbank check` → TLS OK для 4 банков и GigaChat; по каждому банку `region_method` или причина `blocked`/`not_confirmed`; скриншоты в `data/raw/{snapshot}/{bank}/`.
2. **bash:** `lnrbank run --mode block --block DEP` → новый срез в БД; у каждого банка с подтверждённой ЛНР есть строки `conditions` с источником и цитатой; `run_log.md` с покрытием.
3. **bash:** повторить шаг 2 → 0 изменений, 0 вызовов LLM.
4. **bash:** `lnrbank build` → Excel и HTML в `data/out/{snapshot}/`; `openpyxl` открывает книгу, все вкладки на месте.
5. **Playwright:** открыть `dashboard_{дата}.html` по `file://` без сети → KPI-плитки и светофор видны, фильтр по банку меняет таблицу.
6. **Telegram:** `lnrbank notify --test`, затем реальный запуск → пользователь получает сводку и файлы.
7. **bash:** `crontab -l` содержит расписание; два одновременных запуска → второй завершается с сообщением о блокировке.
8. **bash:** `time lnrbank run --mode full` → укладывается в 2 часа (TAC-10); в `run_log.md` есть покрытие по банкам и блокам.

## Risks

| Риск | Вероятность | Влияние | Что делаем |
|---|---|---|---|
| Сайт банка поменял вёрстку, привязка или каталог сломались | высокая | среднее | Шаги в `site_playbook.yaml`; `check` перед сбором; алерт в Telegram с указанием раздела |
| Антибот Сбера не пускает автоматический браузер | средняя | высокое | Статус `blocked` и алерт без обхода; запуск в обычном (не headless) режиме на рабочем столе; ручная проверка |
| GigaChat плохо разбирает сложные таблицы и PDF | средняя | среднее | Эталонный набор и метрики; таблицы передаются в разметке; проверка цитат отсекает ошибки, итог — «н/д», а не неверная цифра |
| robots.txt запрещает нужные разделы | низкая | среднее | Фиксируем в `data_quality`; ручная проверка |
| Расход токенов GigaChat | средняя | низкое | Кэш по хэшу (D-9), обрезка текста до релевантных разделов, `tokens_count` в логе |
| Т-Банк не даёт выбрать регион | высокая | низкое | Путь `federal_confirmed`: подтверждение доступности продукта для жителя ЛНР |
| Сертификат Минцифры перевыпущен | низкая | высокое | Закреплён только корень (действует до 2032); `check` проверяет TLS при каждом запуске |

## Prerequisites (действия пользователя до старта)

- VPS в РФ с Ubuntu (root-доступ по SSH) и SSH-клиент на телефоне, например Termius. Альтернатива — ПК с Linux или macOS.
- Ключ авторизации GigaChat API (Authorization key) и scope (для физлиц — `GIGACHAT_API_PERS`), записать в `.env`.
- Telegram-бот через @BotFather: токен и `chat_id` получателя записать в `.env`.

## Implementation Tasks

### Wave 1

**T1. Каркас проекта, настройки и сертификаты**
- Description: Создать проект `lnr-bank-agent/` со структурой, всеми зависимостями MVP, CLI-заготовкой и загрузкой настроек (`settings.yaml`, `parameters.yaml`, `.env`), как требует D-20. Добавить скрипт установки корня Минцифры и проверку TLS к банкам и GigaChat (D-6). На этом каркасе строятся все следующие волны.
- Skill: infrastructure-setup
- Reviewers: code-reviewer, security-auditor, infrastructure-reviewer
- Verify-smoke: `bash scripts/install_certs.sh` → «fingerprint OK»; `lnrbank --help`; `lnrbank check --tls-only` → OK для sberbank.ru, vtb.ru, psbank.ru, tbank.ru, api.giga.chat; `pytest -q` и `pre-commit run --all-files` проходят.
- Files to modify: `lnr-bank-agent/pyproject.toml`, `uv.lock`, `.gitignore`, `.env.example`, `.pre-commit-config.yaml`, `README.md`, `config/settings.yaml`, `config/parameters.yaml`, `config/site_playbook.yaml`, `scripts/install_certs.sh`, `src/lnrbank/__init__.py`, `src/lnrbank/cli.py`, `src/lnrbank/config.py`, `src/lnrbank/net/tls.py`, `tests/unit/test_config.py`, `tests/unit/test_no_tls_bypass.py`
- Files to read: `work/lnr-bank-retail-agent/user-spec.md`, `work/lnr-bank-retail-agent/code-research.md`, `prompts/lnr-bank-retail-agent/system-prompt.txt`

### Wave 2

**T2. Хранилище срезов**
- Description: Реализовать SQLite-хранилище по разделу Data Models: срезы и запуски, таблицы данных, архив сырых документов и кэш LLM. Срезы только дописываются — на этом стоит конвейер с историей.
- Skill: code-writing
- Reviewers: code-reviewer, security-auditor, test-reviewer
- Files to modify: `src/lnrbank/storage/db.py`, `src/lnrbank/storage/schema.sql`, `src/lnrbank/storage/models.py`, `tests/unit/test_storage.py`
- Files to read: `config/parameters.yaml`, `prompts/lnr-bank-retail-agent/system-prompt.txt` (`<data_model>`)

**T3. Формулы сценариев и правила качества**
- Description: Реализовать формулы сценариев MVP (D-10) и правила качества: обязательные поля, правдоподобие относительно ключевой ставки, покрытие. Формулы нужны там, где калькулятор банка не автоматизирован, правила — чтобы непроверенные значения не попадали в сравнение (D-3).
- Skill: code-writing
- Reviewers: code-reviewer, security-auditor, test-reviewer
- Files to modify: `src/lnrbank/calc/formulas.py`, `src/lnrbank/calc/scenarios.py`, `src/lnrbank/quality/rules.py`, `tests/unit/test_formulas.py`, `tests/unit/test_quality.py`
- Files to read: `config/settings.yaml`, `config/parameters.yaml`, `prompts/lnr-bank-retail-agent/system-prompt.txt` (`<scenarios>`, `<quality>`)

**T4. LLM-провайдер и конвейер извлечения**
- Description: Сделать сменный интерфейс LLM и реализацию на GigaChat (D-5), а также конвейер извлечения с защитами D-4, D-9 и D-14: очистка текста и таблиц, структурированный ответ, валидация, проверка цитат, кэш. Это единственное место, где LLM влияет на данные. Промпты подключаются по контракту D-19; до T7 используются заглушки.
- Skill: code-writing
- Reviewers: code-reviewer, security-auditor, test-reviewer
- Verify-smoke: `python -m lnrbank.llm.smoke` → список моделей GigaChat; фрагмент «Ставка 14,2 % на 12 месяцев» даёт `rate_12m = 14.2` с дословной цитатой.
- Files to modify: `src/lnrbank/llm/base.py`, `src/lnrbank/llm/gigachat.py`, `src/lnrbank/llm/smoke.py`, `src/lnrbank/extract/pipeline.py`, `src/lnrbank/extract/clean.py`, `src/lnrbank/extract/schema.py`, `src/lnrbank/extract/prompts/*.md` (заглушки), `tests/unit/test_extract_pipeline.py`, `tests/unit/test_evidence_check.py`
- Files to read: `config/parameters.yaml`, `work/lnr-bank-retail-agent/code-research.md` (GigaChat SDK)

**T5. Браузерный движок, привязка к ЛНР и проверка доступа**
- Description: Сделать слой браузера по D-7 и движок `site_playbook` для выбора и проверки ЛНР (D-2). Заполнить playbook для четырёх банков по результатам теста доступа. Команда `lnrbank check` выполняет этапы 0–1: TLS, ключевая ставка ЦБ, загрузка, привязка, присутствие банков и проверка watchlist (D-21).
- Skill: code-writing
- Reviewers: code-reviewer, security-auditor, test-reviewer
- Verify-smoke: `lnrbank check` на целевой машине → по каждому банку TLS, загрузка, привязка (способ или причина), скриншоты в `data/raw/`; ключевая ставка ЦБ на дату.
- Verify-user: открыть скриншоты и убедиться, что на сайтах выбраны Луганск или ЛНР.
- Files to modify: `src/lnrbank/browser/engine.py`, `src/lnrbank/browser/region.py`, `src/lnrbank/browser/robots.py`, `src/lnrbank/browser/antibot.py`, `src/lnrbank/net/cbr.py`, `src/lnrbank/cli.py`, `config/site_playbook.yaml`, `tests/integration/test_region_engine.py`, `tests/unit/test_cbr.py`, `tests/fixtures/region/`
- Files to read: `prompts/lnr-bank-retail-agent/runs/2026-10-05_test-dostupa/` (все файлы), `prompts/lnr-bank-retail-agent/system-prompt.txt` (`<region_rules>`, `<boundaries>`), `work/lnr-bank-retail-agent/code-research.md`

### Wave 3

**T6. Адаптеры банков: каталог, документы, инфраструктура, калькуляторы**
- Description: Реализовать адаптеры SBER, VTB, PSB и TBANK. Каждый собирает продуктовую линейку блоков MVP с отметкой доступности в ЛНР, страницы продуктов и PDF-тарифы, офисы и банкоматы по городам ЛНР; калькуляторы автоматизируются для сценариев DEP и MTG (D-10). Сохранить по каждому банку набор страниц как фикстуры для офлайн-тестов и для проверки промптов в T7.
- Skill: code-writing
- Reviewers: code-reviewer, security-auditor, test-reviewer
- Verify-smoke: `lnrbank run --mode block --block DEP --collect-only` → страницы и PDF каждого банка в `data/raw/{snapshot}/{bank}/`, строки `products` с `available_in_lnr`.
- Files to modify: `src/lnrbank/adapters/base.py`, `src/lnrbank/adapters/sber.py`, `src/lnrbank/adapters/vtb.py`, `src/lnrbank/adapters/psb.py`, `src/lnrbank/adapters/tbank.py`, `src/lnrbank/adapters/calculators.py`, `config/site_playbook.yaml`, `tests/integration/test_adapters_offline.py`, `tests/fixtures/{sber,vtb,psb,tbank}/`
- Files to read: `src/lnrbank/browser/`, `prompts/lnr-bank-retail-agent/system-prompt.txt` (`<products>`, `<scenarios>`), `config/parameters.yaml`

### Wave 4

**T7. Промпты извлечения**
- Description: Написать системный промпт и промпты извлечения для блоков MVP по правилам системного промпта: только написанное в источнике, дословная цитата, условия, «н/д». Добавить 1–2 примера на блок. Разметить эталонный набор из фикстур T6 и добиться на нём метрик TAC-12.
- Skill: prompt-master
- Reviewers: prompt-reviewer
- Verify-smoke: `python -m lnrbank.llm.smoke --golden` → точность ≥ 0,9, 100 % цитат найдено.
- Verify-user: сверить 10 случайных значений с сайтами банков.
- Files to modify: `src/lnrbank/extract/prompts/system.md`, `src/lnrbank/extract/prompts/extract_DEP.md`, `extract_CARD.md`, `extract_LOAN.md`, `extract_MTG.md`, `extract_CHANNEL.md`, `tests/golden/`
- Files to read: `prompts/lnr-bank-retail-agent/system-prompt.txt`, `config/parameters.yaml`, `src/lnrbank/extract/schema.py`, `tests/fixtures/`

**T8. Оркестрация конвейера и анализ**
- Description: Собрать режимы из D-17: сбор → извлечение → сценарии → качество → запись среза → изменения и алерты → позиция Сбера и светофор → выводы по шаблонам (D-11) → `run_log.md`. Добавить блокировку параллельных запусков (D-16) и итоговый статус запуска для уведомлений. Это и есть конвейер обновления данных.
- Skill: code-writing
- Reviewers: code-reviewer, security-auditor, test-reviewer
- Verify-smoke: `lnrbank run --mode block --block DEP` → новый срез, строки с источниками и цитатами, `run_log.md` с покрытием; повторный запуск → 0 изменений, 0 вызовов LLM.
- Files to modify: `src/lnrbank/pipeline.py`, `src/lnrbank/runlock.py`, `src/lnrbank/analysis/changes.py`, `src/lnrbank/analysis/gaps.py`, `src/lnrbank/analysis/insights.py`, `src/lnrbank/cli.py`, `tests/unit/test_changes.py`, `tests/unit/test_gaps.py`, `tests/unit/test_insights.py`, `tests/integration/test_pipeline_offline.py`
- Files to read: `src/lnrbank/storage/`, `src/lnrbank/calc/`, `src/lnrbank/quality/`, `src/lnrbank/extract/`, `src/lnrbank/adapters/`, `prompts/lnr-bank-retail-agent/system-prompt.txt` (`<analysis>`, `<pipeline>`)

### Wave 5

**T9. Выходы и доставка: Excel, HTML, Telegram**
- Description: Сформировать Excel и самодостаточный HTML-дашборд по D-12 с защитой от внедрения по D-13. Отправлять в Telegram сводку запуска и файлы отчёта по D-15.
- Skill: code-writing
- Reviewers: code-reviewer, security-auditor, test-reviewer
- Verify-smoke: `lnrbank build` → файлы в `data/out/{snapshot}/`, `openpyxl` открывает книгу; `lnrbank notify --test` → сообщение пришло.
- Verify-user: открыть Excel и HTML двойным кликом без интернета, проверить светофор и графики, получить сообщение в Telegram.
- Files to modify: `src/lnrbank/outputs/excel.py`, `src/lnrbank/outputs/html.py`, `src/lnrbank/outputs/sanitize.py`, `src/lnrbank/outputs/templates/dashboard.html.j2`, `src/lnrbank/outputs/static/chart.umd.min.js`, `src/lnrbank/notify/telegram.py`, `src/lnrbank/cli.py`, `tests/unit/test_sanitize.py`, `tests/integration/test_outputs.py`
- Files to read: `src/lnrbank/storage/`, `src/lnrbank/analysis/`, `prompts/lnr-bank-retail-agent/system-prompt.txt` (`<outputs>`)

### Wave 6 — Audit Wave

**T10. Code Audit**
- Description: Целостная проверка качества кода всей фичи, отчёт с замечаниями.
- Skill: code-reviewing
- Reviewers: none

**T11. Security Audit**
- Description: Проверка по OWASP Top 10 всех компонентов: секреты, TLS, внедрение в HTML и Excel, prompt-injection, работа с внешним контентом.
- Skill: security-auditor
- Reviewers: none

**T12. Test Audit**
- Description: Проверка качества и покрытия тестов по Testing Strategy.
- Skill: test-master
- Reviewers: none

### Wave 7 — Final Wave

**T13. QA**
- Description: Прогнать все тесты и проверить acceptance criteria из user-spec и tech-spec. То, что требует живой среды, отложить в post-deploy.
- Skill: pre-deploy-qa
- Reviewers: none

**T14. Deploy на целевую машину**
- Description: Скрипт развёртывания на VPS с Ubuntu (D-22), запускаемый одной командой: Python и uv, Chromium для Playwright, `install_certs.sh`, `.env` с правами 600, непривилегированный пользователь, cron раз в неделю с логом в `data/logs/`. Пошаговая инструкция для телефона: аренда VPS, подключение через Termius, установка, заполнение `.env`, первый `lnrbank check`. Linux и macOS на ПК поддерживаются той же инструкцией.
- Skill: deploy-pipeline
- Reviewers: code-reviewer, security-auditor, deploy-reviewer
- Verify-user: на целевой машине `crontab -l` показывает расписание, ручной запуск `lnrbank check` проходит.
- Files to modify: `lnr-bank-agent/scripts/deploy.sh`, `lnr-bank-agent/scripts/crontab.example`, `lnr-bank-agent/README.md`, `lnr-bank-agent/docs/setup-from-phone.md`
- Files to read: `work/lnr-bank-retail-agent/tech-spec.md` (D-6, D-16, Prerequisites)

**T15. Post-deploy verification**
- Description: Выполнить Agent Verification Plan на целевой машине и проверить отложенные критерии.
- Skill: post-deploy-qa
- Reviewers: none

## Extension (следующий tech-spec)

- Блоки DAILY, INV, SEG и сценарии TRF-1, TRF-2, CSH-1.
- Автоматизация остальных калькуляторов банков.
- Streamlit-дашборд с динамикой по срезам.
- Выгрузка `bi/*.csv` и `bi/data_dictionary.md` для Power BI, DataLens, Superset.
- Отчёт для руководства в docx с текстом от LLM (выводы с цифрами, гипотезы помечены).
- Полное сравнение банков из watchlist.
- Провайдеры YandexGPT и Ollama.
