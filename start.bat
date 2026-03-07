@echo off
echo Starting Mothership Node...
echo ---------------------------
py -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
pause
