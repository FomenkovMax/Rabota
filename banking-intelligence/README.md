# Banking Intelligence AI

Telegram-бот для конкурентного анализа розничных банковских продуктов (вклады, накопительные счета, акции) на территории ЛНР: Сбер, ПСБ, ВТБ, Генбанк, ЦМР банк.

> ⚠️ **Статус: демо-прототип, этап 2 из 7.** Загрузчик готов, но данные о ставках и акциях **ещё не собираются**: нет подтверждённых URL продуктовых страниц и адаптеров. Бот намеренно не показывает никаких цифр. Домены банков и присутствие в ЛНР помечены как **не подтверждённые** до ручной проверки.

## Что работает сейчас (проверено тестами)

| Компонент | Состояние |
|---|---|
| Реестр банков и источников (`config/*.yaml` → БД), валидация «только официальные домены» | ✅ |
| Модель данных с происхождением значений (документ, URL, время, цитата) | ✅ |
| Миграции Alembic (проверены на SQLite и PostgreSQL 16, up/down/check) | ✅ |
| Интерфейс адаптера банка + статусы полноты сбора | ✅ |
| Бот: `/start`, `/banks`, `/status`, allowlist пользователей | ✅ (хендлеры протестированы с моками) |
| Бот: `/compare /deposits /savings /promo /changes /report /refresh` | 🚧 отвечают «не реализовано» |
| FastAPI `/health` | ✅ |
| Docker Compose | ⚠️ конфиг валиден (`docker compose config`), образ и запуск **не проверялись** (нет Docker-демона) |
| Реальная работа с Telegram | ⚠️ не проверялась (нет `BOT_TOKEN`) |
| Загрузчик (httpx): robots.txt, пауза между запросами, лимит размера, детект TLS/антибот/блокировок без обхода | ✅ (тесты на mock-транспорте) |
| Хранилище сырых документов (по sha256) + `fetch_attempts` + `collection_runs` | ✅ |
| `bankintel probe` / `discover` / `refresh`, бот `/refresh` | ✅ |
| Реальные адаптеры банков, PDF (PyMuPDF), Playwright, Celery/Redis | ❌ не сделано |
| AI, сравнение, отчёты, мониторинг | ❌ этапы 3–7, см. [PLANS.md](PLANS.md) |

> Исправление: первая версия детектора принимала WAF-страницу Сбера за успешную загрузку; исправлено, добавлен тест.

Кандидаты на источники: [docs/source-candidates.md](docs/source-candidates.md).

### Доступность сайтов из тестовой среды (прогон `bankintel probe`, 24.10.2026)

| Банк | Результат |
|---|---|
| ПСБ, ВТБ, ЦМР банк | ✅ 200, `robots.txt` прочитан |
| Сбербанк | ❌ `blocked`: HTTP 200, но вместо сайта страница WAF (`user_blocked`) — даже с сертификатом Минцифры. Причина не установлена, не обходим. |
| Генбанк | ❌ 401 на корне сайта (по `curl` — также 403 и сброс соединения). Похоже на WAF/ограничение доступа; причина не установлена. Не обходим — фиксируем как неполноту данных. |

Сбер/ПСБ/ВТБ раньше падали с `tls_error`: их сайты подписаны корневым CA Минцифры («Russian Trusted Root CA»), которого нет в стандартных наборах. Сертификат лежит в `certs/` (источник, отпечаток и ограничения доверия — в `certs/README.md`) и подключается только в загрузчик через `EXTRA_CA_BUNDLE`; проверка сертификатов не отключена.

## Быстрый старт

```bash
cp .env.example .env        # заполните BOT_TOKEN и ALLOWED_TELEGRAM_IDS
docker compose up --build   # db → миграции+seed → bot + api
```

Локально без Docker:

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
export DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/bankintel
alembic upgrade head && bankintel seed
bankintel bot                       # нужен BOT_TOKEN
uvicorn bankintel.api.main:app      # GET /health
```

## Тесты

```bash
pytest                                              # SQLite, без внешних сервисов
TEST_POSTGRES_URL=postgresql://u:p@host/db pytest   # + миграции на PostgreSQL
```

## Что нужно от вас

- **`BOT_TOKEN`** — создать бота у @BotFather.
- **`ALLOWED_TELEGRAM_IDS`** — ваши Telegram ID (узнать у @userinfobot). Пустой список = бот никому не отвечает.
- **Ручное подтверждение** доменов и присутствия банков в ЛНР (`domain_verified`, `lnr_presence_verified`).
- На этапе 3: `OPENAI_API_KEY` (в API уходят только публичные тексты официальных страниц).

Подробности: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), правила для агентов — [AGENTS.md](AGENTS.md).
