#!/usr/bin/env python3
"""Laeuft dauerhaft im Hintergrund (siehe steamos-lilygo-monitor.service)
und schickt CPU-/GPU-Auslastung sowie eine Temperatur (siehe
system_stats.py) in regelmaessigen Abstaenden an das optionale
LilyGo-Statusdisplay (siehe ../lilygo und lilygo_link.py).

Bewusst als eigener Dienst statt in pico_client.py mit eingebaut: anders
als der RFID-Pico (fuers Spielstarten zwingend noetig) ist das Display rein
informativ und voellig unabhaengig vom Tag-/Spielstart-Ablauf - ein Ausfall
oder Neustart des einen Diensts soll den anderen nicht beeinflussen.

Genau wie beim Led_Pico ist das Geraet komplett optional: ist keins im
Netzwerk konfiguriert/erreichbar, laeuft die Suche einfach im Hintergrund
weiter, ohne dass das sonst irgendwelche Auswirkungen hat.
"""
import time

import lilygo_link
import system_stats


def main():
    config = lilygo_link.load_config()
    interval = config.get("interval_seconds", 2)
    tcp_port = config.get("tcp_port", 5009)
    udp_port = config.get("udp_port", 5010)
    # Fest in lilygo_config.json eingetragene IP bleibt die ganze Laufzeit
    # ueber massgeblich (siehe unten) - nur ohne konfigurierte IP wird bei
    # Verbindungsverlust per Broadcast neu gesucht (analog pico_client.py).
    configured_ip = config.get("lilygo_ip") or None
    lilygo_ip = configured_ip

    print("SteamOS <-> LilyGo Stats-Monitor gestartet", flush=True)

    while True:
        if not lilygo_ip:
            print("Suche LilyGo-Display im Netzwerk...", flush=True)
            lilygo_ip = lilygo_link.discover_lilygo(udp_port)
            if lilygo_ip:
                print(f"LilyGo-Display gefunden unter {lilygo_ip}", flush=True)

        if lilygo_ip:
            timestamp = time.strftime("%H:%M:%S")
            if lilygo_link.ping_lilygo(lilygo_ip, tcp_port):
                cpu = system_stats.cpu_percent()
                gpu = system_stats.gpu_percent()
                temp = system_stats.temperature()
                if lilygo_link.send_stats(lilygo_ip, tcp_port, cpu, gpu, temp):
                    print(f"[{timestamp}] CPU {cpu}% GPU {gpu}% {temp}°C -> {lilygo_ip}", flush=True)
                else:
                    print(f"[{timestamp}] Senden an {lilygo_ip} fehlgeschlagen.", flush=True)
            else:
                print(f"[{timestamp}] LilyGo-Display nicht erreichbar, versuche erneut...", flush=True)
                if not configured_ip:
                    # Nur eine automatisch gefundene IP wird verworfen und
                    # neu gesucht - eine fest konfigurierte bleibt bestehen
                    # (self-healing nach z. B. einem Neustart des Displays).
                    lilygo_ip = None

        time.sleep(interval)


if __name__ == "__main__":
    main()
