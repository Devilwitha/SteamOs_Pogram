#!/usr/bin/env python3
"""Windows-Einstiegspunkt fuer die Spielauswahl-/Tag-Verwaltungs-GUI.

Ruft direkt ../steamOs/gui/gui_server.py auf - der Code dort ist bereits
rein plattformunabhaengig (Python-Standardbibliothek, keine OS-Annahmen).
Dieser Wrapper existiert nur als kurzer, eigenstaendiger Einstiegspunkt
zum lokalen Testen auf Windows - siehe windows/README.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steamOs" / "gui"))

from gui_server import main  # noqa: E402

if __name__ == "__main__":
    main()
