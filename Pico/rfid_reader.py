"""Erkennung der physischen UID eines aufgelegten RFID-Tags ueber den
RC522-Leser. Die Verknuepfung mit einer Spiel-UID erfolgt nicht durch
Beschreiben des Tags, sondern ueber eine lokale Zuordnungstabelle (siehe
tag_store.py) - dadurch funktioniert das auch mit Tags, die sich nicht
beschreiben lassen. Fuer einen vollstaendigen Speicher-Dump einer Karte
(Diagnose) siehe rfid_test.py, das direkt auf mfrc522.py aufsetzt."""
from mfrc522 import MFRC522, OK


def uid_to_hex(uid_bytes):
    return "".join("{:02x}".format(b) for b in uid_bytes)


class RfidStation:
    def __init__(self, **spi_kwargs):
        self._reader = MFRC522(**spi_kwargs)

    def poll(self):
        """Erkennt eine aufliegende Karte. Gibt deren physische UID
        (bytes) zurueck, oder None, wenn keine Karte da ist."""
        if self._reader.request() != OK:
            return None
        status, uid = self._reader.anticoll()
        if status != OK:
            return None
        return uid
