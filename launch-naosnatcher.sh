#!/usr/bin/env bash
# Linux counterpart of "Launch Naosnatcher.bat".
# The Windows .venv lives in the same folder, so Linux gets its own .venv-linux.
set -e
cd "$(dirname "$(readlink -f "$0")")"

if [ ! -x ".venv-linux/bin/python" ]; then
    echo "Premiere installation : creation de l'environnement Python..."
    python3 -m venv .venv-linux
    .venv-linux/bin/python -m pip install --upgrade pip --quiet
    .venv-linux/bin/python -m pip install -r requirements.txt
fi

exec .venv-linux/bin/python -m naosnatcher "$@"
