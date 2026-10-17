#!/usr/bin/env bash
# One sync without the window — Linux counterpart of "Sync quotidienne.bat".
# Meant for a systemd user timer or cron.
cd "$(dirname "$(readlink -f "$0")")"

if [ ! -x ".venv-linux/bin/python" ]; then
    echo "[ERREUR] Environnement Python absent. Lancez d'abord ./launch-naosnatcher.sh" >&2
    exit 1
fi

exec .venv-linux/bin/python -m naosnatcher.run "$@"
