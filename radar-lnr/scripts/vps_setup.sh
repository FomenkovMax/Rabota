#!/usr/bin/env bash
# Первичная настройка на VPS (Ubuntu 22.04/24.04). Запускать из папки проекта:  bash scripts/vps_setup.sh
# Делает: ставит Docker (если нет), готовит папку data, проверяет .env, собирает и запускает бота.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v docker >/dev/null 2>&1; then
  echo "▶ Docker не найден. Ставлю официальным скриптом get.docker.com (нужен sudo)…"
  curl -fsSL https://get.docker.com | sudo sh
  sudo systemctl enable --now docker       # автозапуск Docker при загрузке сервера
  sudo usermod -aG docker "$USER" || true
  echo "ℹ Если дальше будет 'permission denied' — выйди и зайди по SSH заново (группа docker применится)."
fi

# Если .env нет — создаём заготовку и просим заполнить (запускаться без секретов нет смысла)
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "✋ Создал .env из шаблона. Заполни его:  nano .env   — затем запусти этот скрипт ещё раз."
  exit 1
fi
chmod 600 .env

# Папка с данными принадлежит пользователю внутри контейнера (uid 10001)
mkdir -p data
sudo chown -R 10001:10001 data

DC="docker compose"
$DC version >/dev/null 2>&1 || DC="sudo docker compose"
$DC up -d --build
echo
$DC ps
echo
echo "✅ Готово. Логи:  $DC logs -f     Остановить:  $DC down"
echo "   Напиши боту /start, затем /myid; в группе — /chatid."
