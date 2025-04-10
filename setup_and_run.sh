#!/bin/bash

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Install or update packages from requirements.txt
echo "Installing required packages..."
pip install -r requirements.txt

# Run the application on port 5001
echo "Starting the application on port 5001..."
export PORT=5001
python app.py 