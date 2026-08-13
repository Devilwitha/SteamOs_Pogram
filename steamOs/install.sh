#!/usr/bin/env bash
# Installiert den SteamOS<->Pico Monitor sowie den Spiele-Scanner als
# systemd --user Dienste. Laeuft dadurch dauerhaft im Hintergrund, auch
# waehrend Steam im Game Mode ist, da Game Mode nur die grafische
# gamescope-Sitzung ist und die user-Dienste nicht beruehrt.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
USER_SYSTEMD_DIR="$HOME/.config/systemd/user"

mkdir -p "$USER_SYSTEMD_DIR"
# @STEAMOS_DIR@ statt fest einkompiliertem %h/steamOs, da dieses Repo nicht
# zwingend direkt unter $HOME liegt (siehe Chatverlauf: hier z. B. unter
# $HOME/Documents/Github/SteamOs_Pogram/steamOs) - beim Kopieren durch den
# tatsaechlichen Skriptpfad ersetzen.
sed "s#@STEAMOS_DIR@#$SCRIPT_DIR#g" "$SCRIPT_DIR/steamos-pico-monitor.service" > "$USER_SYSTEMD_DIR/steamos-pico-monitor.service"
sed "s#@STEAMOS_DIR@#$SCRIPT_DIR#g" "$SCRIPT_DIR/steamos-game-scanner.service" > "$USER_SYSTEMD_DIR/steamos-game-scanner.service"
sed "s#@STEAMOS_DIR@#$SCRIPT_DIR#g" "$SCRIPT_DIR/steamos-gui.service" > "$USER_SYSTEMD_DIR/steamos-gui.service"
sed "s#@STEAMOS_DIR@#$SCRIPT_DIR#g" "$SCRIPT_DIR/steamos-lilygo-monitor.service" > "$USER_SYSTEMD_DIR/steamos-lilygo-monitor.service"
cp "$SCRIPT_DIR/steamos-game-scanner.timer" "$USER_SYSTEMD_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now steamos-pico-monitor.service
systemctl --user enable --now steamos-gui.service
systemctl --user enable --now steamos-lilygo-monitor.service
systemctl --user enable --now steamos-game-scanner.timer
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
echo "  systemctl --user status steamos-gui.service"
echo "  systemctl --user status steamos-lilygo-monitor.service"
echo "  systemctl --user status steamos-game-scanner.timer"
echo "Logs ansehen mit:"
echo "  journalctl --user -u steamos-pico-monitor.service -f"
echo "  journalctl --user -u steamos-gui.service -f"
echo "  journalctl --user -u steamos-lilygo-monitor.service -f"
echo "  journalctl --user -u steamos-game-scanner.service -f"
echo
echo "GUI erreichbar unter http://127.0.0.1:8080/ (bzw. im LAN, falls gui_bind in config.json gesetzt ist)."
echo "LilyGo-Statusdisplay (falls vorhanden/konfiguriert) ist optional - laeuft ohne, ohne Fehler zu werfen."
