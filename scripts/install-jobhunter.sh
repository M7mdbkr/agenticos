#!/usr/bin/env bash
# One-command setup for Job Hunter on macOS / Linux:  bash scripts/install-jobhunter.sh
set -u
cd "$(dirname "$0")/.."

ask() { read -r -p "$1 [Y/n] " reply; [[ -z "$reply" || "$reply" =~ ^[Yy] ]]; }

python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "❌ Python 3.9+ is required (macOS: brew install python)"; exit 1; }

if ! command -v tesseract >/dev/null && command -v brew >/dev/null; then
  ask "Install tesseract so I can read business-card photos (Arabic + English)?" && brew install tesseract tesseract-lang
fi
if command -v ollama >/dev/null; then
  ask "Download the Ollama vision model for business cards (~8 GB, better than tesseract)?" && ollama pull llama3.2-vision
fi

python3 -m jobhunter setup || exit 1

read -r -p "Path to your CV .docx to use as the master CV (Enter to skip): " cv
if [[ -n "$cv" ]]; then python3 -m jobhunter cv import "${cv/#\~/$HOME}"; fi

echo; echo "Sending you a test email…"; python3 -m jobhunter test-email || echo "⚠️  Test email failed — see the doctor below."
echo; echo "First search (this can take a minute)…"; python3 -m jobhunter once
echo; python3 -m jobhunter install-service
echo; python3 -m jobhunter doctor
echo; echo "Done. Reply to the agent's emails with 'help', or open http://127.0.0.1:8765/#hunter (python3 server.py)."
