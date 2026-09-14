#!/usr/bin/env python3
"""Belso flash-integritas CRC a DEATC firmware-hez.

Bizonyitva (2026-08-21): a FUN_54218 hatterfeladat 512 bajtos adagokban vegigmegy a
0x8000..0x77FF3 tartomanyon, es a FUN_542C8 tabla-vezerelt CRC16-jat hasonlitja a
0x77FF4-en BIG ENDIAN tarolt ertekhez. Eltereskor DTC #22-t allit (FUN_24B08).

  CRC-16/CCITT-FALSE valtozat: poly 0x1021, init 0x0000, MSB-first,
  tabla a flashben 0x11FC6-nal (256 x u16, little endian).

  python tools/fwcrc.py verify <bin>
  python tools/fwcrc.py resign <bin>     # helyben ujraszamolja a 0x77FF4 erteket
"""
import sys
BASE = 0x8000
TBL  = 0x11FC6
END  = 0x77FF4          # innentol a vegeig kihagyva

def table(d):
    o = TBL - BASE
    return [int.from_bytes(d[o+2*i:o+2*i+2], 'little') for i in range(256)]

def crc(d):
    t = table(d); c = 0
    for b in d[:END-BASE]:
        c = (t[((c >> 8) ^ b) & 0xFF] ^ ((c << 8) & 0xFFFF)) & 0xFFFF
    return c

def main():
    cmd, path = sys.argv[1], sys.argv[2]
    d = bytearray(open(path, 'rb').read())
    assert len(d) == 0x70000, 'varatlan meret: %d' % len(d)
    calc = crc(d)
    stored = (d[END-BASE] << 8) | d[END-BASE+1]
    print('tarolt=%04X  szamolt=%04X  %s' % (stored, calc, 'OK' if stored == calc else 'ELTER'))
    if cmd == 'resign' and stored != calc:
        d[END-BASE] = calc >> 8; d[END-BASE+1] = calc & 0xFF
        open(path, 'wb').write(d)
        print('ujraalairva ->', path)

main()
