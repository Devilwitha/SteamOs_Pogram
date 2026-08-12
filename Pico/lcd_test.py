"""Einfacher Testlauf fuer das 16x2-I2C-LCD. Auf dem Pico ausfuehren
(z. B. per Thonny 'Run current script' oder `import lcd_test` im REPL),
sobald das Display angeschlossen ist. Ist unter der erwarteten Adresse
kein Geraet zu finden, wird die erste tatsaechlich gefundene I2C-Adresse
verwendet (die zwei gaengigen Adressen sind 0x27 und 0x3F)."""
from machine import I2C, Pin

from i2c_lcd import LcdI2c

I2C_ID = 0
SDA_PIN = 0
SCL_PIN = 1
LCD_ADDR = 0x27


def main():
    i2c = I2C(I2C_ID, sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400000)
    addrs = i2c.scan()
    print("Gefundene I2C-Geraete:", [hex(a) for a in addrs])

    if not addrs:
        print("Kein I2C-Geraet gefunden - Verkabelung pruefen (siehe README).")
        return

    addr = LCD_ADDR if LCD_ADDR in addrs else addrs[0]
    if addr != LCD_ADDR:
        print("Adresse", hex(LCD_ADDR), "nicht gefunden, verwende stattdessen", hex(addr))

    lcd = LcdI2c(i2c, addr=addr)
    lcd.clear()
    lcd.putstr("Pico bereit!\nLCD Test OK")
    print("Testtext auf dem LCD angezeigt.")


if __name__ == "__main__":
    main()
