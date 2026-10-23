# Banking Intelligence AI

Telegram-бот для конкурентного анализа розничных банковских продуктов (вклады, накопительные счета, акции) на территории ЛНР: Сбер, ПСБ, ВТБ, Генбанк, ЦМР банк.

> ⚠️ **Статус: демо-прототип, этап 1 из 7.** Данные о ставках и акциях **ещё не собираются** — в БД есть только реестр банков. Бот намеренно не показывает никаких цифр. Домены банков и присутствие в ЛНР помечены как **не подтверждённые** до ручной проверки.

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
| Сбор данных, AI, сравнение, отчёты, мониторинг | ❌ этапы 2–7, см. [PLANS.md](PLANS.md) |

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
