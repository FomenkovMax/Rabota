#!/usr/bin/env bash
# Обновление на VPS: подтянуть код из git и перезапустить.   bash scripts/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
git pull --ff-only
DC="docker compose"
$DC version >/dev/null 2>&1 || DC="sudo docker compose"
$DC up -d --build
docker image prune -f >/dev/null 2>&1 || true     # убираем старые слои образов
$DC ps
echo "✅ Обновлено. Логи:  $DC logs -f --tail=50"
