#!/usr/bin/env bash
# Entfernt den SteamOS<->Pico Monitor und den Spiele-Scanner wieder.
set -euo pipefail

systemctl --user disable --now steamos-pico-monitor.service || true
systemctl --user disable --now steamos-gui.service || true
systemctl --user disable --now steamos-lilygo-monitor.service || true
systemctl --user disable --now steamos-game-scanner.timer || true
systemctl --user disable --now steamos-openrgb.service || true
rm -f "$HOME/.config/systemd/user/steamos-pico-monitor.service"
rm -f "$HOME/.config/systemd/user/steamos-gui.service"
rm -f "$HOME/.config/systemd/user/steamos-lilygo-monitor.service"
rm -f "$HOME/.config/systemd/user/steamos-game-scanner.service"
rm -f "$HOME/.config/systemd/user/steamos-game-scanner.timer"
rm -f "$HOME/.config/systemd/user/steamos-openrgb.service"
systemctl --user daemon-reload

# Wake-on-USB-udev-Regel (siehe install.sh) - system-weit, braucht sudo,
# daher separat und mit eigener Fehlerbehandlung statt den Rest des
# Skripts davon abhaengig zu machen.
if [ -f /etc/udev/rules.d/10-wakeup.rules ]; then
    if sudo rm -f /etc/udev/rules.d/10-wakeup.rules && sudo udevadm control --reload; then
        echo "Wake-on-USB-udev-Regel entfernt."
    else
        echo "Hinweis: Wake-on-USB-udev-Regel konnte nicht entfernt werden. Manuell:"
        echo "  sudo rm -f /etc/udev/rules.d/10-wakeup.rules && sudo udevadm control --reload"
    fi
fi

# USB-Automount-udev-Regel (siehe install.sh) - system-weit, braucht sudo,
# daher separat und mit eigener Fehlerbehandlung. Bereits gemountete
# Datentraeger bleiben davon unberuehrt (liegen unter /run, das ohnehin
# beim naechsten Neustart geleert wird).
if [ -f /etc/udev/rules.d/61-usb-automount.rules ]; then
    if sudo rm -f /etc/udev/rules.d/61-usb-automount.rules && sudo udevadm control --reload; then
        echo "USB-Automount-udev-Regel entfernt."
    else
        echo "Hinweis: USB-Automount-udev-Regel konnte nicht entfernt werden. Manuell:"
        echo "  sudo rm -f /etc/udev/rules.d/61-usb-automount.rules && sudo udevadm control --reload"
    fi
fi

echo "Dienste entfernt."
