#!/usr/bin/env bash
# Еженедельный запуск сбора для cron.
#
#   0 7 * * 1 /путь/psb-sber-compare/weekly_run.sh
#
# Лог каждого запуска — в data/run_ГГГГ-ММ-ДД.log

set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data
LOGFILE="data/run_$(date +%F).log"

PYTHON="python3"
[ -x ".venv/bin/python" ] && PYTHON=".venv/bin/python"

echo "[$(date '+%F %T')] Запуск сбора" >> "$LOGFILE"
if "$PYTHON" run.py collect >> "$LOGFILE" 2>&1; then
    echo "[$(date '+%F %T')] Готово. Отчёт: data/dashboard.html" >> "$LOGFILE"
else
    code=$?
    echo "[$(date '+%F %T')] ОШИБКА, код $code" >> "$LOGFILE"
    exit $code
fi
