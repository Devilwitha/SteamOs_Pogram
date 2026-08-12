"""Startpunkt fuer den Raspberry Pi Pico W.
Wird beim Booten automatisch ausgefuehrt (Dateiname main.py).

Ablauf:
1. Versuche bis zu 3x, dich mit dem gespeicherten WLAN zu verbinden
   (siehe wlan.py - Hotspot-Fallback-Logik analog zu
   github.com/Devilwitha/Pico/tree/main/Picodesk). Ist ein LCD
   angeschlossen, zeigt es den Verbindungsstatus an (siehe _init_lcd/
   _lcd_show unten) - ohne LCD wird dieser Teil automatisch uebersprungen.
2. Bei Erfolg: starte den RFID-Tag-Manager sowie den Ping-/Steuer-/
   Discovery-Server fuer SteamOS.
3. Bei Misserfolg: wlan.py oeffnet automatisch einen Access Point;
   speichere neue Zugangsdaten ueber die Einrichtungsseite und starte
   danach neu. Wird laenger als HOTSPOT_TIMEOUT_SEK niemand aktiv, startet
   sich der Pico von selbst neu und versucht es erneut.
"""
import machine
import time
import _thread
import wlan
import ping_server
import tag_manager
import captive_portal

WIFI_ATTEMPTS = 3
WIFI_TIMEOUT_SEC = 10
HOSTNAME = "pico-steamos"

LCD_I2C_ID = 0
LCD_SDA_PIN = 0
LCD_SCL_PIN = 1
LCD_ADDR = 0x27
IP_ANZEIGE_SEK = 5


def _init_lcd():
    """Initialisiert das optionale 16x2-I2C-LCD. Ist keines angeschlossen
    oder schlaegt die Initialisierung fehl, wird None zurueckgegeben und
    der Rest des Programms laeuft unveraendert (nur ohne Anzeige) weiter."""
    try:
        from machine import I2C, Pin
        from i2c_lcd import LcdI2c

        i2c = I2C(LCD_I2C_ID, sda=Pin(LCD_SDA_PIN), scl=Pin(LCD_SCL_PIN), freq=400000)
        addrs = i2c.scan()
        addr = LCD_ADDR if LCD_ADDR in addrs else (addrs[0] if addrs else None)
        if addr is None:
            return None
        return LcdI2c(i2c, addr=addr)
    except Exception as e:
        print("LCD nicht verfuegbar:", e)
        return None


def _lcd_show(lcd, zeile1, zeile2=""):
    if lcd is None:
        return
    try:
        lcd.clear()
        lcd.putstr(zeile1[:16])
        if zeile2:
            lcd.move_to(0, 1)
            lcd.putstr(zeile2[:16])
    except Exception as e:
        print("LCD-Fehler:", e)


def start_setup_mode(lcd):
    print("Kein WLAN verbunden - Einrichtungsmodus (Access Point) aktiv")
    _lcd_show(lcd, "WLAN Fehler", "AP: " + wlan.AP_SSID)

    def on_saved():
        print("Neue Zugangsdaten gespeichert, Neustart in 2 Sekunden...")
        time.sleep(2)
        machine.reset()

    _thread.start_new_thread(wlan.hotspot_timeout_thread, ())
    captive_portal.run(on_saved)


def main():
    led = machine.Pin("LED", machine.Pin.OUT)
    wlan.LED = led

    lcd = _init_lcd()
    _lcd_show(lcd, "WLAN verbinden", "...")

    try:
        _netz, modus = wlan.verbinden(
            hostname=HOSTNAME,
            standard_ssid="",
            standard_passwort="",
            versuche=WIFI_ATTEMPTS,
            timeout=WIFI_TIMEOUT_SEC,
        )
    except Exception as e:
        # Ein unerwarteter Fehler beim Verbindungsversuch darf nicht dazu
        # fuehren, dass der Access-Point-Fallback ausbleibt.
        print("Unerwarteter Fehler beim WLAN-Verbindungsaufbau:", e)
        modus = "hotspot"
        wlan.hotspot_starten()

    if modus == "hotspot":
        led.off()
        start_setup_mode(lcd)
        return

    led.on()
    my_ip = wlan.ip
    print("Pico bereit unter", my_ip)

    _lcd_show(lcd, "WLAN OK", my_ip)
    time.sleep(IP_ANZEIGE_SEK)
    _lcd_show(lcd, "Pico bereit", my_ip)

    try:
        tag_manager.init()
    except Exception as e:
        print("RFID-Leser (RC522) konnte nicht initialisiert werden:", e)

    # Ab hier uebernimmt ping_server._background_loop die LCD-Anzeige und
    # zeigt laufend den aktuell aufliegenden Tag (verknuepftes Spiel bzw.
    # "Unbekannter Tag") oder bei leerem Leser wieder diesen
    # Bereitschafts-Bildschirm an.
    ping_server.start(my_ip, HOSTNAME, lcd)


main()
