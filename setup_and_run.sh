#!/bin/bash
set -e

echo "Checking for Python3..."
if ! command -v python3 &> /dev/null
then
    echo "Python3 not found. Installing with Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    brew install python
fi

# Kill any process already using port 8000
if lsof -ti:8000 >/dev/null; then
    echo "Port 8000 is in use. Killing old process..."
    kill -9 $(lsof -ti:8000)
fi

echo "Starting server"
python3 translator-app.py &

# Save server PID so we can kill it later if needed
SERVER_PID=$!

# Wait for server to start
sleep 3

echo "Opening website"
open index.html

# Wait until user closes terminal, then stop server
trap "echo 'Stopping server...'; kill -9 $SERVER_PID" EXIT
wait $SERVER_PID