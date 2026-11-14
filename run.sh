#!/data/data/com.termux/files/usr/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d .venv ]; then python -m venv .venv; fi
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
exec python app.py
