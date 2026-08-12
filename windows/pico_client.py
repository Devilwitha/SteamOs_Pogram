#!/usr/bin/env python3
"""Windows-Einstiegspunkt fuer den SteamOS<->Pico Monitor.

Ruft direkt ../steamOs/pico_client.py auf - der Code dort ist bereits
plattformuebergreifend (inkl. Windows-spezifischer steam.exe-Aufloesung
ueber die Registry, da 'steam' unter Windows anders als auf SteamOS meist
nicht im PATH steht). Dieser Wrapper existiert nur als kurzer,
eigenstaendiger Einstiegspunkt zum lokalen Testen auf Windows - siehe
windows/README.md.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steamOs"))

from pico_client import main  # noqa: E402

if __name__ == "__main__":
    main()
