"""Startpunkt fuer den Led_Pico (Raspberry Pi Pico W / Pico 2 W).
Wird beim Booten automatisch ausgefuehrt (Dateiname main.py).

Eigenstaendiges zweites Geraet neben dem RFID-Pico (siehe ../Pico) -
steuert einen WS2812/NeoPixel-LED-Streifen in der Farbe des aktuell
erkannten Spiels bzw. Tags an. Beide Picos laufen unabhaengig
voneinander im selben WLAN; SteamOS (steamOs/pico_client.py,
steamOs/led_link.py) verbindet die beiden.

Ablauf:
1. Versuche bis zu 3x, dich mit dem gespeicherten WLAN zu verbinden
   (siehe wlan.py - identische Hotspot-Fallback-Logik wie beim RFID-Pico,
   nur mit eigener Access-Point-SSID, damit beide Geraete beim
   Ersteinrichten unterscheidbar sind).
2. Bei Erfolg: starte den TCP-Steuer-/UDP-Discovery-Server (led_server.py),
   der den LED-Streifen (led_strip.py) auf per COLOR:<hex> gesendete
   Farben setzt.
3. Bei Misserfolg: wlan.py oeffnet automatisch einen Access Point;
   speichere neue Zugangsdaten ueber die Einrichtungsseite und starte
   danach neu.
"""
import machine
import time
import _thread
import wlan
import captive_portal
import led_server
import led_strip

WIFI_ATTEMPTS = 3
WIFI_TIMEOUT_SEC = 10
HOSTNAME = "led-pico"

# Datenpin des LED-Streifens sowie Anzahl der LEDs - siehe README
# (Hardware/Verkabelung) fuer Verkabelung und Stromversorgung.
LED_PIN = 15
LED_COUNT = 30
LED_BRIGHTNESS = 0.5

wlan.AP_SSID = "LedPico-Setup"
wlan.AP_PASSWORT = "picosetup123"


def start_setup_mode():
    print("Kein WLAN verbunden - Einrichtungsmodus (Access Point) aktiv")

    def on_saved():
        print("Neue Zugangsdaten gespeichert, Neustart in 2 Sekunden...")
        time.sleep(2)
        machine.reset()

    _thread.start_new_thread(wlan.hotspot_timeout_thread, ())
    captive_portal.run(on_saved)


def main():
    led = machine.Pin("LED", machine.Pin.OUT)
    wlan.LED = led

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
        start_setup_mode()
        return

    led.on()
    my_ip = wlan.ip
    print("Led_Pico bereit unter", my_ip)

    strip = led_strip.LedStrip(LED_PIN, LED_COUNT, brightness=LED_BRIGHTNESS)
    strip.off()

    led_server.start(my_ip, strip)


main()
