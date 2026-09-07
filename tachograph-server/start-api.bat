@echo off
cd /d C:\tachograph-server
.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000 >> .runtime\api.log 2>&1
