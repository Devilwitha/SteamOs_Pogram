"""Startpunkt fuer den Raspberry Pi Pico W.
Wird beim Booten automatisch ausgefuehrt (Dateiname main.py).

Ablauf:
1. Versuche bis zu 3x, dich mit dem gespeicherten WLAN zu verbinden.
2. Bei Erfolg: starte den Ping-/Discovery-Server fuer SteamOS.
3. Bei Misserfolg: starte einen Access Point mit Einrichtungsseite,
   speichere neue Zugangsdaten und starte danach neu.
"""
import machine
import time
import wifi_manager
import ping_server
import captive_portal

WIFI_ATTEMPTS = 3
WIFI_TIMEOUT_SEC = 10


def start_setup_mode():
    print("Starte Einrichtungsmodus (Access Point)")
    wifi_manager.start_ap()

    def on_saved():
        print("Neue Zugangsdaten gespeichert, Neustart in 2 Sekunden...")
        time.sleep(2)
        machine.reset()

    captive_portal.run(on_saved)


def main():
    led = machine.Pin("LED", machine.Pin.OUT)
    ssid, password = wifi_manager.load_credentials()
    wlan = wifi_manager.connect(ssid, password, attempts=WIFI_ATTEMPTS, timeout=WIFI_TIMEOUT_SEC)

    if wlan is None:
        led.off()
        start_setup_mode()
        return

    led.on()
    my_ip = wlan.ifconfig()[0]
    print("Pico bereit unter", my_ip)
    ping_server.start(my_ip)


main()
