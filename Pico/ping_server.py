"""TCP-Server, der auf Ping-Anfragen vom SteamOS-Programm mit 'erreichbar'
antwortet, sowie ein UDP-Discovery-Server, damit SteamOS den Pico im
Netzwerk automatisch finden kann."""
import socket
import _thread

TCP_PORT = 5005
UDP_PORT = 5006
DISCOVERY_MESSAGE = b"DISCOVER_PICO"


def _tcp_server():
    addr = socket.getaddrinfo("0.0.0.0", TCP_PORT)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(4)
    print("Ping-Server laeuft auf Port", TCP_PORT)

    while True:
        cl, cl_addr = s.accept()
        try:
            cl.settimeout(2)
            data = cl.recv(64)
            if data:
                cl.send(b"erreichbar")
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
    """Startet Discovery-Server (eigener Thread) und Ping-Server (blockierend)."""
    _thread.start_new_thread(_udp_discovery_server, (my_ip,))
    _tcp_server()
