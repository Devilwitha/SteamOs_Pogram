"""Kleiner geteilter Laufzeit-Zustand zwischen ping_server.py (schreibt) und
status_server.py (liest), um einen zirkulaeren Import zu vermeiden
(ping_server importiert bereits status_server fuer die Statusseite).

Haelt ausschliesslich die zuletzt gesehene IP der SteamOS-Seite im RAM -
nicht persistiert, nach einem Neustart wieder leer. Sie wird passiv aus den
sowieso alle paar Sekunden eintreffenden PING-Verbindungen von
steamOs/pico_client.py abgeleitet (siehe ping_server._handle_tcp_client) und
dient status_server.py nur als bequemer Vorschlag fuer das Verbindungs-
Einstellungsformular der Steuer-Seite (siehe control.html) - die tatsaechlich
verwendete PC-Adresse liegt (falls vom Nutzer gespeichert) in
remote_config.py."""

_last_pc_ip = None


def note_pc_ip(ip):
    global _last_pc_ip
    _last_pc_ip = ip


def get_last_pc_ip():
    return _last_pc_ip
