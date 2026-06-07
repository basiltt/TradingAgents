@echo off
title TradingAgents Web UI

:: SECURITY: bind to loopback by default. The trading endpoints have NO per-request
:: auth — the loopback bind IS the security boundary. Exposing them on 0.0.0.0 lets
:: any device on the network place real-money trades (directly, or via the frontend
:: dev proxy which forwards /api + /ws to the backend under a loopback Host). Override
:: with TRADINGAGENTS_BIND_HOST=0.0.0.0 ONLY behind a trusted network + an auth proxy.
:: Mirrors start.sh so Windows and *nix launchers share one security posture.
if not defined TRADINGAGENTS_BIND_HOST set "TRADINGAGENTS_BIND_HOST=127.0.0.1"
if not defined TRADINGAGENTS_PORT set "TRADINGAGENTS_PORT=8877"

echo ========================================
echo   TradingAgents Web UI
echo   Bind host   : %TRADINGAGENTS_BIND_HOST%
echo   Backend API : http://localhost:%TRADINGAGENTS_PORT%
echo   Frontend    : http://localhost:5177
echo ========================================
echo.

:: Start backend API server
start "TradingAgents API" cmd /k "cd /d %~dp0 && python -m uvicorn backend.main:create_app --host %TRADINGAGENTS_BIND_HOST% --port %TRADINGAGENTS_PORT% --factory --reload --reload-dir backend --reload-dir tradingagents"

:: Wait a moment for backend to start
timeout /t 3 /nobreak >nul

:: Start frontend dev server
start "TradingAgents Frontend" cmd /k "cd /d %~dp0\frontend && npm run dev -- --host %TRADINGAGENTS_BIND_HOST% --port 5177 --strictPort"

echo Both servers starting...
echo   Backend API : http://localhost:%TRADINGAGENTS_PORT%
echo   Frontend    : http://localhost:5177
echo.
echo Close the two spawned terminal windows to stop.
