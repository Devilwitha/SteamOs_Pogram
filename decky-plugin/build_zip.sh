#!/usr/bin/env bash
# Baut das Decky-Plugin (falls noetig) und packt es zu einer installierbaren
# ZIP-Datei (release/<Name>-<Version>.zip). Layout innerhalb der ZIP folgt
# der Struktur, die Decky Loader beim manuellen Installieren erwartet -
# ein einzelner Ordner (Plugin-Name) mit plugin.json/main.py/dist/ darin,
# also identisch zu dem, was danach unter ~/homebrew/plugins/<Name>/ liegt.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PLUGIN_NAME="$(python3 -c "import json; print(json.load(open('plugin.json'))['name'])" | tr ' ' '-')"
VERSION="$(python3 -c "import json; print(json.load(open('package.json'))['version'])")"

if [ ! -f dist/index.js ]; then
  echo "dist/index.js fehlt - baue Frontend zuerst..."
  if ! command -v pnpm >/dev/null 2>&1; then
    echo "Fehler: pnpm ist nicht installiert. Siehe README.md ('Voraussetzungen zum Bauen')." >&2
    exit 1
  fi
  if [ ! -d node_modules ]; then
    pnpm install
  fi
  pnpm run build
fi

RELEASE_DIR="$SCRIPT_DIR/release"
STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT

PLUGIN_DIR="$STAGE_DIR/$PLUGIN_NAME"
mkdir -p "$PLUGIN_DIR"
# package.json muss mit ins installierte Verzeichnis - Decky Loader
# (backend/decky_loader/plugin/plugin.py) liest daraus "type": "module" und
# waehlt nur dann den modernen ESMODULE_V1-Ladepfad (dynamisches import());
# fehlt package.json oder das Feld, faellt es auf den alten
# LEGACY_EVAL_IIFE-Pfad zurueck, der unser ESM-gebautes dist/index.js per
# eval() ausfuehrt und an dessen "export"-Anweisung mit SyntaxError scheitert.
cp plugin.json package.json main.py "$PLUGIN_DIR/"
cp -r dist "$PLUGIN_DIR/dist"
[ -f README.md ] && cp README.md "$PLUGIN_DIR/"
[ -f LICENSE ] && cp LICENSE "$PLUGIN_DIR/"

mkdir -p "$RELEASE_DIR"
ZIP_PATH="$RELEASE_DIR/${PLUGIN_NAME}-${VERSION}.zip"
rm -f "$ZIP_PATH"
(cd "$STAGE_DIR" && zip -r -q "$ZIP_PATH" "$PLUGIN_NAME")

echo "Fertig: $ZIP_PATH"
echo "Installation: im Decky-Loader-Menu -> Einstellungen -> 'Aus ZIP installieren' auswaehlen,"
echo "oder manuell nach ~/homebrew/plugins/${PLUGIN_NAME}/ entpacken."
