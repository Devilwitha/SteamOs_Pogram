"""
wlan.py - WLAN-Verbindung mit Hotspot-Fallback.

Struktur und Namensgebung bewusst identisch zu pico_tools/wlan.py aus
github.com/Devilwitha/Pico/tree/main/Picodesk (eigenes Referenzprojekt):
Zugangsdaten aus einer JSON-Datei laden, mehrfach verbinden versuchen,
bei Misserfolg einen Setup-Access-Point oeffnen und nach einer Wartezeit
im Hotspot automatisch neu starten, um es erneut zu versuchen.

Zwei bewusste, kommentierte Abweichungen gegenueber dem Referenzprojekt
(auf dieser Hardware im Livetest noetig, siehe Pico/README.md):
1) hotspot_starten() wartet mit Timeout auf ap.active() statt endlos -
   nach einem gescheiterten WLAN-Versuch kam der Access Point sonst
   manchmal nicht hoch und das Board haengte sich komplett auf.
2) Bei jedem Fehlschlag wird der Verbindungsstatus (wlan.status()) mit
   geloggt, um die Ursache (falsches Passwort, WLAN nicht gefunden,
   dauerhaftes CONNECTING durch WPA3/PMF bei manchen WLAN6-Routern...)
   direkt am Log erkennen zu koennen.

Verwendung in main.py:

    import wlan

    wlan.AP_SSID = "Pico-Setup"
    wlan.AP_PASSWORT = "picosetup"
    wlan.LED = machine.Pin("LED", machine.Pin.OUT)   # optional

    _netz, modus = wlan.verbinden(
        hostname="pico-steamos",
        standard_ssid="",
        standard_passwort="",
    )
    if modus == "hotspot":
        _thread.start_new_thread(wlan.hotspot_timeout_thread, ())

Ueber wlan.modus ("normal"/"hotspot") und wlan.ip laesst sich der aktuelle
Zustand jederzeit abfragen.
"""
import network
import time
import ujson as json
import machine

KONFIG_DATEI = "wlan.conf"
_ALTE_KONFIG_DATEI = "wifi_config.json"  # fruehere Version dieses Projekts

AP_SSID = "Pico-Setup"
AP_PASSWORT = "picosetup123"  # mind. 8 Zeichen (WPA2-Vorgabe)
HOTSPOT_TIMEOUT_SEK = 10 * 60

MAX_VERSUCHE = 3
VERSUCH_TIMEOUT = 15
AP_START_TIMEOUT_SEK = 15  # eigene Ergaenzung, siehe Modul-Docstring oben

# Optional: machine.Pin, blinkt waehrend des Verbindungsaufbaus und leuchtet
# dauerhaft, sobald die Verbindung steht
LED = None

# Status - von aussen lesbar, wird von verbinden()/hotspot_starten() gepflegt
modus = "normal"  # "normal" (im konfigurierten WLAN) oder "hotspot"
ip = ""

_hostname = ""
_hotspot_start_zeit = 0
_standard_ssid = ""
_standard_passwort = ""

# network.WLAN.status() Rueckgabewerte (rp2-Port), fuer verstaendliche Logs
_STATUS_NAMEN = {
    0: "IDLE",
    1: "CONNECTING",
    -1: "CONNECT_FAIL",
    -2: "NO_AP_FOUND",
    -3: "WRONG_PASSWORD",
    3: "GOT_IP",
}


def _migriere_alte_konfig():
    """Liest eine wifi_config.json aus einer frueheren Version dieses
    Projekts einmalig nach wlan.conf um, damit gespeicherte Zugangsdaten
    beim Update nicht verloren gehen."""
    try:
        with open(_ALTE_KONFIG_DATEI) as f:
            daten = json.load(f)
    except (OSError, ValueError):
        return
    if daten.get("ssid"):
        speichern(daten["ssid"], daten.get("password") or "")
        print("Alte wifi_config.json nach", KONFIG_DATEI, "uebernommen")


def lade_zugangsdaten(standard_ssid="", standard_passwort=""):
    """Liest ssid/password aus KONFIG_DATEI, falls vorhanden, sonst die
    uebergebenen Standardwerte."""
    try:
        with open(KONFIG_DATEI) as f:
            daten = json.load(f)
            ssid = daten.get("ssid") or standard_ssid
            passwort = daten.get("password") or standard_passwort
            return ssid, passwort
    except (OSError, ValueError):
        _migriere_alte_konfig()
        try:
            with open(KONFIG_DATEI) as f:
                daten = json.load(f)
                return daten.get("ssid") or standard_ssid, daten.get("password") or standard_passwort
        except (OSError, ValueError):
            return standard_ssid, standard_passwort


def speichern(ssid, passwort):
    """Schreibt neue WLAN-Zugangsdaten nach KONFIG_DATEI, von wo sie beim
    naechsten Aufruf von verbinden() geladen werden."""
    with open(KONFIG_DATEI, "w") as f:
        json.dump({"ssid": ssid, "password": passwort}, f)


def hostname_setzen(name):
    try:
        network.hostname(name)
    except (AttributeError, OSError):
        pass


def _status_text(sta):
    try:
        code = sta.status()
    except OSError:
        return "unbekannt"
    return "{} ({})".format(_STATUS_NAMEN.get(code, "?"), code)


def _mit_wlan_verbinden(ssid, passwort, hostname, timeout):
    global ip
    if hostname:
        hostname_setzen(hostname)

    sta = network.WLAN(network.STA_IF)
    if hostname:
        try:
            sta.config(hostname=hostname)
        except (ValueError, OSError):
            pass
    sta.active(True)

    try:
        sta.connect(ssid, passwort)
    except OSError as exc:
        raise RuntimeError("Verbindungsfehler: {}".format(exc))

    start = time.time()
    while not sta.isconnected():
        if time.time() - start > timeout:
            raise RuntimeError("Timeout, Status: " + _status_text(sta))
        if LED is not None:
            LED.toggle()
        time.sleep(0.3)

    if LED is not None:
        LED.value(1)
    ip = sta.ifconfig()[0]
    print("Mit WLAN verbunden, IP-Adresse:", ip, "- Hostname:", hostname)
    return sta


def _verbinden_mit_wiederholung(ssid, passwort, hostname, versuche, timeout):
    for versuch in range(1, versuche + 1):
        print("WLAN-Verbindungsversuch", versuch, "von", versuche, "zu", ssid)
        try:
            return _mit_wlan_verbinden(ssid, passwort, hostname, timeout)
        except RuntimeError as exc:
            print("Versuch", versuch, "von", versuche, "fehlgeschlagen:", exc)
    return None


def hotspot_starten():
    """Oeffnet einen eigenen Access Point mit AP_SSID/AP_PASSWORT, ueber den
    eine Recovery-Webseite erreichbar ist, um neue WLAN-Zugangsdaten
    einzugeben. Wird von verbinden() aufgerufen, wenn die Verbindung zum
    konfigurierten WLAN wiederholt fehlschlaegt."""
    global ip, modus, _hotspot_start_zeit
    modus = "hotspot"
    _hotspot_start_zeit = time.time()

    try:
        network.WLAN(network.STA_IF).active(False)
    except OSError:
        pass
    time.sleep_ms(300)

    ap = network.WLAN(network.AP_IF)
    ap.config(ssid=AP_SSID, password=AP_PASSWORT)
    ap.active(True)

    start = time.time()
    while not ap.active():
        if time.time() - start > AP_START_TIMEOUT_SEK:
            print("Access Point konnte nicht gestartet werden, starte neu...")
            time.sleep(1)
            machine.reset()
        time.sleep(0.2)

    ip = ap.ifconfig()[0]
    print("Kein WLAN verbunden - Hotspot aktiv:", AP_SSID, "- IP:", ip)
    return ap


def verbinden(hostname="", standard_ssid="", standard_passwort="", versuche=None, timeout=None):
    """Laedt die Zugangsdaten (KONFIG_DATEI, sonst standard_ssid/-passwort),
    versucht mehrfach die Verbindung zum WLAN und oeffnet bei Misserfolg
    (oder falls keine SSID bekannt ist) stattdessen den Recovery-Hotspot.
    Gibt (netzwerk_objekt, modus) zurueck, modus ist "normal" oder
    "hotspot"."""
    global modus, _hostname, _standard_ssid, _standard_passwort
    _hostname = hostname
    _standard_ssid = standard_ssid
    _standard_passwort = standard_passwort
    versuche = MAX_VERSUCHE if versuche is None else versuche
    timeout = VERSUCH_TIMEOUT if timeout is None else timeout

    ssid, passwort = lade_zugangsdaten(standard_ssid, standard_passwort)
    netz = _verbinden_mit_wiederholung(ssid, passwort, hostname, versuche, timeout) if ssid else None

    if netz is not None:
        modus = "normal"
        return netz, modus

    return hotspot_starten(), "hotspot"


def status():
    """Fuer einen optionalen Status-Endpunkt: aktueller Modus, IP, Hostname
    und (im Hotspot-Modus) Hotspot-SSID sowie Restzeit bis zum
    automatischen Neustart."""
    konfigurierte_ssid, _ = lade_zugangsdaten(_standard_ssid, _standard_passwort)
    daten = {
        "modus": modus,
        "ip": ip,
        "hostname": _hostname,
        "ssid_konfiguriert": konfigurierte_ssid,
    }
    if modus == "hotspot":
        daten["hotspot_ssid"] = AP_SSID
        rest = HOTSPOT_TIMEOUT_SEK - (time.time() - _hotspot_start_zeit)
        daten["hotspot_rest_sek"] = max(0, int(rest))
    return daten


def hotspot_timeout_thread(tick=None, timeout_sek=None):
    """Fuer den Hotspot-Modus in einem eigenen Thread starten: laeuft in
    einer Sekunden-Schleife (ruft dabei optional einmal pro Sekunde tick()
    auf) und startet das Geraet nach timeout_sek (Standard:
    HOTSPOT_TIMEOUT_SEK) automatisch neu, damit regelmaessig erneut
    versucht wird, sich mit dem konfigurierten WLAN zu verbinden - auch
    wenn niemand die Einrichtungsseite ausfuellt."""
    warte_sek = HOTSPOT_TIMEOUT_SEK if timeout_sek is None else timeout_sek
    start = time.time()
    while time.time() - start < warte_sek:
        if tick is not None:
            tick()
        time.sleep(1)
    print(int(warte_sek), "Sek. im Hotspot ohne Einrichtung - versuche erneut das WLAN")
    machine.reset()
