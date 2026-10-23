# Архитектура

```
config/banks.yaml, sources.yaml ──► registry.loader ──► БД: banks, sources
                                                           │
 Telegram ◄── bot (aiogram) ◄── views ◄───────────────────┤
 HTTP     ◄── api  (FastAPI)                               │
                                                           ▼
 официальные сайты ──► Fetcher ──► BankAdapter.parse ──► documents, product_snapshots,
                      (этап 2)     (по банку)             region_availability, change_events
                                                           │
                                          AI-извлечение (3) → сравнение (4) → отчёты (5)
```

## Модули (`src/bankintel`)

| Модуль | Роль |
|---|---|
| `config.py` | Настройки из окружения (pydantic-settings), секреты — `SecretStr`. |
| `domain/enums.py` | Статусы: доступность в ЛНР, полнота сбора, исход загрузки. |
| `db/models.py` | Схема. Миграции — `migrations/`. |
| `registry/` | Pydantic-валидация конфигов и идемпотентная синхронизация в БД. |
| `sources/base.py` | `BankAdapter` (шаблонный метод `collect`: fetch → parse → статус), `Fetcher` (протокол), реестр адаптеров. Адаптеры независимы друг от друга. |
| `bot/` | `views` (тексты), `handlers` (команды), `access` (allowlist). |
| `api/` | `/health`. |

## Ключевые решения

- **Происхождение данных**: `ProductSnapshot.document_id` → `Document(url, fetched_at, sha256, storage_path)`; `evidence` хранит цитаты. Значение без документа в БД попасть не может.
- **Доступность в ЛНР** — отдельная сущность `RegionAvailability` с цитатой; по умолчанию `unknown`.
- **Неполнота — часть данных**: `FetchAttempt` пишется всегда; `CollectionResult.status` ∈ ok/partial/failed/not_implemented.
- **Верификация человеком**: `Bank.domain_verified`, `lnr_presence_verified`; `Source.status = todo` блокирует сбор. `sync_registry` не сбрасывает подтверждения, сделанные вручную.
- **Официальные домены**: источник с чужим/похожим доменом не пройдёт валидацию конфига (тесты на lookalike-домены).
- **Безопасный доступ к боту**: пустой allowlist — отказ всем.
- **БД**: PostgreSQL в проде, SQLite (aiosqlite) в тестах; JSON-колонки — переносимый `sa.JSON`.
