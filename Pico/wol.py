"""Sendet ein Wake-on-LAN 'Magic Packet' per UDP-Broadcast, um den PC aus
dem Schlaf-/Ruhezustand zu wecken (siehe ping_server.py: ausgeloest, wenn
ein verknuepfter Tag aufliegt, aber SteamOS laenger nicht antwortet -
typischerweise weil pico_client.py wegen des Schlafmodus nicht laeuft).

Rein Broadcast-basiert: der Pico muss dafuer weder die IP noch den
aktuellen Zustand des PCs kennen, nur dessen MAC-Adresse (siehe
remote_config.py, Feld 'pc_mac'). Setzt auf PC-Seite voraus, dass
Wake-on-LAN im BIOS/UEFI sowie am Netzwerkadapter aktiviert ist (siehe
README.md) - klappt zuverlaessig i. d. R. nur ueber eine kabelgebundene
Netzwerkverbindung, WLAN-Adapter unterstuetzen es meist nicht im
Ruhezustand.
"""
import socket

WOL_PORT = 9


def _mac_bytes(mac):
    """Wandelt eine MAC-Adresse in ueblichem Format ('AA:BB:CC:DD:EE:FF',
    'AA-BB-...' oder ohne Trenner) in 6 rohe Bytes um. Wirft ValueError bei
    ungueltiger Eingabe."""
    cleaned = mac.replace(":", "").replace("-", "").strip()
    if len(cleaned) != 12:
        raise ValueError("MAC-Adresse muss 12 Hex-Zeichen haben")
    return bytes(int(cleaned[i:i + 2], 16) for i in range(0, 12, 2))


def send(mac):
    """Sendet das Magic Packet (6x 0xFF, danach die MAC-Adresse 16x
    wiederholt) per UDP-Broadcast im lokalen Netz. Gibt True bei
    (versuchtem) Versand zurueck, False bei ungueltiger MAC-Adresse oder
    Netzwerkfehler."""
    try:
        payload = b"\xff" * 6 + _mac_bytes(mac) * 16
    except ValueError as e:
        print("WOL: ungueltige MAC-Adresse:", e)
        return False

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # Nicht auf allen MicroPython-Portversionen vorhanden/noetig -
            # ohne diese Option senden manche Firmware-Stacks Broadcasts
            # trotzdem klaglos, deshalb hier bewusst tolerant.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except (AttributeError, OSError):
            pass
        s.sendto(payload, ("255.255.255.255", WOL_PORT))
        s.close()
        return True
    except OSError as e:
        print("WOL: Senden fehlgeschlagen:", e)
        return False
