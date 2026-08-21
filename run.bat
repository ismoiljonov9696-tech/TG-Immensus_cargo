@echo off
REM Windows'da ishga tushirish. Kompyuter yoqilgan bo'lishi kerak.
REM Birinchi marta:  python -m venv .venv  &&  .venv\Scripts\pip install -r requirements.txt
cd /d "%~dp0"
.venv\Scripts\python.exe -m src.scheduler
pause
