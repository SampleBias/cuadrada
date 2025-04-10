@echo off
setlocal

REM Activate virtual environment if it exists
if exist venv\Scripts\activate.bat (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
)

REM Install or update packages from requirements.txt
echo Installing required packages...
pip install -r requirements.txt

REM Run the application on port 5001
echo Starting the application on port 5001...
set PORT=5001
python app.py

pause
 