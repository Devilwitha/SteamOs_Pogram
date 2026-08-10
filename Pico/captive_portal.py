"""Einfacher Webserver auf Port 80, der eine WLAN-Einrichtungsseite anzeigt
und eingegebene Zugangsdaten speichert (laeuft im Access-Point-Modus)."""
import socket
from wifi_manager import save_credentials

PAGE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pico WLAN Einrichtung</title>
<style>
body{{font-family:sans-serif;background:#1b1f24;color:#eee;display:flex;justify-content:center;padding-top:40px;margin:0}}
form{{background:#262b33;padding:24px;border-radius:8px;width:280px}}
input{{width:100%;padding:8px;margin:8px 0;border-radius:4px;border:none;box-sizing:border-box}}
button{{width:100%;padding:10px;background:#1a9fff;color:#fff;border:none;border-radius:4px;font-weight:bold}}
h2{{text-align:center;margin-top:0}}
p{{font-size:0.85em;color:#aaa}}
</style>
</head>
<body>
<form method="POST" action="/save">
<h2>WLAN einrichten</h2>
{message}
<input type="text" name="ssid" placeholder="WLAN Name (SSID)" required>
<input type="password" name="password" placeholder="WLAN Passwort" required>
<button type="submit">Speichern &amp; Verbinden</button>
<p>Der Pico startet nach dem Speichern neu und versucht sich zu verbinden.</p>
</form>
</body>
</html>
"""


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
            request = b""
            cl.settimeout(3)
            try:
                while b"\r\n\r\n" not in request:
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
                    response_html = PAGE.format(
                        message="<p style='color:#4caf50'>Gespeichert! Neustart...</p>"
                    )
                    cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + response_html)
                    cl.close()
                    on_credentials_saved()
                    continue
                else:
                    response_html = PAGE.format(message="<p style='color:#f44336'>Bitte alle Felder ausfuellen.</p>")
            else:
                response_html = PAGE.format(message="")

            cl.send("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n\r\n" + response_html)
        except Exception as e:
            print("Fehler im Webserver:", e)
        finally:
            cl.close()
