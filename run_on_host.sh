#!/usr/bin/env bash
# Fuehrt ein Python-Skript auf dem echten SteamOS-Host aus statt im
# sandboxten VSCode-Terminal (Flatpak) - noetig fuer alles, was tkinter
# (GUI) oder DISPLAY braucht (z. B. tools/cover_maker/cover_maker.py):
# das Python im VSCode-Sandbox (Freedesktop-SDK-Runtime) hat kein
# eingebautes Tcl/Tk und keinen DISPLAY, das Host-Python schon.
#
# Nutzt .venv-host (per --system-site-packages erstellt, siehe Chatverlauf)
# statt .venv, damit sowohl das Host-tkinter als auch normal per pip
# installierte Pakete (z. B. Pillow) verfuegbar sind.
#
# Verwendung: ./run_on_host.sh tools/cover_maker/cover_maker.py [Argumente...]
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

if command -v flatpak-spawn >/dev/null 2>&1; then
    # Im sandboxten VSCode-Terminal: auf den Host wechseln.
    exec flatpak-spawn --host "$(pwd)/.venv-host/bin/python" "$@"
else
    # Schon direkt auf dem Host (z. B. echtes Konsole-Fenster): kein
    # flatpak-spawn noetig/vorhanden, .venv-host direkt verwenden.
    exec "$(pwd)/.venv-host/bin/python" "$@"
fi
