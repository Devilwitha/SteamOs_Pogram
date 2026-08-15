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
cp "$SCRIPT_DIR/steamos-openrgb.service" "$USER_SYSTEMD_DIR/"

systemctl --user daemon-reload
systemctl --user enable --now steamos-pico-monitor.service
systemctl --user enable --now steamos-gui.service
systemctl --user enable --now steamos-lilygo-monitor.service
systemctl --user enable --now steamos-game-scanner.timer
# Sofortiger erster Scan, statt auf OnBootSec zu warten:
systemctl --user start steamos-game-scanner.service

# steamos-openrgb.service nur aktivieren, wenn OpenRGB tatsaechlich als
# Flatpak installiert ist (siehe openrgb_link.py/README) - anders als die
# Python-basierten optionalen Geraete (LilyGo, Led_Pico) wuerde der Dienst
# sonst dauerhaft mit Restart=always fehlschlagen (Flatpak-App nicht
# gefunden) und nur unnoetig das Journal fuellen, statt einfach untaetig
# zu bleiben.
if flatpak info org.openrgb.OpenRGB >/dev/null 2>&1; then
    systemctl --user enable --now steamos-openrgb.service
else
    echo "Hinweis: OpenRGB (org.openrgb.OpenRGB) nicht als Flatpak gefunden - "
    echo "  steamos-openrgb.service wird nicht aktiviert. Fuer lokale USB-RGB-LEDs"
    echo "  (siehe openrgb_link.py): 'flatpak install flathub org.openrgb.OpenRGB'"
    echo "  und install.sh erneut ausfuehren."
fi

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
echo "  systemctl --user status steamos-openrgb.service  # falls OpenRGB installiert ist"
echo "Logs ansehen mit:"
echo "  journalctl --user -u steamos-pico-monitor.service -f"
echo "  journalctl --user -u steamos-gui.service -f"
echo "  journalctl --user -u steamos-lilygo-monitor.service -f"
echo "  journalctl --user -u steamos-game-scanner.service -f"
echo "  journalctl --user -u steamos-openrgb.service -f"
echo
echo "GUI erreichbar unter http://127.0.0.1:8090/ (bzw. im LAN, falls gui_bind in config.json gesetzt ist)."
echo "LilyGo-Statusdisplay und lokale USB-RGB-LEDs (OpenRGB) sind optional - laufen ohne, ohne Fehler zu werfen."
