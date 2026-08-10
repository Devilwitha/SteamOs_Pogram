#!/usr/bin/env bash
# Installiert den SteamOS<->Pico Monitor als systemd --user Dienst.
# Laeuft dadurch dauerhaft im Hintergrund, auch waehrend Steam im Game Mode ist,
# da Game Mode nur die grafische gamescope-Sitzung ist und den user-Dienst nicht beruehrt.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$USER_SYSTEMD_DIR"
cp "$SCRIPT_DIR/steamos-pico-monitor.service" "$USER_SYSTEMD_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now steamos-pico-monitor.service

echo "Aktiviere Linger, damit der Dienst auch ohne aktive Anmeldesitzung laeuft..."
if ! loginctl enable-linger "$USER" 2>/dev/null; then
    echo "Hinweis: 'loginctl enable-linger' schlug fehl. Bitte ggf. manuell ausfuehren:"
    echo "  sudo loginctl enable-linger $USER"
fi

echo
echo "Fertig. Status pruefen mit:"
echo "  systemctl --user status steamos-pico-monitor.service"
echo "Logs ansehen mit:"
echo "  journalctl --user -u steamos-pico-monitor.service -f"
