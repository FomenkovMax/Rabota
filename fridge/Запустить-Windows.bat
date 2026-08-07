@echo off
chcp 65001 >nul
title Что приготовить — счётчик калорий по фото холодильника
cd /d "%~dp0"
cls

where node >nul 2>nul
if errorlevel 1 goto nonode
if not exist node_modules goto install

:run
echo.
echo   Запускаю...
node server.js
echo.
echo   Приложение остановлено.
pause
exit /b 0

:install
echo.
echo   Первый запуск: устанавливаю зависимости, это займёт минуту-две...
echo.
call npm install --no-audit --no-fund
if errorlevel 1 goto noinstall
cls
goto run

:nonode
echo.
echo   ====================================================
echo     Не найден Node.js — без него приложение не пойдёт
echo   ====================================================
echo.
where winget >nul 2>nul
if errorlevel 1 goto manual
echo   Могу установить Node.js прямо сейчас (через штатный
echo   установщик Windows). Это займёт пару минут.
echo.
set ANSWER=
set /p ANSWER=  Установить? Введите y и нажмите Enter (или n, чтобы отказаться):
if /i "%ANSWER%"=="y" goto winget
goto manual

:winget
echo.
echo   Устанавливаю Node.js, подождите...
echo.
winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
echo.
echo   Готово. Теперь ЗАКРОЙТЕ это окно и запустите файл
echo   «Запустить-Windows.bat» ещё раз — Node.js подхватится.
echo.
pause
exit /b 0

:manual
echo   Что сделать:
echo     1. Сейчас откроется сайт nodejs.org
echo     2. Нажмите большую зелёную кнопку LTS и скачайте установщик
echo     3. Установите его, всё время нажимая «Далее»
echo     4. Запустите этот файл ещё раз
echo.
start "" https://nodejs.org/
pause
exit /b 1

:noinstall
echo.
echo   Не удалось установить зависимости.
echo   Проверьте интернет и запустите этот файл ещё раз.
echo.
pause
exit /b 1
