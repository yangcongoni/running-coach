@echo off
cd /d "%~dp0"
if exist "work\garmin-api-trial\.venv\Scripts\python.exe" (
 "work\garmin-api-trial\.venv\Scripts\python.exe" -B -X utf8 "outputs\local_archive\web_second_factor.py"
) else (
 python -B -X utf8 "outputs\local_archive\web_second_factor.py"
)
if errorlevel 1 pause
