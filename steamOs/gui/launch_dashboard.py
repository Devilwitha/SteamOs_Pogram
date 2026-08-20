#!/usr/bin/env python3
"""Einstiegspunkt fuer Steam: startet das native Controller-Einstellungsmenue
(siehe native_console.py) - gedacht als Ziel fuer einen Nicht-Steam-Spiel-
Eintrag in Steam, damit das Menue in Big Picture genau wie ein Spiel aus der
Bibliothek waehlbar/startbar ist (siehe
steamOs/README.md#als-nicht-steam-spiel-in-big-picture-hinzufuegen).

Frueher wurde hier ein Browser im Kiosk-Modus gestartet (siehe Git-
Historie/dashboard.html) - Chromes Gamepad-Web-API liefert unter Wayland
(SteamOS/Bazzite) aber keine zuverlaessigen Controller-Events, sobald die
Seite von Steam aus gestartet wird (weder mit noch ohne Steam Input, sowohl
Eintrags- als auch globale Controller-Einstellungen probiert). Das native
Programm liest den Controller stattdessen direkt ueber SDL2 und ist davon
unabhaengig - siehe native_console.py-Docstring.

native_console.main() blockiert bis das Fenster geschlossen wird (Steam
haelt diesen Prozess fuer die Laufzeit "das Spiel") - gui_server.py selbst
muss nicht separat gestartet werden, laeuft bereits dauerhaft als
steamos-gui.service (siehe install.sh); native_console.main() wartet
selbst kurz darauf, falls der Dienst gerade erst hochfaehrt.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import native_console  # noqa: E402

if __name__ == "__main__":
    native_console.main()
