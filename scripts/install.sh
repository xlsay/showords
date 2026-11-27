#!/usr/bin/env bash
set -e

ROLE="${1:-}"
if [[ "$ROLE" != "server" && "$ROLE" != "client" ]]; then
    echo "Usage: ./scripts/install.sh server|client"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${REPO_ROOT}/codes/${ROLE}"

echo "==> Installing MeetingAssist ${ROLE}..."

# Find Python 3.12+
PYTHON_CMD=""
for candidate in python3 python3.12; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; assert sys.version_info >= (3, 12)' 2>/dev/null; then
        PYTHON_CMD="$candidate"
        break
    fi
done
if [[ -z "$PYTHON_CMD" ]]; then
    echo "Error: Python 3.12+ is required but not found."
    exit 1
fi
echo "Using Python interpreter: $PYTHON_CMD"

if [[ "$ROLE" == "client" ]] && ! command -v npm >/dev/null 2>&1; then
    echo "Error: npm not found. Please install Node.js 20+ and try again."
    exit 1
fi

# Python environment
cd "$APP_DIR"
if [ ! -d ".venv" ]; then
    "$PYTHON_CMD" -m venv .venv
fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

if [[ "$ROLE" == "client" ]]; then
    cd "${APP_DIR}/frontend"
    npm install
    # npm 11 withholds Electron's download script.
    if [ ! -f node_modules/electron/path.txt ]; then
        echo "==> Fetching the Electron binary..."
        node node_modules/electron/install.js
    fi
fi

echo ""
echo "Installation complete. Start with:"
echo "  ./scripts/start.sh ${ROLE}"
