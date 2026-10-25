@echo off
setlocal
cd /d "%~dp0"
echo Starting PageWeaver at http://127.0.0.1:8080
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" image_to_pdf_server.py
) else (
    python image_to_pdf_server.py
)
pause
