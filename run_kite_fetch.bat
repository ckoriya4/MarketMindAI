@echo off
rem ------------------------------------------------------------
rem  run_kite_fetch.bat
rem  • Activates the project virtual‑env (.venv)
rem  • Executes the Python helper that:
rem      – opens the Kite login URL in the default browser,
rem      – asks you for the request token,
rem      – writes the token to .env,
rem      – fetches the live option‑chain and prints JSON.
rem ------------------------------------------------------------

rem Change to the directory that contains this script (project root)
cd /d "%~dp0"

rem Activate the virtual environment
call .venv\Scripts\activate.bat

rem Run the fetch script – forward any arguments you pass to this .bat file
python backend\run_kite_fetch.py %*

