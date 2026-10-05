#!/usr/bin/env bash
# Записать секрет в .env агента без ручного редактирования файла: lnrbank-secret ИМЯ
set -euo pipefail
NAME="${1:-}"
case "$NAME" in
  GIGACHAT_CREDENTIALS|GIGACHAT_SCOPE|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID|LNRBANK_CA_BUNDLE) ;;
  *) echo "Использование: lnrbank-secret GIGACHAT_CREDENTIALS|GIGACHAT_SCOPE|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID" >&2; exit 1 ;;
esac
ENV_FILE="${LNRBANK_ENV:-/home/lnrbank/Rabota/lnr-bank-agent/.env}"
[ -f "$ENV_FILE" ] || { echo "Нет $ENV_FILE — сначала запусти установку" >&2; exit 1; }
read -r -s -p "Вставь значение $NAME (ввод не отображается): " VALUE; echo
[ -n "$VALUE" ] || { echo "Пустое значение — ничего не изменено" >&2; exit 1; }
case "$VALUE" in *$'\n'*|*'"'*) echo "Недопустимые символы в значении" >&2; exit 1 ;; esac
TMP="$(mktemp)"
grep -v "^$NAME=" "$ENV_FILE" > "$TMP" || true
printf '%s=%s\n' "$NAME" "$VALUE" >> "$TMP"
cat "$TMP" > "$ENV_FILE"   # перезапись содержимого сохраняет владельца и права 600
rm -f "$TMP"
echo "✓ $NAME записан"
