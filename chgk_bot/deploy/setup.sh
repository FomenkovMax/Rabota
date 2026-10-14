#!/usr/bin/env bash
# Установка ЧГК-бота на чистый Ubuntu 22.04/24.04 одной командой (запускать от root):
#   bash <(curl -fsSL https://raw.githubusercontent.com/FomenkovMax/Rabota/claude/gracious-lovelace-w0b4kc/chgk_bot/deploy/setup.sh)
# Секреты вводятся скрытно и сохраняются только в /opt/rabota/chgk_bot/.env (права 600).
set -euo pipefail

REPO="https://github.com/FomenkovMax/Rabota.git"
BRANCH="${BRANCH:-claude/gracious-lovelace-w0b4kc}"
DIR=/opt/rabota

[ "$(id -u)" -eq 0 ] || { echo "Запусти от root (или через sudo)"; exit 1; }

echo "==> Ставлю Docker и git"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq docker.io docker-compose-v2 git ca-certificates >/dev/null
systemctl enable --now docker >/dev/null

echo "==> Скачиваю проект ($BRANCH)"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch -q origin "$BRANCH" && git -C "$DIR" checkout -q "$BRANCH" && git -C "$DIR" pull -q origin "$BRANCH"
else
  git clone -q --branch "$BRANCH" --depth 1 "$REPO" "$DIR"
fi
cd "$DIR/chgk_bot"

if [ ! -f .env ]; then
  echo "==> Настройка. Ввод скрытый — символы не отображаются."
  read -rsp "BOT_TOKEN (от @BotFather): " BOT_TOKEN; echo
  read -rsp "ANTHROPIC_API_KEY (Enter — пропустить): " API_KEY; echo
  BASE_URL=""; AUTH_MODE=""
  if [ -n "$API_KEY" ]; then
    read -rp "ANTHROPIC_BASE_URL (Enter — официальный API; для LiteAI: https://api.liteai.tech/anthropic): " BASE_URL
    read -rp "Режим авторизации x-api-key или bearer [x-api-key]: " AUTH_MODE
  fi
  read -rp "CLAUDE_MODEL [claude-sonnet-5-5]: " MODEL
  read -rp "ADMIN_ID (твой Telegram ID): " ADMIN_ID
  umask 077
  {
    echo "BOT_TOKEN=$BOT_TOKEN"
    echo "ANTHROPIC_API_KEY=$API_KEY"
    [ -n "$BASE_URL" ] && echo "ANTHROPIC_BASE_URL=$BASE_URL"
    echo "ANTHROPIC_AUTH_MODE=${AUTH_MODE:-x-api-key}"
    echo "CLAUDE_MODEL=${MODEL:-claude-sonnet-5-5}"
    echo "ADMIN_ID=${ADMIN_ID:-0}"
  } > .env
  chmod 600 .env
else
  echo "==> .env уже есть — оставляю как есть"
fi

echo "==> Собираю и запускаю"
docker compose up -d --build

if grep -q '^ANTHROPIC_API_KEY=.\+' .env; then
  echo "==> Проверяю ключ и модель"
  docker compose run --rm chgk-bot python -m bot.check_llm || echo "(проверка не прошла — см. сообщение выше)"
fi

echo
echo "Готово. Логи:      cd $DIR/chgk_bot && docker compose logs -f"
echo "Обновить бота:     bash $DIR/chgk_bot/deploy/setup.sh"
echo "Остановить:        cd $DIR/chgk_bot && docker compose down"
