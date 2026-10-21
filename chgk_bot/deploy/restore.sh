#!/usr/bin/env bash
# Восстановление базы из копии: bash deploy/restore.sh /opt/rabota/backups/chgk-ГГГГММДД-ЧЧММСС.sql.gz
# ВНИМАНИЕ: текущие данные в базе будут заменены данными из копии.
set -euo pipefail
FILE="${1:-}"
[ -f "$FILE" ] || { echo "Укажи файл копии. Доступные:"; ls -1t /opt/rabota/backups/chgk-*.sql.gz 2>/dev/null | head; exit 1; }
cd "${APP_DIR:-/opt/rabota/chgk_bot}"
read -rp "Заменить текущую базу данными из $FILE? Напиши 'да': " OK
[ "$OK" = "да" ] || { echo "Отменено"; exit 1; }
docker compose stop backend chgk-bot
gunzip -c "$FILE" | docker compose exec -T postgres psql -U chgk -d chgk -v ON_ERROR_STOP=1 -q
docker compose start backend chgk-bot
echo "Восстановлено из $FILE"
