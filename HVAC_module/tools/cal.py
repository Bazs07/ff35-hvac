"""Valtozat-kalibracios blokk olvaso (F1ET-18D619-AM).

Hasznalat:
  python tools/cal.py curve <offset> [valtozat ...]   # toresspontos gorbe (FUN_4B3E0 formatum)
  python tools/cal.py byte  <offset> [<offset> ...]   # bajt-ertek minden valtozatban
  python tools/cal.py word  <offset> [<offset> ...]   # u16 (big endian) minden valtozatban
"""
import sys, re

BASE = 0x8000
BIN = 'F1ET-18D619-AM_00008000.bin'
BLOCK = 0x9E0

def load():
    d = open(BIN, 'rb').read()
    blocks = {}
    for m in re.finditer(rb'C34[46][A-Z]{0,4}', d):
        blocks[m.group().decode()] = BASE + m.start() - 1
    return d, blocks

def rb(d, a):  return d[a - BASE]
def rh(d, a):  # signed 16, big endian
    v = d[a - BASE] | (d[a - BASE + 1] << 8)
    return v - 0x10000 if v & 0x8000 else v
def rhu(d, a):
    return d[a - BASE] | (d[a - BASE + 1] << 8)

def curve(d, base, off):
    a = base + off
    n = rhu(d, a)
    pts = [(rh(d, a + 2 + 4*i), rh(d, a + 4 + 4*i)) for i in range(n)]
    return n, pts, a + 2 + 4*n - base   # visszaadja a kovetkezo offsetet is

def main():
    d, blocks = load()
    cmd = sys.argv[1]
    offs = [int(x, 0) for x in sys.argv[2:] if x[0].isdigit() or x.startswith('0x')]
    names = [x for x in sys.argv[2:] if not (x[0].isdigit() or x.startswith('0x'))] or list(blocks)
    for name in names:
        base = blocks[name]
        for off in offs:
            if cmd == 'curve':
                n, pts, nxt = curve(d, base, off)
                print('%-8s +0x%03X (%4d) n=%d  next=+0x%03X' % (name, off, off, n, nxt))
                print('          ' + '  '.join('(%d,%d)' % p for p in pts))
            elif cmd == 'byte':
                print('%-8s +0x%03X (%4d) = %d' % (name, off, off, rb(d, base + off)))
            elif cmd == 'word':
                print('%-8s +0x%03X (%4d) = %d (0x%04X)' % (name, off, off, rh(d, base + off), rhu(d, base + off)))
        print()

if __name__ == '__main__':
    main()
