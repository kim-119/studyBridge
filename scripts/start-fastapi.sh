#!/usr/bin/env bash
set -euo pipefail

FASTAPI_DIR="/home/ai07/capstoneLLM/fastapi"
PORT="${FASTAPI_PORT:-8000}"

cd "$FASTAPI_DIR"

if [ ! -d ".venv" ] || [ ! -f ".venv/bin/activate" ]; then
  rm -rf .venv
  python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip

if [ -f "requirements.txt" ]; then
  pip install -r requirements.txt
fi

if [ -f "main.py" ]; then
  exec python -m uvicorn main:app --host 0.0.0.0 --port "$PORT"
elif [ -f "app/main.py" ]; then
  exec python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
else
  echo "[ERROR] Cannot find main.py or app/main.py in $FASTAPI_DIR"
  ls -la
  exit 1
fi
