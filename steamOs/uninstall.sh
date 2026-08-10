#!/usr/bin/env bash
# Entfernt den SteamOS<->Pico Monitor Dienst wieder.
set -euo pipefail

systemctl --user disable --now steamos-pico-monitor.service || true
rm -f "$HOME/.config/systemd/user/steamos-pico-monitor.service"
systemctl --user daemon-reload

echo "Dienst entfernt."
