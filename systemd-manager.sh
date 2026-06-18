#!/bin/bash
# Launcher for systemd-manager
# Automatically uses pkexec for system services if not already root.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$(command -v python3)"

if [ -z "$PYTHON" ]; then
    zenity --error --text="python3 is not installed." 2>/dev/null || \
        echo "Error: python3 is not installed."
    exit 1
fi

exec "$PYTHON" "$SCRIPT_DIR/systemd_manager.py" "$@"
