"""Einfacher Webserver auf Port 80, der eine WLAN-Einrichtungsseite anzeigt
und eingegebene Zugangsdaten speichert (laeuft im Access-Point-Modus)."""
import socket
from wlan import speichern as save_credentials

with open("setup.html") as _f:
    PAGE = _f.read()


def _render(message_html):
    return PAGE.replace("__MESSAGE__", message_html)


def _send_html(cl, html):
    body_bytes = html.encode()
    header = "HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n".format(
        len(body_bytes)
    )
    data = header.encode() + body_bytes
    sent = 0
    while sent < len(data):
        n = cl.send(data[sent:])
        if not n:
            break
        sent += n


def _url_decode(s):
    s = s.replace("+", " ")
    result = ""
    i = 0
    while i < len(s):
        if s[i] == "%" and i + 2 < len(s):
            result += chr(int(s[i + 1:i + 3], 16))
            i += 3
        else:
            result += s[i]
            i += 1
    return result


def _parse_form(body):
    data = {}
    for pair in body.split("&"):
        if "=" in pair:
            k, v = pair.split("=", 1)
            data[_url_decode(k)] = _url_decode(v)
    return data


def run(on_credentials_saved):
    """Startet den Setup-Webserver. `on_credentials_saved` wird aufgerufen,
    sobald gueltige Zugangsdaten gespeichert wurden (z.B. um neu zu starten)."""
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(2)
    print("Setup-Webseite laeuft auf Port 80")

    while True:
        cl, cl_addr = s.accept()
        try:
            # Bis zum Ende der Header (\r\n\r\n) lesen und damit verwerfen -
            # bleiben ungelesene Bytes im Socket-Puffer, wenn cl.close()
            # aufgerufen wird, kann der TCP-Stack ein RST statt eines
            # sauberen FIN senden und der Browser verwirft die Antwort.
            request = b""
            cl.settimeout(3)
            try:
                while b"\r\n\r\n" not in request and len(request) < 4096:
                    chunk = cl.recv(1024)
                    if not chunk:
                        break
                    request += chunk
            except OSError:
                pass

            request_text = request.decode()
            header_part, _, rest = request_text.partition("\r\n\r\n")

            if request_text.startswith("POST /save"):
                content_length = 0
                for line in header_part.split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        content_length = int(line.split(":", 1)[1].strip())

                body = rest
                while len(body) < content_length:
                    body += cl.recv(1024).decode()

                form = _parse_form(body)
                ssid = form.get("ssid", "")
                password = form.get("password", "")

                if ssid and password:
                    save_credentials(ssid, password)
                    _send_html(cl, _render("<p style='color:#4caf50'>Gespeichert! Neustart...</p>"))
                    cl.close()
                    on_credentials_saved()
                    continue
                else:
                    response_html = _render("<p style='color:#f44336'>Bitte alle Felder ausfuellen.</p>")
            else:
                response_html = _render("")

            _send_html(cl, response_html)
        except Exception as e:
            print("Fehler im Webserver:", e)
        finally:
            cl.close()
