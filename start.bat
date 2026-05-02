@echo off
title TradingAgents Web UI
echo ========================================
echo   TradingAgents Web UI
echo   Backend API : http://localhost:8877
echo   Frontend    : http://localhost:5177
echo ========================================
echo.

:: Start backend API server
start "TradingAgents API" cmd /k "cd /d %~dp0 && python -m uvicorn backend.main:app --host 0.0.0.0 --port 8877 --factory"

:: Wait a moment for backend to start
timeout /t 3 /nobreak >nul

:: Start frontend dev server
start "TradingAgents Frontend" cmd /k "cd /d %~dp0\frontend && npm run dev"

echo Both servers starting...
echo   Backend API : http://localhost:8877
echo   Frontend    : http://localhost:5177
echo.
echo Close the two spawned terminal windows to stop.
