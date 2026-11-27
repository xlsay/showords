#!/usr/bin/env bash
set -e

ROLE="${1:-}"
if [[ "$ROLE" != "server" && "$ROLE" != "client" ]]; then
    echo "Usage: ./scripts/start.sh server|client"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${REPO_ROOT}/codes/${ROLE}"

if [ ! -x "${APP_DIR}/.venv/bin/python" ]; then
    echo "Error: ${ROLE} environment not found. Run ./scripts/install.sh ${ROLE} first."
    exit 1
fi

if [[ "$ROLE" == "server" ]]; then
    echo "==> Starting MeetingAssist server..."
    cd "$APP_DIR"
    exec .venv/bin/python main.py
fi

# The desktop app starts and supervises the local capture bridge itself.
echo "==> Starting MeetingAssist client..."
cd "${APP_DIR}/frontend"
exec npm run dev
