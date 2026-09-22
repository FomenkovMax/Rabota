@echo off
rem Еженедельный запуск сбора для Планировщика заданий Windows.
rem
rem Как поставить на расписание:
rem   1. Win+R → taskschd.msc → «Создать задачу»
rem   2. Вкладка «Действия» → «Создать»:
rem        Программа:        C:\путь\psb-sber-compare\weekly_run.bat
rem        Рабочая папка:    C:\путь\psb-sber-compare
rem   3. Вкладка «Триггеры» → еженедельно, понедельник, 07:00
rem
rem Лог каждого запуска складывается в data\run_ГГГГ-ММ-ДД.log

setlocal
cd /d "%~dp0"

if not exist "data" mkdir "data"

rem Дата в формате ГГГГ-ММ-ДД без зависимости от локали системы.
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"') do set RUNDATE=%%d
set LOGFILE=data\run_%RUNDATE%.log

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=python
)

echo [%date% %time%] Запуск сбора >> "%LOGFILE%"
"%PYTHON%" run.py collect >> "%LOGFILE%" 2>&1
set CODE=%ERRORLEVEL%

if %CODE% NEQ 0 (
    echo [%date% %time%] ОШИБКА, код %CODE% >> "%LOGFILE%"
    exit /b %CODE%
)

echo [%date% %time%] Готово. Отчёт: data\dashboard.html >> "%LOGFILE%"
exit /b 0
