"""TCP-Server, der Anfragen von SteamOS beantwortet, sowie ein
UDP-Discovery-Server, damit SteamOS den Pico im Netzwerk automatisch
findet.

Zeilenbasiertes Protokoll ueber TCP:
    PING              -> "erreichbar"
    SELECT:<uid>      -> UID wird in SELECTED_GAME_FILE gespeichert,
                          Antwort "OK:<uid>" bestaetigt den Empfang
"""
import socket
import _thread

TCP_PORT = 5005
UDP_PORT = 5006
DISCOVERY_MESSAGE = b"DISCOVER_PICO"
SELECTED_GAME_FILE = "selected_game.txt"


def _handle_command(command):
    command = command.strip()

    if command == "PING":
        return "erreichbar"

    if command.startswith("SELECT:"):
        uid = command[len("SELECT:"):].strip()
        if not uid:
            return "ERROR:empty_uid"
        try:
            with open(SELECTED_GAME_FILE, "w") as f:
                f.write(uid)
        except OSError:
            return "ERROR:write_failed"
        return "OK:" + uid

    return "ERROR:unknown_command"


def _read_line(cl, max_len=256):
    data = b""
    while not data.endswith(b"\n") and len(data) < max_len:
        chunk = cl.recv(64)
        if not chunk:
            break
        data += chunk
    return data.decode(errors="ignore").strip()


def _tcp_server():
    addr = socket.getaddrinfo("0.0.0.0", TCP_PORT)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(4)
    print("Steuer-Server laeuft auf Port", TCP_PORT)

    while True:
        cl, cl_addr = s.accept()
        try:
            cl.settimeout(3)
            command = _read_line(cl)
            if command:
                response = _handle_command(command)
                print("Befehl:", command, "-> Antwort:", response)
                cl.send((response + "\n").encode())
        except OSError:
            pass
        finally:
            cl.close()


def _udp_discovery_server(my_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", UDP_PORT))
    print("Discovery-Server laeuft auf Port", UDP_PORT)

    while True:
        try:
            data, addr = s.recvfrom(64)
            if data == DISCOVERY_MESSAGE:
                s.sendto(("PICO:" + my_ip).encode(), addr)
        except OSError:
            pass


def start(my_ip):
    """Startet Discovery-Server (eigener Thread) und Steuer-Server (blockierend)."""
    _thread.start_new_thread(_udp_discovery_server, (my_ip,))
    _tcp_server()
