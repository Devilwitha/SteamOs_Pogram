"""
Installiert alle Python-Pakete, die die Skripte in tools/ benoetigen.

Start: python install_requirements.py
"""

import subprocess
import sys
from pathlib import Path

REQUIREMENTS_FILE = Path(__file__).parent / "requirements.txt"


def main():
    if not REQUIREMENTS_FILE.exists():
        print(f"requirements.txt nicht gefunden: {REQUIREMENTS_FILE}")
        sys.exit(1)

    print(f"Installiere Pakete aus {REQUIREMENTS_FILE} ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)]
    )

    if result.returncode != 0:
        print("Installation fehlgeschlagen.")
        sys.exit(result.returncode)

    print("Alle Pakete wurden erfolgreich installiert.")


if __name__ == "__main__":
    main()
