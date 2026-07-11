@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   Enterprise Agent - 停止服务
echo ========================================
echo.

docker compose down

echo.
echo 服务已停止。
pause
