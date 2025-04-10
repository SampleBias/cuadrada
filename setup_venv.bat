@echo off
SETLOCAL

REM Create virtual environment if it doesn't exist
IF NOT EXIST venv (
    echo Creating virtual environment...
    python -m venv venv
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Install dependencies
echo Installing dependencies...
pip install -r requirements.txt

echo Virtual environment setup complete. Use 'venv\Scripts\activate.bat' to activate it in future.
ENDLOCAL 