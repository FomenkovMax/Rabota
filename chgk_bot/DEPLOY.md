# DEPLOY — как запустить, обновить и починить

Для новичка. Все команды выполняются **на сервере** (VPS, Ubuntu 22.04/24.04), от root. Секреты (токен бота, ключ API, пароли) **вставляй только в терминал сервера** и никому не присылай.

## Что где работает
| Сервис | Что делает |
|---|---|
| `caddy` | Сайт Mini App + HTTPS (сертификат выпускается сам) |
| `backend` | Игра, API, WebSocket |
| `chgk-bot` | Telegram-бот (чат-игра, кнопка «Открыть игру») |
| `postgres` | База данных |

Папка проекта: `/opt/rabota/chgk_bot`. Настройки: файл `.env` рядом (права 600). Копии базы: `/opt/rabota/backups`.

## 1. Первый запуск
1. Заведи бота у @BotFather, возьми токен. Узнай свой Telegram ID (бот `/myid`, либо @userinfobot).
2. Открой у хостера порты **80 и 443**.
3. Запусти одной командой:
   ```
   bash <(curl -fsSL https://raw.githubusercontent.com/FomenkovMax/Rabota/claude/gracious-lovelace-w0b4kc/chgk_bot/deploy/setup.sh)
   ```
   Скрипт сам поставит Docker, создаст swap 2 ГБ, сгенерирует пароль базы и `JWT_SECRET`, определит адрес `https://<IP-через-дефисы>.sslip.io`, соберёт и запустит всё и включит ежедневный бэкап.
4. Проверка: `curl https://<адрес>/api/health` → `{"ok":true,"questions":…}`.
5. В Telegram: открой бота → `/start` → «🎮 Открыть игру».

Первая сборка на 1 vCPU занимает несколько минут — это нормально.

## 2. Настройки (`.env`)
Редактировать: `nano /opt/rabota/chgk_bot/.env`, затем применить: `cd /opt/rabota/chgk_bot && docker compose up -d`.
Главные: `BOT_TOKEN`, `ADMIN_ID`, `ALLOWED_IDS` / `ALLOWED_CHATS` (кто может играть; пусто = всем), `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`. Полный список с пояснениями — `.env.example`.
Названия наград, лиг и ачивок — `config/brand.json` (после правки: `docker compose up -d --build backend`).

## 3. Обновление
```
bash /opt/rabota/chgk_bot/deploy/setup.sh
```
Скрипт скачает свежий код, пересоберёт и перезапустит. Базу и `.env` не трогает; миграции базы применяются сами.

## 4. Откат
Если после обновления что-то сломалось:
```
cd /opt/rabota && git log --oneline | head        # найди нужный коммит
git checkout <коммит>
cd chgk_bot && docker compose up -d --build
```
Если сломалась база — восстанови из копии (см. ниже).

## 5. Логи и состояние
```
cd /opt/rabota/chgk_bot
docker compose ps                      # что запущено
docker compose logs -f backend         # логи бэкенда (Ctrl+C — выйти)
docker compose logs --tail 100 chgk-bot caddy
```
Логи ротируются сами (3 файла по 10 МБ на сервис). Контейнеры перезапускаются автоматически после сбоя и перезагрузки сервера.

## 6. Бэкапы
- Автоматически: каждый день в 04:15, хранится 7 последних копий в `/opt/rabota/backups`. Журнал: `/var/log/chgk-backup.log`.
- Вручную сейчас: `bash /opt/rabota/chgk_bot/deploy/backup.sh`.
- Восстановление: `bash /opt/rabota/chgk_bot/deploy/restore.sh /opt/rabota/backups/<файл>.sql.gz` (спросит подтверждение; текущие данные будут заменены).
- Копии лежат на том же сервере — раз в неделю скачивай свежую себе (`scp root@<сервер>:/opt/rabota/backups/<файл> .`).

## 7. Админ-функции
В Mini App (только для `ADMIN_ID`): меню «🛠 Вопросы» — поиск, скрыть/вернуть/удалить вопрос, добавить вопрос, пакетная загрузка JSON/CSV (кнопка «Проверить» покажет ошибки до загрузки). Импорт вопросов iqga.me: `docker compose exec backend python -m bot.import_iqga`.

## 8. Частые проблемы
| Симптом | Что делать |
|---|---|
| Сайт не открывается / нет HTTPS | Порты 80/443 закрыты у хостера; `docker compose logs caddy`. Лимиты Let's Encrypt для sslip.io общие — если не выпускается, возьми свой домен: `PUBLIC_HOST=ваш.домен` в `.env`, направь A-запись на IP, `docker compose up -d` |
| «Игра только для участников команды» | Человек не в группе из `ALLOWED_CHATS`; бот должен быть в этой группе |
| Сборка падает по памяти | Проверь `swapon --show` (должен быть 2 ГБ); повтори `setup.sh` |
| Судья «не ответил / спорно» | Ключ API или провайдер тормозит: `docker compose exec backend python -m bot.check_llm` |
| «Не удалось отправить карточку» | Напиши боту `/start` в личке |
| Бот не отвечает в группе | Privacy mode в @BotFather выключить, бота добавить заново |

## 9. Безопасность
- `.env` не коммитить (он в `.gitignore`); токен и ключ API, попавшие в чат, перевыпусти.
- Вопросы с iqga.me — материалы авторов, только для тренировки команды: не публикуй их и держи доступ закрытым (`ALLOWED_CHATS`).
