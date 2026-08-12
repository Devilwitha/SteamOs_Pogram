"""Diagnose-Skript: zeigt alle Daten einer aufgelegten MIFARE-Classic-Karte
an (physische UID + Inhalt aller lesbaren Sektoren/Bloecke). Direkt in
Thonny ausfuehren ("Run current script" bzw. F5) - die Ausgabe erscheint
im Shell-Fenster. Funktioniert unabhaengig vom restlichen Programm
(main.py muss dafuer nicht laufen).

Jeder MIFARE-Classic-1K-Tag hat 16 Sektoren zu je 4 Bloecken (0-63); der
jeweils letzte Block eines Sektors ist der "Trailer" (Schluessel/Rechte).
Bei unbeschriebenen/Werks-Tags funktioniert die Authentifizierung mit dem
Standardschluessel FF FF FF FF FF FF (DEFAULT_KEY) fuer alle Sektoren.
"""
import time

from mfrc522 import MFRC522, OK, AUTHENT1A, DEFAULT_KEY

reader = MFRC522()


def _hex(data):
    return " ".join("{:02X}".format(b) for b in data)


def _text(data):
    return "".join(chr(b) if 32 <= b < 127 else "." for b in data)


def dump_card(uid):
    print("Karten-UID:", _hex(uid), "({} Byte)".format(len(uid)))
    for sector in range(16):
        first_block = sector * 4
        trailer_block = first_block + 3

        if reader.select_tag(uid) != OK:
            print("  Sektor {:2d}: Karte nicht (mehr) auswaehlbar, breche ab".format(sector))
            return

        if reader.auth(AUTHENT1A, trailer_block, DEFAULT_KEY, uid) != OK:
            print("  Sektor {:2d}: Authentifizierung fehlgeschlagen (anderer Schluessel?)".format(sector))
            reader.stop_crypto1()
            continue

        for block in range(first_block, trailer_block + 1):
            data = reader.read(block)
            if data is None:
                print("    Block {:2d}: Lesefehler".format(block))
                continue
            rolle = " <- Trailer (Schluessel/Rechte)" if block == trailer_block else ""
            print("    Block {:2d}: {}  '{}'{}".format(block, _hex(data), _text(data), rolle))

        reader.stop_crypto1()


def main():
    print("RFID-Diagnose gestartet. Karte auf den RC522 legen...")
    last_uid = None
    while True:
        if reader.request() == OK:
            status, uid = reader.anticoll()
            if status == OK and uid != last_uid:
                last_uid = uid
                print("\n--- Neue Karte erkannt ---")
                dump_card(uid)
                print("--- Ende ---\n")
        else:
            if last_uid is not None:
                print("Karte entfernt.\n")
            last_uid = None
        time.sleep_ms(300)


if __name__ == "__main__":
    main()
