"""Kalibracio-betolto es gorbe-kiertekelo a F1ET-18D619-AM firmware-hez.

A firmware ket gorbe-formatumot hasznal (12. es 25. szakasz):
  FUN_4B3E0 / FUN_4B360 : u16 n, majd n x (int16 x, int16 y)
  FUN_4B2E0             : u8  n, majd n x (u8   x, u8   y)
Mindketto TORESSPONTOS LINEARIS INTERPOLACIO, a szeleken vagva
(a 0x4B42C-tol indulo ag: y = y0 + (y1-y0)*(x-x0)/(x1-x0)).

A valtozat-blokk bazisa = a valtozatnev string cime - 1, meret 0x9E0.
A szamok LITTLE ENDIAN-ok (V850).
"""
import os, re, struct

BASE = 0x8000
BIN = os.path.join(os.path.dirname(__file__), '..', 'F1ET-18D619-AM_00008000.bin')


def s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def sb(v):
    v &= 0xFF
    return v - 0x100 if v & 0x80 else v


def clip(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def pct(x):
    """A firmware fixpontos szazalek-idiomaja: (x*41)>>6, majd kesobb >>6.
    Ez a fuggveny csak az elso felet adja (a hivo vegzi a masodik >>6-ot)."""
    return (x * 41) >> 6


def interp(pts, x):
    """FUN_4B3E0 / FUN_4B2E0 szemantika."""
    if not pts:
        return 0
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            if x1 == x0:
                return y1
            return y0 + (y1 - y0) * (x - x0) // (x1 - x0)
    return pts[-1][1]


class Cal:
    def __init__(self, variant='C346', path=None):
        self.d = open(path or BIN, 'rb').read()
        self.blocks = {}
        for m in re.finditer(rb'C34[46][A-Z]{0,4}', self.d):
            self.blocks[m.group().decode()] = BASE + m.start() - 1
        if variant not in self.blocks:
            raise KeyError('%s nincs a fajlban; van: %s' % (variant, list(self.blocks)))
        self.variant = variant
        self.base = self.blocks[variant]

    # --- nyers hozzaferes az abszolut flash-cimhez ---
    def _b(self, a):   return self.d[a - BASE]
    def _h(self, a):   return struct.unpack('<H', self.d[a - BASE:a - BASE + 2])[0]
    def _sh(self, a):  return struct.unpack('<h', self.d[a - BASE:a - BASE + 2])[0]

    # --- valtozat-blokk relativ ---
    def b(self, off):  return self._b(self.base + off)          # u8
    def sbv(self, off): return sb(self._b(self.base + off))     # i8
    def h(self, off):  return self._h(self.base + off)          # u16
    def sh(self, off): return self._sh(self.base + off)         # i16

    def curve(self, off):
        """u16 toresspontos tabla a valtozat-blokkban (FUN_4B3E0 / FUN_4B360)."""
        return self._curve_abs(self.base + off)

    def bcurve(self, off):
        """u8 toresspontos tabla a valtozat-blokkban (FUN_4B2E0)."""
        a = self.base + off - BASE
        n = self.d[a]
        return [(self.d[a + 1 + 2 * i], self.d[a + 2 + 2 * i]) for i in range(n)]

    def gcurve(self, addr):
        """u16 toresspontos tabla abszolut flash-cimen (globalis gorbek)."""
        return self._curve_abs(addr)

    def _curve_abs(self, addr):
        n = self._h(addr)
        return [(self._sh(addr + 2 + 4 * i), self._sh(addr + 4 + 4 * i)) for i in range(n)]

    # --- kenyelmi ---
    def f(self, off, x):    return interp(self.curve(off), x)
    def fb(self, off, x):   return interp(self.bcurve(off), x)
    def fg(self, addr, x):  return interp(self.gcurve(addr), x)
