#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/backend/.venv"

if [ ! -d "$VENV" ]; then
  echo "Setting up virtual environment..."
  python3 -m venv "$VENV"
fi

source "$VENV/bin/activate"
pip install -r "$SCRIPT_DIR/backend/requirements.txt" -q

# Load .env if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  # shellcheck disable=SC1090
  source "$SCRIPT_DIR/.env"
  set +a
fi

echo ""
echo "  Talking Head Editor  →  http://localhost:8765"
if [ "${MOCK_TRANSCRIBE}" = "1" ]; then
  echo "  MOCK_TRANSCRIBE=1  (fake transcripts, no ElevenLabs key needed)"
fi
if [ -z "${DASHBOARD_PASSWORD}" ]; then
  echo "  No password set — open access (local dev)"
fi
echo ""

cd "$SCRIPT_DIR/backend"
uvicorn main:app --host 0.0.0.0 --port 8765 --reload
