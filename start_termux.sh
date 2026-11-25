#!/bin/bash
# AwareNet — Termux Launcher Script
# This script automates starting the AwareNet server on Android.

# Set the project directory automatically
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "═══════════════════════════════════════════════════════════"
echo "      AwareNet— Automated Launcher Script By Houwas        "
echo "═══════════════════════════════════════════════════════════"

# Check for Python dependencies
if ! command -v python &> /dev/null
then
    echo "[!] Python not found. Please install it: 'pkg install python'"
    exit
fi

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    echo "[*] Activating virtual environment..."
    source .venv/bin/activate
fi

# Ensure Python dependencies are installed
echo "[*] Checking dependencies..."
pip install -r requirements.txt --quiet 2>/dev/null || pip install flask flask-socketio pyotp qrcode[pil] --quiet

# Run the server
echo "[*] Launching AwareNet server on 127.0.0.1:5000..."
python app.py
