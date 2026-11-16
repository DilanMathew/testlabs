#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "First run: setting up... this takes a minute."
  python3 -m venv .venv || { echo "Python 3 not found. Install Python 3.10+ first."; exit 1; }
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt || { echo "Install failed."; exit 1; }
fi
exec .venv/bin/python run.py "$@"
