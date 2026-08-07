#!/bin/bash
# Двойной клик по этому файлу запускает приложение и открывает его в браузере.
# macOS: если система ругается на неизвестного разработчика — правый клик → «Открыть».
# Linux: в свойствах файла отметьте «Разрешить запуск» и запустите двойным кликом.

cd "$(dirname "$0")" || exit 1
clear

pause_and_exit() {
  echo ""
  read -r -p "  Нажмите Enter, чтобы закрыть окно..." _
  exit "$1"
}

if ! command -v node >/dev/null 2>&1; then
  echo "  Не найден Node.js — без него приложение не запустится."
  echo "  Скачайте версию LTS с https://nodejs.org/, установите"
  echo "  и запустите этот файл снова."
  command -v open >/dev/null 2>&1 && open "https://nodejs.org/" 2>/dev/null
  pause_and_exit 1
fi

NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)"
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "  Установлен Node.js $(node -v), а нужен 20 или новее."
  echo "  Обновите его с https://nodejs.org/ и запустите файл снова."
  pause_and_exit 1
fi

if [ ! -d node_modules ]; then
  echo "  Первый запуск: устанавливаю зависимости, это займёт минуту-две…"
  echo ""
  if ! npm install --no-audit --no-fund; then
    echo ""
    echo "  Установка не удалась. Проверьте интернет и попробуйте снова."
    pause_and_exit 1
  fi
  clear
fi

node server.js
pause_and_exit 0
