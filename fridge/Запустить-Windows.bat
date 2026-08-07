@echo off
chcp 65001 >nul
title Что приготовить — счётчик калорий по фото холодильника
cd /d "%~dp0"
cls

where node >nul 2>nul
if errorlevel 1 (
  echo   Не найден Node.js — без него приложение не запустится.
  echo   Сейчас откроется сайт nodejs.org: скачайте версию LTS,
  echo   установите её и запустите этот файл снова.
  echo.
  start "" https://nodejs.org/
  pause
  exit /b 1
)

if not exist node_modules (
  echo   Первый запуск: устанавливаю зависимости, это займёт минуту-две...
  echo.
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    echo.
    echo   Установка не удалась. Проверьте интернет и попробуйте снова.
    pause
    exit /b 1
  )
  cls
)

node server.js
echo.
pause
