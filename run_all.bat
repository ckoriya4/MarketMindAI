@echo off
rem ------------------------------------------------------------
rem run_all.bat – one‑click wrapper for run_all.py
rem ------------------------------------------------------------

rem Change to the directory where this batch lives (project root)
cd /d "%~dp0"

rem Activate the virtual environment
call .venv\Scripts\activate.bat

rem Run the Python driver script
python run_all.py %*

