"""TCP-Steuer-Server + UDP-Discovery-Server fuer den Led_Pico.

Deutlich einfacher als Pico/ping_server.py: der Led_Pico hat kein
RFID-Polling und braucht deshalb keinen zusaetzlichen Hintergrund-Thread
(die "nur ein Zusatz-Thread"-Einschraenkung des RP2040/RP2350, siehe
Pico/README.md, spielt hier also keine Rolle) - TCP- und UDP-Socket
laufen gemeinsam per select() im Hauptthread.

Zeilenbasiertes Protokoll ueber TCP (Standard-Port 5007):
    PING          -> "erreichbar"
    COLOR:<hex>   -> setzt den LED-Streifen auf die angegebene Farbe
                     (z.B. '#ff8800', 'ff8800' oder die Kurzform 'f80');
                     Antwort "OK:COLOR:<hex>" oder bei ungueltiger Farbe
                     "ERROR:bad_color"
    OFF           -> schaltet den LED-Streifen aus; Antwort "OK:OFF"

UDP-Discovery (Standard-Port 5008), damit SteamOS den Led_Pico automatisch
im Netzwerk findet:
    DISCOVER_LED_PICO -> Antwort "LEDPICO:<eigene-ip>"
"""
import select
import socket

import led_strip

TCP_PORT = 5007
UDP_PORT = 5008
DISCOVERY_MESSAGE = b"DISCOVER_LED_PICO"


def _handle_command(command, strip):
    command = command.strip()

    if command == "PING":
        return "erreichbar"

    if command.startswith("COLOR:"):
        hex_value = command[len("COLOR:"):].strip()
        rgb = led_strip.parse_hex_color(hex_value)
        if rgb is None:
            return "ERROR:bad_color"
        strip.set_color(*rgb)
        return "OK:COLOR:" + hex_value

    if command == "OFF":
        strip.off()
        return "OK:OFF"

    return "ERROR:unknown_command"


def _read_line(cl, max_len=256):
    data = b""
    while not data.endswith(b"\n") and len(data) < max_len:
        chunk = cl.recv(64)
        if not chunk:
            break
        data += chunk
    return data.decode().strip()


def _handle_tcp_client(cl, strip):
    try:
        cl.settimeout(3)
        command = _read_line(cl)
        if command:
            response = _handle_command(command, strip)
            print("Befehl:", command, "-> Antwort:", response)
            cl.send((response + "\n").encode())
    except Exception as e:
        print("TCP-Fehler:", e)
    finally:
        cl.close()


def start(my_ip, strip):
    """Startet TCP-Steuer- und UDP-Discovery-Server gemeinsam
    (blockierend im aufrufenden Thread) - siehe Modul-Docstring."""
    tcp = socket.socket()
    tcp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp.bind(socket.getaddrinfo("0.0.0.0", TCP_PORT)[0][-1])
    tcp.listen(4)

    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp.bind(("0.0.0.0", UDP_PORT))

    print("Led_Pico: Steuer-Server (TCP", TCP_PORT, ") und Discovery (UDP", UDP_PORT, ") laufen")

    while True:
        readable, _w, _e = select.select([tcp, udp], [], [], 1.0)
        for s in readable:
            if s is tcp:
                cl, _addr = tcp.accept()
                _handle_tcp_client(cl, strip)
            else:
                try:
                    data, addr = udp.recvfrom(64)
                    if data == DISCOVERY_MESSAGE:
                        udp.sendto(("LEDPICO:" + my_ip).encode(), addr)
                except OSError:
                    pass
