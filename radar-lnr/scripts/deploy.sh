#!/usr/bin/env bash
# Заливка проекта с твоего компьютера на VPS без git (Linux / macOS / WSL / Git Bash).
#   bash scripts/deploy.sh user@1.2.3.4            — залить код и перезапустить
#   bash scripts/deploy.sh user@1.2.3.4 --env      — заодно залить локальный .env (секреты!)
#   bash scripts/deploy.sh user@1.2.3.4 logs       — смотреть логи
# Переменная REMOTE_DIR задаёт папку на сервере (по умолчанию ~/radar-lnr).
set -euo pipefail
HOST="${1:?Укажи сервер: bash scripts/deploy.sh user@host}"
ACTION="${2:-deploy}"
REMOTE_DIR="${REMOTE_DIR:-radar-lnr}"
cd "$(dirname "$0")/.."

if [ "$ACTION" = "logs" ]; then
  exec ssh "$HOST" "cd $REMOTE_DIR && docker compose logs -f --tail=100"
fi

echo "▶ Заливаю код в $HOST:$REMOTE_DIR (без .env, data, .venv)…"
tar czf - --exclude='.env' --exclude='.venv' --exclude='data' --exclude='__pycache__' --exclude='.git' \
    --exclude='.pytest_cache' . | ssh "$HOST" "mkdir -p $REMOTE_DIR && tar xzf - -C $REMOTE_DIR"

if [ "$ACTION" = "--env" ]; then
  echo "▶ Заливаю .env (права 600)…"
  scp .env "$HOST:$REMOTE_DIR/.env"
  ssh "$HOST" "chmod 600 $REMOTE_DIR/.env"
fi

echo "▶ Запускаю на сервере…"
ssh "$HOST" "cd $REMOTE_DIR && bash scripts/vps_setup.sh"
