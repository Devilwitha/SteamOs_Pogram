#!/bin/bash
# Einmaliges Diagnose-Skript (kein dauerhafter Teil des Projekts) - schreibt
# in den ersten ~100s nach jedem Start alle paar Sekunden den Zustand von
# steamos-openrgb.service + Umgebung in eine Logdatei, damit sich ein
# fehlgeschlagener Start im Game Mode nachtraeglich nachvollziehen laesst
# (waehrend des Game Mode ist kein Desktop/Terminal erreichbar, um live
# nachzuschauen - siehe Chatverlauf).
LOG=~/openrgb-boot-diagnose.log

{
  echo "===== NEUER LAUF: $(date '+%Y-%m-%d %H:%M:%S') ====="
  echo "uptime: $(uptime -p 2>/dev/null || cat /proc/uptime)"
} >> "$LOG"

for i in $(seq 1 20); do
  {
    echo "--- t=+${i}x5s ($(date '+%H:%M:%S')) ---"
    echo "[status]"
    systemctl --user status steamos-openrgb.service --no-pager 2>&1 | head -8
    echo "[process]"
    ps aux | grep -i openrgb | grep -v grep
    echo "[port 6742]"
    ss -tln 2>/dev/null | grep 6742 || echo "not listening"
    echo "[env DISPLAY/WAYLAND]"
    systemctl --user show-environment 2>&1 | grep -iE "^display=|^wayland_display=|^xdg_session_type=|^xdg_current_desktop="
    echo "[recent journal]"
    journalctl --user -u steamos-openrgb.service -n 5 --no-pager 2>&1
    echo
  } >> "$LOG"
  sleep 5
done

echo "===== ENDE LAUF ($(date '+%H:%M:%S')) =====" >> "$LOG"
