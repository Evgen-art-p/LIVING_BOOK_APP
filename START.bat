@echo off
chcp 65001 > nul
echo 🚀 Запуск Грондхейма v4.0...

:: 1. Запуск Маяка (Сервера)
:: Переходим в папку server и запускаем питон
start "ГРОНДХЕЙМ: МАЯК" cmd /k "cd /d %~dp0server && python beacon.py"

:: Ждем 3 секунды на прогрев
timeout /t 3

:: 2. Открываем Кабинет Родителя
start "" "%~dp0dashboard\index.html"

:: 3. Открываем Искорку
start "" "%~dp0player\index.html"

echo ✅ Все системы запущены.
pause