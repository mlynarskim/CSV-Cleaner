#!/usr/bin/env bash

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_ENV="$PROJECT_DIR/.venv-build"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ARCHITECTURE="$(uname -m)"
APP_PATH="$PROJECT_DIR/dist/CSV Cleaner.app"
ARCHIVE_PATH="$PROJECT_DIR/dist/CSV-Cleaner-macOS-$ARCHITECTURE.zip"

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "Ten skrypt działa wyłącznie na macOS."
    exit 1
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Nie znaleziono Python 3. Zainstaluj Python 3.11 lub nowszy."
    exit 1
fi

cd "$PROJECT_DIR"

echo "Tworzenie środowiska budowania..."
"$PYTHON_BIN" -m venv "$BUILD_ENV"

echo "Instalowanie zależności..."
"$BUILD_ENV/bin/python" -m pip install --upgrade pip
"$BUILD_ENV/bin/python" -m pip install . pyinstaller

echo "Budowanie aplikacji..."
"$BUILD_ENV/bin/pyinstaller" \
    --clean \
    --noconfirm \
    "$PROJECT_DIR/csv_cleaner_macos.spec"

if [[ ! -d "$APP_PATH" ]]; then
    echo "Budowanie nie utworzyło oczekiwanego pakietu aplikacji."
    exit 1
fi

echo "Tworzenie archiwum..."
rm -f "$ARCHIVE_PATH"
ditto \
    -c \
    -k \
    --sequesterRsrc \
    --keepParent \
    "$APP_PATH" \
    "$ARCHIVE_PATH"

echo
echo "Gotowe."
echo "Aplikacja: $APP_PATH"
echo "Archiwum do publikacji: $ARCHIVE_PATH"
