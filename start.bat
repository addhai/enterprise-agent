@echo off
chcp 65001 >nul
echo.
echo ========================================
echo   Enterprise Agent - 一键启动
echo ========================================
echo.

REM 检查 Docker 是否运行
docker info >nul 2>&1
if errorlevel 1 (
    echo [错误] Docker 未启动，请先打开 Docker Desktop
    pause
    exit /b 1
)

echo [1/3] 正在构建后端镜像...
docker compose build fastapi
if errorlevel 1 (
    echo [错误] 构建失败
    pause
    exit /b 1
)
echo.

echo [2/3] 正在启动服务...
docker compose up -d
if errorlevel 1 (
    echo [错误] 启动失败
    pause
    exit /b 1
)
echo.

echo [3/3] 等待服务就绪...
timeout /t 10 /nobreak >nul
echo.

echo ========================================
echo   启动成功！
echo ========================================
echo.
echo   打开浏览器访问: http://localhost
echo.
echo   查看日志: docker compose logs -f
echo   停止服务: docker compose down
echo.
timeout /t 3
start http://localhost
