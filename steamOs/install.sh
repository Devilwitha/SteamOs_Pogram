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

# Wake-on-USB-Controller (optional, hier fuer den 8BitDo Ultimate 2) - siehe
# Chatverlauf: eine udev-Regel setzt "power/wakeup" fuer den USB-Bus, an dem
# der Controller haengt, dauerhaft auf "enabled" (ueberlebt Neustarts/
# erneutes Einstecken). Die Bus-Nummer wird bewusst dynamisch ueber die
# USB-ID ermittelt statt fest einkompiliert, da sie sich mit dem
# physischen Port aendern kann. Zusaetzlich wird der aktuelle Zustand
# sofort direkt gesetzt - 'udevadm trigger' allein hat sich bei einem
# bereits verbundenen Geraet als nicht zuverlaessig genug erwiesen. Setzt
# passwortlosen oder interaktiven sudo-Zugriff voraus (einzige Stelle in
# diesem Skript, die root braucht) - schlaegt der sudo-Aufruf fehl (z. B.
# falscher Passwort-Timeout), wird das mit einer Fehlermeldung uebersprungen,
# ohne den Rest des Skripts abzubrechen.
CONTROLLER_VENDOR_ID="2dc8"
CONTROLLER_PRODUCT_ID="6013"  # 8BitDo Ultimate 2 - fuer einen anderen Controller anpassen (siehe lsusb)

CONTROLLER_BUS=""
for dev in /sys/bus/usb/devices/*/; do
    if [ -f "${dev}idVendor" ] && [ -f "${dev}idProduct" ] && [ -f "${dev}busnum" ]; then
        if [ "$(cat "${dev}idVendor")" = "$CONTROLLER_VENDOR_ID" ] && \
           [ "$(cat "${dev}idProduct")" = "$CONTROLLER_PRODUCT_ID" ]; then
            CONTROLLER_BUS="usb$(cat "${dev}busnum")"
            break
        fi
    fi
done

if [ -n "$CONTROLLER_BUS" ]; then
    echo
    echo "Richte Wake-on-USB fuer den Controller ein (${CONTROLLER_BUS}, benoetigt sudo)..."
    if echo "SUBSYSTEM==\"usb\", KERNEL==\"${CONTROLLER_BUS}\", ATTR{power/wakeup}=\"enabled\"" \
            | sudo tee /etc/udev/rules.d/10-wakeup.rules > /dev/null \
        && sudo udevadm control --reload \
        && sudo udevadm trigger \
        && sudo sh -c "echo enabled > /sys/bus/usb/devices/${CONTROLLER_BUS}/power/wakeup"; then
        echo "  aktueller Zustand: $(cat "/sys/bus/usb/devices/${CONTROLLER_BUS}/power/wakeup")"
    else
        echo "  Fehler bei der Einrichtung - bitte die obigen Schritte manuell pruefen."
    fi
else
    echo
    echo "Hinweis: Controller (USB-ID ${CONTROLLER_VENDOR_ID}:${CONTROLLER_PRODUCT_ID}) aktuell nicht"
    echo "  gefunden - Wake-on-USB-Einrichtung uebersprungen. Controller anschliessen und"
    echo "  install.sh erneut ausfuehren, um es einzurichten."
fi

echo
echo "Richte USB-Automount fuer Datentraeger ein (benoetigt sudo)..."
chmod +x "$SCRIPT_DIR/usb-automount.sh"
if sed "s#@STEAMOS_DIR@#$SCRIPT_DIR#g; s#@STEAMOS_USER@#$USER#g; s#@STEAMOS_UID@#$(id -u)#g; s#@STEAMOS_GID@#$(id -g)#g" \
        "$SCRIPT_DIR/61-usb-automount.rules" | sudo tee /etc/udev/rules.d/61-usb-automount.rules > /dev/null \
    && sudo udevadm control --reload; then
    echo "  eingerichtet - Sticks/externe Festplatten erscheinen kuenftig automatisch"
    echo "  unter /run/media/$USER/<Geraetename>, auch im Game Mode."
    # Bereits eingesteckte Datentraeger sofort erfassen, statt auf das
    # naechste Ein-/Ausstecken warten zu muessen:
    sudo udevadm trigger --action=add --subsystem-match=block || true
else
    echo "  Fehler bei der Einrichtung - bitte die obigen Schritte manuell pruefen."
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
if [ -n "$CONTROLLER_BUS" ]; then
    echo "Wake-on-USB-Status pruefen mit: cat /sys/bus/usb/devices/${CONTROLLER_BUS}/power/wakeup"
fi
echo "USB-Automount-Logs ansehen mit: journalctl -t usb-automount -f"
