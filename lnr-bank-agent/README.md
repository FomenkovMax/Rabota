# lnr-bank-agent

Локальный агент сравнения розничных продуктов банков в ЛНР: Сбер, ВТБ, ПСБ, Т-Банк.

ТЗ: `../work/lnr-bank-retail-agent/tech-spec.md`. Задачи: `../work/lnr-bank-retail-agent/tasks/`.

## Статус

Готова задача 1 — каркас, настройки, сертификат Минцифры, проверка TLS. Команды `check` (полная), `run`, `build` и `notify` появятся в задачах 5, 8 и 9.

## Установка (Linux или macOS)

```bash
cd lnr-bank-agent
uv sync                          # зависимости
bash scripts/install_certs.sh    # корень Минцифры: сверка отпечатка и установка
cp .env.example .env             # впиши ключ GigaChat и токен бота
chmod 600 .env
uv run lnrbank check --tls-only  # TLS к банкам и GigaChat
```

Нужен [uv](https://docs.astral.sh/uv/). Пошаговая инструкция для VPS с телефона появится в задаче 14.

## Зачем сертификат Минцифры

Сайты Сбера, ВТБ, ПСБ, Т-Банка и API GigaChat работают на сертификатах НУЦ Минцифры. Скрипт скачивает корень с gu-st.ru (CDN Госуслуг) и сверяет SHA-256 с закреплённым значением. Затем ставит корень в системное хранилище и в хранилище браузера и собирает CA-бандл `data/certs/ca-bundle.pem` для Python. Проверка сертификатов в коде не отключается — это проверяет тест.

## Настройки

- `config/settings.yaml` — банки, регион, пороги, сценарии, LLM, браузер, хранение. Без секретов.
- `config/parameters.yaml` — словарь параметров по блокам.
- `config/site_playbook.yaml` — шаги выбора ЛНР по сайтам (наполняется в задачах 5 и 6).
- `.env` — секреты: `GIGACHAT_CREDENTIALS`, `GIGACHAT_SCOPE`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## Проверки

```bash
uv run pytest -q
# хуки (запускать из корня репозитория):
uv run --project lnr-bank-agent pre-commit install -c lnr-bank-agent/.pre-commit-config.yaml
```

Pre-commit: gitleaks (поиск секретов), ruff (линт и формат), unit-тесты.
