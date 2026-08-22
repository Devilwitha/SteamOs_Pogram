"""Decky-Loader-Plugin-Backend fuer die SteamOS-Konsole.

Macht keine eigene Logik - reiner HTTP-Proxy zum bereits laufenden
gui_server.py (steamos-gui.service, Standardport 8090, siehe
steamOs/gui/gui_server.py::API_ROUTES). Das Frontend (src/index.tsx)
spricht ueber diese zwei Methoden (api_get/api_post) exakt dieselbe
JSON-API wie dashboard.html und native_console.py - kein Server-seitiger
Code muss dafuer angefasst werden.

Der Proxy laeuft im Python-Backend (statt direktem fetch() aus dem
CEF-Frontend), weil das der von Decky Loader dokumentierte, zuverlaessige
Weg ist, mit einem lokalen Dienst zu sprechen (kein CORS/CSP-Risiko im
Steam-Client-UI-Kontext).
"""
import json
import urllib.error
import urllib.request

import decky_plugin

GUI_PORT = 8090
BASE_URL = f"http://127.0.0.1:{GUI_PORT}"
TIMEOUT_SECONDS = 8


class Plugin:
    async def _main(self):
        decky_plugin.logger.info(
            "SteamOS-Konsole-Plugin gestartet, Backend unter %s", BASE_URL
        )

    async def _unload(self):
        pass

    async def api_get(self, path: str):
        return self._request("GET", path, None)

    async def api_post(self, path: str, body: dict):
        return self._request("POST", path, body)

    def _request(self, method: str, path: str, body):
        url = BASE_URL + path
        data = None
        headers = {}
        if method == "POST":
            data = json.dumps(body if body is not None else {}).encode("utf-8")
            headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            decky_plugin.logger.error(
                "gui_server.py nicht erreichbar (%s %s): %s", method, path, e
            )
            return {"ok": False, "error": str(e)}
