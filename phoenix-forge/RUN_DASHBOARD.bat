@echo off
call .venv\Scripts\activate.bat
start "Phoenix Forge" http://127.0.0.1:8787
uvicorn phoenix_forge.api.app:app --host 127.0.0.1 --port 8787
