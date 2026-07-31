#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ENV="$PROJECT_DIR/.venv-build"
ARCHITECTURE="$(uname -m)"
APP_PATH="$PROJECT_DIR/dist/CSV Cleaner.app"
ARCHIVE_PATH="$PROJECT_DIR/dist/CSV-Cleaner-macOS-$ARCHITECTURE.zip"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This script runs only on macOS."
    exit 1
fi

supports_macos_ui() {
    "$1" -c '
import sys
import tkinter

python_ok = sys.version_info >= (3, 11)
tk_version = tuple(
    int(part)
    for part in tkinter.Tcl().eval("info patchlevel").split(".")
)
raise SystemExit(0 if python_ok and tk_version >= (8, 6, 13) else 1)
' >/dev/null 2>&1
}

if [[ -n "${PYTHON_BIN:-}" ]]; then
    PYTHON_CANDIDATES=("$PYTHON_BIN")
else
    PYTHON_CANDIDATES=(
        "python3.14"
        "python3.13"
        "python3.12"
        "/opt/anaconda3/bin/python3.12"
        "python3"
    )
fi

PYTHON_BIN=""
for candidate in "${PYTHON_CANDIDATES[@]}"; do
    if command -v "$candidate" >/dev/null 2>&1; then
        resolved_candidate="$(command -v "$candidate")"
        if supports_macos_ui "$resolved_candidate"; then
            PYTHON_BIN="$resolved_candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    echo "Python 3.11 or newer with Tk 8.6.13 or newer was not found."
    echo "Install a current Python version with Tkinter support and try again."
    exit 1
fi

cd "$PROJECT_DIR"

echo "Selected environment:"
"$PYTHON_BIN" -c '
import platform
import sys
import tkinter

tk_patch = tkinter.Tcl().eval("info patchlevel")
print(f"Python {platform.python_version()}")
print(f"Tk {tk_patch}")
print(f"Architecture {platform.machine()}")
'

echo "Creating the build environment..."
if [[ -d "$BUILD_ENV" ]]; then
    rm -rf "$BUILD_ENV"
fi
"$PYTHON_BIN" -m venv "$BUILD_ENV"

echo "Installing dependencies..."
"$BUILD_ENV/bin/python" -m pip install --upgrade pip
"$BUILD_ENV/bin/python" -m pip install . pyinstaller

echo "Building the application..."
"$BUILD_ENV/bin/pyinstaller" \
    --clean \
    --noconfirm \
    "$PROJECT_DIR/csv_cleaner_macos.spec"

if [[ ! -d "$APP_PATH" ]]; then
    echo "The build did not create the expected application package."
    exit 1
fi

echo "Creating the archive..."
rm -f "$ARCHIVE_PATH"
ditto \
    -c \
    -k \
    --sequesterRsrc \
    --keepParent \
    "$APP_PATH" \
    "$ARCHIVE_PATH"

echo
echo "Done."
echo "Application: $APP_PATH"
echo "Release archive: $ARCHIVE_PATH"
