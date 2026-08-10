"""Treiber fuer ein 16x2-LCD (HD44780-kompatibel) ueber einen I2C-PCF8574-
Backpack (das uebliche guenstige 'I2C LCD1602'-Modul). Nur die fuer einen
einfachen Testtext benoetigten Funktionen im 4-Bit-Modus."""
import time

# Bitbelegung des ueblichen PCF8574-LCD-Backpacks
_RS = 0x01
_EN = 0x04
_BACKLIGHT = 0x08


class LcdI2c:
    def __init__(self, i2c, addr=0x27, cols=16, rows=2):
        self._i2c = i2c
        self._addr = addr
        self.cols = cols
        self.rows = rows
        self._backlight = _BACKLIGHT
        self._init_display()

    def _write_byte(self, data):
        self._i2c.writeto(self._addr, bytes([data | self._backlight]))

    def _pulse_enable(self, data):
        self._write_byte(data | _EN)
        time.sleep_us(1)
        self._write_byte(data & ~_EN & 0xFF)
        time.sleep_us(50)

    def _write4(self, nibble, rs):
        data = (nibble & 0xF0) | (_RS if rs else 0)
        self._write_byte(data)
        self._pulse_enable(data)

    def _command(self, cmd):
        self._write4(cmd & 0xF0, rs=False)
        self._write4((cmd << 4) & 0xF0, rs=False)

    def _write_char(self, ch):
        code = ord(ch)
        self._write4(code & 0xF0, rs=True)
        self._write4((code << 4) & 0xF0, rs=True)

    def _init_display(self):
        time.sleep_ms(50)
        # Klassische HD44780-Initialisierungssequenz fuer den 4-Bit-Modus
        for _ in range(3):
            self._write4(0x30, rs=False)
            time.sleep_ms(5)
        self._write4(0x20, rs=False)
        time.sleep_ms(1)

        self._command(0x28)  # 4-Bit, 2 Zeilen, 5x8 Punkte
        self._command(0x08)  # Display aus
        self._command(0x01)  # Clear
        time.sleep_ms(2)
        self._command(0x06)  # Entry mode: Cursor nach rechts
        self._command(0x0C)  # Display an, Cursor/Blinken aus

    def clear(self):
        self._command(0x01)
        time.sleep_ms(2)

    def move_to(self, col, row):
        row_offsets = (0x00, 0x40, 0x14, 0x54)
        row = min(row, self.rows - 1)
        self._command(0x80 | ((col + row_offsets[row]) & 0xFF))

    def putstr(self, text):
        for ch in text:
            if ch == "\n":
                self.move_to(0, 1)
            else:
                self._write_char(ch)

    def backlight(self, on=True):
        self._backlight = _BACKLIGHT if on else 0x00
        self._write_byte(0x00)
