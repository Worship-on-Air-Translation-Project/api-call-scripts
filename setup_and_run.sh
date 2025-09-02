#!/bin/bash
set -e

echo "Checking for Python3..."
if ! command -v python3 &> /dev/null
then
    echo "Python3 not found. Installing with Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew install python
fi

echo "Checking for pip..."
if ! command -v pip3 &> /dev/null
then
    echo "pip3 not found. Installing..."
    curl https://bootstrap.pypa.io/get-pip.py -o get-pip.py
    python3 get-pip.py
fi

echo "Installing required Python packages..."
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt

# Kill any process already using port 8000
if lsof -ti:8000 >/dev/null; then
    echo "Port 8000 is in use. Killing old process..."
    kill -9 $(lsof -ti:8000)
fi

echo "Starting server"
python3 translator-app.py &

SERVER_PID=$!

# Wait for server to start
sleep 3

echo "Opening website"
open static/index.html

# Kill server when script exits
trap "echo 'Stopping server...'; kill -9 $SERVER_PID" EXIT
wait $SERVER_PID