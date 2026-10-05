#!/usr/bin/env bash
# Установка и обновление агента на VPS с Ubuntu (22.04/24.04). Запуск от root, повторный запуск безопасен.
#   curl -fsSL https://raw.githubusercontent.com/FomenkovMax/Rabota/ccr-d13b0862-srpe73/lnr-bank-agent/scripts/deploy.sh | sudo bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/FomenkovMax/Rabota.git}"
BRANCH="${BRANCH:-ccr-d13b0862-srpe73}"
AGENT_USER="${AGENT_USER:-lnrbank}"
AGENT_HOME="/home/$AGENT_USER"
REPO_DIR="$AGENT_HOME/Rabota"
APP_DIR="$REPO_DIR/lnr-bank-agent"

step() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
# Если сервер ходит в интернет через прокси, его настройки передаются пользователю агента.
PASS_ENV="HTTPS_PROXY,https_proxy,HTTP_PROXY,http_proxy,NO_PROXY,no_proxy,SSL_CERT_FILE,UV_NATIVE_TLS,UV_SYSTEM_CERTS,NODE_EXTRA_CA_CERTS"
as_agent() { sudo -u "$AGENT_USER" -H --preserve-env="$PASS_ENV" "$@"; }

[ "$(id -u)" -eq 0 ] || { echo "Запусти от root: sudo bash deploy.sh" >&2; exit 1; }
grep -qi ubuntu /etc/os-release || echo "⚠ Скрипт проверен на Ubuntu; на другой ОС возможны отличия."

step "1/8 Системные пакеты"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q git curl ca-certificates openssl libnss3-tools cron sudo

step "2/8 Часовой пояс Europe/Moscow (для расписания)"
timedatectl set-timezone Europe/Moscow 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Moscow /etc/localtime

step "3/8 Пользователь $AGENT_USER (без прав администратора)"
id "$AGENT_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$AGENT_USER"

step "4/8 Код из $REPO_URL ($BRANCH)"
if [ -d "$REPO_DIR/.git" ]; then
  as_agent git -C "$REPO_DIR" fetch -q origin "$BRANCH"
  as_agent git -C "$REPO_DIR" checkout -q "$BRANCH"
  # Только fast-forward: локальные правки (например, playbook) не затираются.
  as_agent git -C "$REPO_DIR" merge -q --ff-only "origin/$BRANCH" \
    || { echo "✗ Есть локальные изменения, обновление остановлено. Покажи вывод в чате." >&2; exit 1; }
else
  as_agent git clone -q --depth 50 --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
fi

step "5/8 uv и зависимости Python"
as_agent bash -lc 'command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh -s -- -q'
UV="$AGENT_HOME/.local/bin/uv"
as_agent bash -c "cd '$APP_DIR' && '$UV' sync -q --no-dev"

step "6/8 Браузер Chromium для Playwright"
"$APP_DIR/.venv/bin/playwright" install-deps chromium >/dev/null
as_agent bash -c "cd '$APP_DIR' && .venv/bin/playwright install chromium"

step "7/8 Сертификат Минцифры"
LNRBANK_USER="$AGENT_USER" bash "$APP_DIR/scripts/install_certs.sh"

step "8/8 Секреты, команда lnrbank, расписание"
if [ ! -f "$APP_DIR/.env" ]; then
  as_agent cp "$APP_DIR/.env.example" "$APP_DIR/.env"
fi
chmod 600 "$APP_DIR/.env"
as_agent mkdir -p "$APP_DIR/data/logs"
cat > /usr/local/bin/lnrbank <<WRAP
#!/usr/bin/env bash
# Запуск агента от пользователя $AGENT_USER из любой папки.
exec sudo -u $AGENT_USER -H bash -c 'cd "$APP_DIR" && exec "$UV" run --no-dev lnrbank "\$@"' lnrbank "\$@"
WRAP
chmod 755 /usr/local/bin/lnrbank
install -m 755 "$APP_DIR/scripts/set_secret.sh" /usr/local/bin/lnrbank-secret
sed "s|@APP_DIR@|$APP_DIR|g; s|@UV@|$UV|g" "$APP_DIR/scripts/crontab.example" | crontab -u "$AGENT_USER" -
systemctl enable --now cron >/dev/null 2>&1 || service cron start >/dev/null 2>&1 || true

step "Проверка TLS"
lnrbank check --tls-only || true

cat <<'DONE'

✅ Установка завершена. Дальше:
  1. Секреты:  lnrbank-secret GIGACHAT_CREDENTIALS
               lnrbank-secret TELEGRAM_BOT_TOKEN
               lnrbank-secret TELEGRAM_CHAT_ID
  2. Проверка: lnrbank check
  3. Пришли вывод `lnrbank check` в чат — донастроим выбор ЛНР.
  Обновление агента — повторить ту же команду установки.
DONE
