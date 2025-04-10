#!/bin/bash

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Install or update packages from requirements.txt
echo "Installing required packages..."
pip install -r requirements.txt

# Run the application
echo "Starting the application..."
python app.py 