#!/usr/bin/env bash
# Installiert den SteamOS<->Pico Monitor sowie den Spiele-Scanner als
# systemd --user Dienste. Laeuft dadurch dauerhaft im Hintergrund, auch
# waehrend Steam im Game Mode ist, da Game Mode nur die grafische
# gamescope-Sitzung ist und die user-Dienste nicht beruehrt.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$USER_SYSTEMD_DIR"
cp "$SCRIPT_DIR/steamos-pico-monitor.service" "$USER_SYSTEMD_DIR/"
cp "$SCRIPT_DIR/steamos-game-scanner.service" "$USER_SYSTEMD_DIR/"
cp "$SCRIPT_DIR/steamos-game-scanner.timer" "$USER_SYSTEMD_DIR/"
cp "$SCRIPT_DIR/steamos-gui-server.service" "$USER_SYSTEMD_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now steamos-pico-monitor.service
systemctl --user enable --now steamos-game-scanner.timer
systemctl --user enable --now steamos-gui-server.service
# Sofortiger erster Scan, statt auf OnBootSec zu warten:
systemctl --user start steamos-game-scanner.service

echo "Aktiviere Linger, damit die Dienste auch ohne aktive Anmeldesitzung laufen..."
if ! loginctl enable-linger "$USER" 2>/dev/null; then
    echo "Hinweis: 'loginctl enable-linger' schlug fehl. Bitte ggf. manuell ausfuehren:"
    echo "  sudo loginctl enable-linger $USER"
fi

echo
echo "Fertig. Status pruefen mit:"
echo "  systemctl --user status steamos-pico-monitor.service"
echo "  systemctl --user status steamos-game-scanner.timer"
echo "  systemctl --user status steamos-gui-server.service"
echo "Logs ansehen mit:"
echo "  journalctl --user -u steamos-pico-monitor.service -f"
echo "  journalctl --user -u steamos-game-scanner.service -f"
echo "  journalctl --user -u steamos-gui-server.service -f"
