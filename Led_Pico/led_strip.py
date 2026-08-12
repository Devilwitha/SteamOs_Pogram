"""Treiber fuer einen WS2812/NeoPixel-LED-Streifen ueber das in der
MicroPython-rp2-Firmware eingebaute neopixel-Modul (nutzt intern PIO,
kein zusaetzlicher externer Treiber noetig). Der gesamte Streifen wird
immer einheitlich auf eine Farbe gesetzt - es gibt hier bewusst keine
Pro-Pixel-Ansteuerung, das Projekt braucht nur "Streifen zeigt Farbe X
des aktuellen Spiels/Tags an"."""
from machine import Pin
import neopixel


class LedStrip:
    def __init__(self, pin, count, brightness=1.0):
        """brightness: 0.0-1.0, skaliert jede Farbe global herunter -
        nuetzlich, um viele LEDs an einem duennen USB-Netzteil nicht zu
        ueberlasten (siehe README, Stromversorgung)."""
        self._np = neopixel.NeoPixel(Pin(pin, Pin.OUT), count)
        self._count = count
        self.brightness = brightness

    def _scale(self, value):
        return max(0, min(255, int(value * self.brightness)))

    def set_color(self, r, g, b):
        color = (self._scale(r), self._scale(g), self._scale(b))
        for i in range(self._count):
            self._np[i] = color
        self._np.write()

    def off(self):
        self.set_color(0, 0, 0)


def parse_hex_color(text):
    """Parst einen Hex-Farbstring ('#ff8800', 'ff8800' oder die kurze
    Form 'f80') zu einem (r, g, b)-Tupel. Gibt bei ungueltiger Eingabe
    None zurueck, statt eine Ausnahme auszuloesen - der aufrufende
    TCP-Handler (led_server.py) antwortet dann mit ERROR:bad_color, statt
    dass eine fehlerhafte Eingabe den Server abstuerzen laesst."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return None
    try:
        r = int(text[0:2], 16)
        g = int(text[2:4], 16)
        b = int(text[4:6], 16)
    except ValueError:
        return None
    return (r, g, b)
