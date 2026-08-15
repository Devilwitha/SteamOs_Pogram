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

echo "Dienste entfernt."
