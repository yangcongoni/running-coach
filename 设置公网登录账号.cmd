@echo off
cd /d "%~dp0"
python -B -X utf8 "%~dp0outputs\local_archive\web_account.py"
if errorlevel 1 pause
