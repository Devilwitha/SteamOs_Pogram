"""MicroPython-Treiber fuer den RFID-Leser/Schreiber RC522 (MFRC522-Chip)
per SPI. Implementiert nur, was fuer diese Anwendung benoetigt wird: Tag
erkennen (Request/Anticollision), Tag auswaehlen, per Key A authentifizieren
und MIFARE-Classic-Datenbloecke lesen/schreiben.

Verkabelung (Standard-SPI0 des Pico):
    RC522 SDA(SS)  -> GP5  (CS)
    RC522 SCK      -> GP2
    RC522 MOSI     -> GP3
    RC522 MISO     -> GP4
    RC522 RST      -> GP6
    RC522 3.3V     -> 3V3
    RC522 GND      -> GND
"""
from machine import Pin, SPI
import time

# --- Register (siehe MFRC522-Datenblatt) ---
_COMMAND_REG = 0x01
_COM_IEN_REG = 0x02
_COM_IRQ_REG = 0x04
_DIV_IRQ_REG = 0x05
_ERROR_REG = 0x06
_STATUS2_REG = 0x08
_FIFO_DATA_REG = 0x09
_FIFO_LEVEL_REG = 0x0A
_CONTROL_REG = 0x0C
_BIT_FRAMING_REG = 0x0D
_MODE_REG = 0x11
_TX_CONTROL_REG = 0x14
_TX_ASK_REG = 0x15
_CRC_RESULT_REG_H = 0x21
_CRC_RESULT_REG_L = 0x22
_T_MODE_REG = 0x2A
_T_PRESCALER_REG = 0x2B
_T_RELOAD_REG_H = 0x2C
_T_RELOAD_REG_L = 0x2D

# --- PCD-Kommandos (Reader-Kommandos) ---
_PCD_IDLE = 0x00
_PCD_AUTHENT = 0x0E
_PCD_TRANSCEIVE = 0x0C
_PCD_RESETPHASE = 0x0F
_PCD_CALCCRC = 0x03

# --- PICC-Kommandos (Karten-Kommandos) ---
_PICC_REQIDL = 0x26
_PICC_ANTICOLL = 0x93
_PICC_SELECTTAG = 0x93
_PICC_READ = 0x30
_PICC_WRITE = 0xA0
_PICC_HALT = 0x50

OK = 0
NOTAGERR = 1
ERR = 2

AUTHENT1A = 0x60

# Werkseitiger Standardschluessel fuer unbeschriebene MIFARE-Classic-Karten
DEFAULT_KEY = b"\xff\xff\xff\xff\xff\xff"


class MFRC522:
    def __init__(self, spi_id=0, sck=2, mosi=3, miso=4, cs=5, rst=6, baudrate=1000000):
        self._cs = Pin(cs, Pin.OUT)
        self._cs.value(1)
        self._rst = Pin(rst, Pin.OUT)
        self._rst.value(1)

        self._spi = SPI(spi_id, baudrate=baudrate, polarity=0, phase=0,
                         sck=Pin(sck), mosi=Pin(mosi), miso=Pin(miso))

        self._init()

    # -- Low-Level SPI --
    def _wreg(self, reg, val):
        self._cs.value(0)
        self._spi.write(bytes([(reg << 1) & 0x7E, val]))
        self._cs.value(1)

    def _rreg(self, reg):
        self._cs.value(0)
        self._spi.write(bytes([((reg << 1) & 0x7E) | 0x80]))
        val = self._spi.read(1)
        self._cs.value(1)
        return val[0]

    def _setbit(self, reg, mask):
        self._wreg(reg, self._rreg(reg) | mask)

    def _clearbit(self, reg, mask):
        self._wreg(reg, self._rreg(reg) & (~mask & 0xFF))

    def _init(self):
        self._rst.value(1)
        self._wreg(_COMMAND_REG, _PCD_RESETPHASE)
        time.sleep_ms(50)

        self._wreg(_T_MODE_REG, 0x8D)
        self._wreg(_T_PRESCALER_REG, 0x3E)
        self._wreg(_T_RELOAD_REG_L, 30)
        self._wreg(_T_RELOAD_REG_H, 0)
        self._wreg(_TX_ASK_REG, 0x40)
        self._wreg(_MODE_REG, 0x3D)
        self._antenna_on()

    def _antenna_on(self):
        if not (self._rreg(_TX_CONTROL_REG) & 0x03):
            self._setbit(_TX_CONTROL_REG, 0x03)

    def _tocard(self, command, send_data):
        recv_data = []
        recv_bits = 0
        status = ERR
        irq_en = 0x00
        wait_irq = 0x00

        if command == _PCD_AUTHENT:
            irq_en = 0x12
            wait_irq = 0x10
        elif command == _PCD_TRANSCEIVE:
            irq_en = 0x77
            wait_irq = 0x30

        self._wreg(_COM_IEN_REG, irq_en | 0x80)
        self._clearbit(_COM_IRQ_REG, 0x80)
        self._setbit(_FIFO_LEVEL_REG, 0x80)
        self._wreg(_COMMAND_REG, _PCD_IDLE)

        for b in send_data:
            self._wreg(_FIFO_DATA_REG, b)

        self._wreg(_COMMAND_REG, command)
        if command == _PCD_TRANSCEIVE:
            self._setbit(_BIT_FRAMING_REG, 0x80)

        i = 2000
        while True:
            n = self._rreg(_COM_IRQ_REG)
            i -= 1
            if not (i != 0 and not (n & 0x01) and not (n & wait_irq)):
                break

        self._clearbit(_BIT_FRAMING_REG, 0x80)

        if i == 0:
            return ERR, b"", 0

        if (self._rreg(_ERROR_REG) & 0x1B) != 0x00:
            return ERR, b"", 0

        status = OK
        if n & irq_en & 0x01:
            status = NOTAGERR

        if command == _PCD_TRANSCEIVE:
            n = self._rreg(_FIFO_LEVEL_REG)
            last_bits = self._rreg(_CONTROL_REG) & 0x07
            if last_bits != 0:
                recv_bits = (n - 1) * 8 + last_bits
            else:
                recv_bits = n * 8
            if n == 0:
                n = 1
            if n > 16:
                n = 16
            for _ in range(n):
                recv_data.append(self._rreg(_FIFO_DATA_REG))

        return status, bytes(recv_data), recv_bits

    def _crc(self, data):
        self._clearbit(_DIV_IRQ_REG, 0x04)
        self._setbit(_FIFO_LEVEL_REG, 0x80)
        for b in data:
            self._wreg(_FIFO_DATA_REG, b)
        self._wreg(_COMMAND_REG, _PCD_CALCCRC)

        i = 0xFF
        while True:
            n = self._rreg(_DIV_IRQ_REG)
            i -= 1
            if not (i != 0 and not (n & 0x04)):
                break

        return bytes([self._rreg(_CRC_RESULT_REG_L), self._rreg(_CRC_RESULT_REG_H)])

    def request(self):
        """Prueft, ob eine Karte im Feld ist."""
        self._wreg(_BIT_FRAMING_REG, 0x07)
        status, _, bits = self._tocard(_PCD_TRANSCEIVE, bytes([_PICC_REQIDL]))
        if status != OK or bits != 0x10:
            return ERR
        return OK

    def anticoll(self):
        """Anti-Kollisionserkennung, liefert (status, uid-bytes)."""
        self._wreg(_BIT_FRAMING_REG, 0x00)
        status, recv, _ = self._tocard(_PCD_TRANSCEIVE, bytes([_PICC_ANTICOLL, 0x20]))

        if status == OK and len(recv) == 5:
            check = 0
            for b in recv[:4]:
                check ^= b
            if check != recv[4]:
                return ERR, None
            return OK, recv[:4]

        return ERR, None

    def select_tag(self, uid):
        buf = [_PICC_SELECTTAG, 0x70] + list(uid)
        buf += list(self._crc(buf))
        status, _, bits = self._tocard(_PCD_TRANSCEIVE, bytes(buf))
        if status == OK and bits == 0x18:
            return OK
        return ERR

    def auth(self, mode, block_addr, key, uid):
        buf = [mode, block_addr] + list(key) + list(uid)
        status, _, _ = self._tocard(_PCD_AUTHENT, bytes(buf))
        if status != OK:
            return ERR
        if not (self._rreg(_STATUS2_REG) & 0x08):
            return ERR
        return OK

    def stop_crypto1(self):
        self._clearbit(_STATUS2_REG, 0x08)

    def read(self, block_addr):
        buf = [_PICC_READ, block_addr]
        buf += list(self._crc(buf))
        status, recv, _ = self._tocard(_PCD_TRANSCEIVE, bytes(buf))
        if status == OK and len(recv) == 16:
            return recv
        return None

    def write(self, block_addr, data):
        buf = [_PICC_WRITE, block_addr]
        buf += list(self._crc(buf))
        status, recv, bits = self._tocard(_PCD_TRANSCEIVE, bytes(buf))
        if status != OK or bits != 4 or (recv[0] & 0x0F) != 0x0A:
            return ERR

        write_buf = list(data[:16]) + [0] * (16 - len(data[:16]))
        write_buf += list(self._crc(write_buf))
        status, recv, bits = self._tocard(_PCD_TRANSCEIVE, bytes(write_buf))
        if status != OK or bits != 4 or (recv[0] & 0x0F) != 0x0A:
            return ERR
        return OK

    def halt(self):
        buf = [_PICC_HALT, 0]
        buf += list(self._crc(buf))
        self._tocard(_PCD_TRANSCEIVE, bytes(buf))
