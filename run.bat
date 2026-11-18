@echo off
title MarketMind AI Runner
echo ========================================================
echo          Starting MarketMind AI System...
echo ========================================================

echo [1/2] Starting FastAPI Backend on port 8000...
start "MarketMind AI - Backend" cmd /k "cd /d %~dp0 && .\.venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload"

echo [2/2] Starting React Vite Frontend on port 5173...
start "MarketMind AI - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ========================================================
echo  All systems started!
echo  Frontend URL: http://localhost:5173/
echo  Backend URL:  http://127.0.0.1:8000/
echo  API Docs:     http://127.0.0.1:8000/docs
echo ========================================================

