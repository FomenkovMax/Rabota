#!/usr/bin/env bash
# Резервная копия базы PostgreSQL: сжатый дамп в /opt/rabota/backups, хранится последние 7 штук.
# Запуск вручную: bash /opt/rabota/chgk_bot/deploy/backup.sh   (по расписанию его ставит setup.sh)
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/rabota/chgk_bot}"
OUT_DIR="${BACKUP_DIR:-/opt/rabota/backups}"
KEEP="${KEEP:-7}"
# чем снимать дамп (можно подменить в тестах)
DUMP_CMD="${DUMP_CMD:-docker compose exec -T postgres pg_dump -U chgk --clean --if-exists chgk}"

mkdir -p "$OUT_DIR"
cd "$APP_DIR"
FILE="$OUT_DIR/chgk-$(date +%Y%m%d-%H%M%S).sql.gz"
TMP="$FILE.part"
if ! $DUMP_CMD | gzip > "$TMP"; then
  rm -f "$TMP"; echo "Бэкап не удался" >&2; exit 1
fi
[ -s "$TMP" ] || { rm -f "$TMP"; echo "Бэкап пустой — не сохраняю" >&2; exit 1; }
mv "$TMP" "$FILE"
# удаляем всё, кроме последних $KEEP копий
ls -1t "$OUT_DIR"/chgk-*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "Готово: $FILE ($(du -h "$FILE" | cut -f1)); копий хранится: $(ls -1 "$OUT_DIR"/chgk-*.sql.gz | wc -l)"
