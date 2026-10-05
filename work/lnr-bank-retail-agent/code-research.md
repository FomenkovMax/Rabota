# Code Research: lnr-bank-retail-agent

Дата: 2026-10-05

## Существующий код

Кода агента нет. В репозитории — Vite-лендинг «ЛИФТ» (`index.html`, `src/`, `qa/`), к задаче он не относится. Агент — новый самостоятельный Python-проект в папке `lnr-bank-agent/`, со своим `pyproject.toml`. Сборку лендинга он не затрагивает: Netlify публикует только `dist/`.

## Входные материалы

| Файл | Что даёт |
|---|---|
| `prompts/lnr-bank-retail-agent/system-prompt.txt` | Доменные правила: привязка к ЛНР, продукты по блокам, сценарии, модель данных, качество, анализ, границы |
| `prompts/lnr-bank-retail-agent/README.md` | Режимы запуска, выходы, ограничения |
| `prompts/lnr-bank-retail-agent/runs/2026-10-05_test-dostupa/run_log.md` | Результаты теста доступа |
| `prompts/lnr-bank-retail-agent/runs/2026-10-05_test-dostupa/site_playbook.csv` | Черновик способов привязки к ЛНР |
| `prompts/lnr-bank-retail-agent/runs/2026-10-05_test-dostupa/psb_lnr_cities.csv` | 56 населённых пунктов ЛНР из выбора города на сайте ПСБ с их id |

## Проверенные факты (05.10.2026)

- **Сертификаты.** sberbank.ru, vtb.ru, psbank.ru, tbank.ru, api.giga.chat и gigachat.devices.sberbank.ru подписаны «Russian Trusted Sub CA» → «Russian Trusted Root CA» (Минцифры).
  - Корень с gu-st.ru (CDN Госуслуг): SHA-256 `D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31`, действует до 27.02.2032. Отпечаток совпал с корнем в цепочках банков.
  - Промежуточный Sub CA у банков новее файла на gu-st.ru, поэтому закреплять в коде нужно только корень.
- **Сайты без браузера** (прямой HTTPS с корнем Минцифры):
  - ПСБ, ВТБ, Т-Банк отдают полные страницы;
  - Сбер отдаёт страницу JS-проверки браузера (≈6 КБ, маркеры `TSPD`, `bobcmn`): контент виден только в настоящем браузере.
- **ПСБ.** Выбор города встроен в страницу в виде JSON: 56 населённых пунктов ЛНР с `parentId` 811561, Луганск — id 811307. По умолчанию открывается `cityId` 811354.
- **ВТБ.** Селектора региона в исходном HTML главной нет, вероятно, он подгружается скриптом. На сайте есть отдельная линия 8 800 100-24-24 для клиентов Крыма, ДНР, ЛНР, Запорожской и Херсонской областей.
- **Т-Банк.** ЛНР на главной не упоминается, в коде есть только геолокация для карт. Вероятный путь привязки — `federal_confirmed`.
- **ЦБ.** Ключевая ставка — таблица `https://www.cbr.ru/hd_base/KeyRate/` (параметры `UniDbQuery.From` и `UniDbQuery.To`). На 05.10.2026 — 14,00 %.
- **GigaChat SDK** (`gigachat` 0.2.3, PyPI):
  - настройки: `credentials`, `scope` (по умолчанию `GIGACHAT_API_PERS`), `model`, `verify_ssl_certs`, `ca_bundle_file`, `timeout`, `max_retries`;
  - методы: `chat`, `get_models`, `tokens_count`, `get_balance`;
  - структурированный ответ: модели содержат `functions`, `function_call`, `response_format` и `json_schema`;
  - адреса по умолчанию: `https://api.giga.chat/v1` и `https://ngw.devices.sberbank.ru:9443/api/v2/oauth`.

## Выводы для реализации

1. Корень Минцифры нужен в трёх местах: системное хранилище, хранилище браузера (на Linux — NSS DB `~/.pki/nssdb`) и CA-бандл для Python, который получают httpx и `ca_bundle_file` GigaChat.
2. Для Сбера нужен полноценный браузер. Прямых HTTP-запросов недостаточно.
3. Привязка к ЛНР у банков разная, поэтому описывается декларативно, по банку, в `site_playbook.yaml`.
