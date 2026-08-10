"""WLAN-Verbindung und Zugangsdaten-Speicherung fuer den Pico W."""
import network
import ujson as json
import time

CONFIG_FILE = "wifi_config.json"


def load_credentials():
    try:
        with open(CONFIG_FILE) as f:
            data = json.load(f)
            return data.get("ssid"), data.get("password")
    except (OSError, ValueError):
        return None, None


def save_credentials(ssid, password):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"ssid": ssid, "password": password}, f)


def connect(ssid, password, attempts=3, timeout=10):
    """Versucht bis zu `attempts` mal, sich mit dem gespeicherten WLAN zu verbinden.
    Gibt das verbundene WLAN-Objekt zurueck oder None, wenn alle Versuche fehlschlagen."""
    if not ssid:
        return None

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    for attempt in range(1, attempts + 1):
        print("WLAN Verbindungsversuch {}/{} zu '{}'".format(attempt, attempts, ssid))
        wlan.connect(ssid, password)

        start = time.ticks_ms()
        while not wlan.isconnected():
            if time.ticks_diff(time.ticks_ms(), start) > timeout * 1000:
                break
            time.sleep_ms(200)

        if wlan.isconnected():
            print("WLAN verbunden, IP:", wlan.ifconfig()[0])
            return wlan

        wlan.disconnect()

    print("WLAN Verbindung nach {} Versuchen fehlgeschlagen".format(attempts))
    wlan.active(False)
    return None


def start_ap(ssid="Pico-Setup", password="picosetup"):
    """Startet einen Access Point, ueber den das WLAN eingerichtet werden kann."""
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    try:
        ap.config(ssid=ssid, password=password)
    except OSError:
        ap.config(essid=ssid, password=password)
    while not ap.active():
        time.sleep_ms(100)
    print("Access Point aktiv:", ap.ifconfig())
    return ap
