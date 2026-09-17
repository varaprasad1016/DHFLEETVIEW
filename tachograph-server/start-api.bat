@echo off
cd /d C:\tachograph-server
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> D:\DHFleetViewData\tacho\logs\api.log 2>&1
