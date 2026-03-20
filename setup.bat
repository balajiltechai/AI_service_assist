@echo off
echo Setting up AI Service Documentation & Change Intelligence...
cd /d %~dp0

python -m venv venv
call venv\Scripts\activate.bat

pip install -r backend/requirements.txt

if not exist .env (
    copy .env.example .env
    echo .env file created. Edit it and add your ANTHROPIC_API_KEY.
)

echo.
echo Setup complete!
echo 1. Edit .env and set your ANTHROPIC_API_KEY
echo 2. Run: python run.py
echo 3. Open: http://localhost:8000
pause
