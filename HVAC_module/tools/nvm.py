#!/usr/bin/env python3
"""A DEATC nem-felejto tar (adat-flash / EEPROM-emulacio) blokk-terkepe.

Reszletes leiras: HVAC_ELEMZES.md 43. szakasz.

  python tools/nvm.py map        # a 38 blokk teljes terkepe
  python tools/nvm.py layout     # a RAM-tukor cimrendje
  python tools/nvm.py hvac       # csak ami a klimahoz tartozik

TABLASZERKEZETEK (visszafejtve)
  0xBF84  u32 -> 0xBF90          a (blokk_id, hossz) tabla mutatoja
  0xBF88  u32 -> 0xFEDFCDDC      munkateruleti mutato
  0xBF8C  u16 db = 38,  u16 = 10
  0xBF90  38 x (u16 blokk_id, u16 hossz)
  0xC028  38 x 8 bajt:  +0 u32 a blokk RAM-kezdocime,  +4 u32 statusz-bajt cime

  FUN_29ADA(ptr)          RAM-cim -> blokk-index (linearis kereses)
  FUN_2962C(dst,src,?,n)  a blokk irasa (a RAM-tukorbe, ervenyesseg-ellenorzessel)
  FUN_299C8(ptr)          a blokk kiirasa a tarba (commit)
  FUN_58BCA(keres)        9 parancsu diszpecser a 0x58xxx transzport fele
"""
import sys
import os
import struct

BASE = 0x8000
GP = 0xFEE04000
BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                   'F1ET-18D619-AM_00008000.bin')

HDR = 0xBF8C            # u16 db, u16 ?
LENTAB = 0xBF90         # (id, hossz) parok
ADDRTAB = 0xC028        # 8 bajtos rekordok

# Amit sikerult azonositani (a hivo kodbol).  [B] = bizonyitott, [E] = becsult.
KNOWN = {
    4:  ('DTC-statusz tomb', '30 x 2 bajt, a 0xBC34 DTC-tablahoz; a 0x24166 '
         'ciklus irja egyesevel', 'B'),
    15: ('lepteto-blokk', '5 motor x 6 bajt; a lepteto-meghajto irja ki, ha a '
         'gp-29248 "piszkos" jelzo all (0x2728E)', 'B'),
    16: ('KIKAPCSOLASI BLOKK', 'a 25.5 / 39.11 soak-adat: T_levego (gp-29064), '
         'T_tomeg (gp-29066), szurt kulso ho, CAN-bajtok -- a 0x4A068 allitja '
         'ossze, a 0x4A12A irja ki', 'B'),
    9:  ('16 bajt a 0x4Cxxx modultol', 'a CAN-kuldo / A-C kornyekerol', 'E'),
    26: ('KONFIGURACIOS REKORD', 'gp-32550/32549/32548 = 3 bajtos kereskedoi '
         'beallitas (FUN_29DF0 hasonlitja ossze). gp-32549 az A-C allapotgep '
         'uzemmodja (0x39762), gp-32548 bitjei a 44.3 utolagos szaritast '
         'engedelyezik', 'B'),
    27: ('a gp-229xx allapotgep szamlaloi', 'a 27..38 azonositoju 2 bajtos '
         'blokkok mind a 44.3 allapotgephez tartoznak (gp-32604..32616)', 'B'),
}


def load():
    return open(BIN, 'rb').read()


def blocks(d):
    n, extra = struct.unpack('<HH', d[HDR - BASE:HDR - BASE + 4])
    out = []
    for i in range(n):
        bid, ln = struct.unpack('<HH', d[LENTAB - BASE + 4 * i:
                                         LENTAB - BASE + 4 * i + 4])
        addr, st = struct.unpack('<II', d[ADDRTAB - BASE + 8 * i:
                                          ADDRTAB - BASE + 8 * i + 8])
        out.append(dict(idx=i, id=bid, length=ln, addr=addr, status=st))
    return out, n, extra


def gpname(a):
    return 'gp-%d' % (GP - a) if 0xFEDF0000 <= a < GP else '0x%08X' % a


def cmd_map(d):
    bl, n, extra = blocks(d)
    tot = sum(b['length'] for b in bl)
    print('=== NVM blokk-terkep: %d blokk, osszesen %d bajt ===' % (n, tot))
    print('(fejlec 0x%05X: db=%d, %d)' % (HDR, n, extra))
    print()
    print('%-4s %-4s %-6s %-12s %-12s %s'
          % ('idx', 'id', 'hossz', 'RAM', 'statusz', 'mi ez'))
    for b in bl:
        k = KNOWN.get(b['id'])
        what = '%s  [%s]' % (k[0], k[2]) if k else ''
        print('%-4d %-4d %-6d %-12s 0x%08X   %s'
              % (b['idx'], b['id'], b['length'], gpname(b['addr']),
                 b['status'], what))
    print()
    print('Azonositott blokkok reszletesen:')
    for bid, (name, detail, conf) in sorted(KNOWN.items()):
        b = [x for x in bl if x['id'] == bid][0]
        print('  id %-3d %-22s (%d bajt, %s)  [%s]'
              % (bid, name, b['length'], gpname(b['addr']), conf))
        for line in _wrap(detail, 68):
            print('        %s' % line)


def _wrap(s, w):
    out, cur = [], ''
    for word in s.split():
        if len(cur) + len(word) + 1 > w:
            out.append(cur)
            cur = word
        else:
            cur = (cur + ' ' + word).strip()
    if cur:
        out.append(cur)
    return out


def cmd_layout(d):
    bl, n, _ = blocks(d)
    print('=== A RAM-tukor cimrendje ===')
    s = sorted(bl, key=lambda b: b['addr'])
    prev = None
    for b in s:
        gap = ''
        if prev is not None:
            d_ = b['addr'] - (prev['addr'] + prev['length'])
            if d_:
                gap = '   <- %d bajt res' % d_
        print('  0x%08X..0x%08X  %-12s id=%-3d %3d bajt%s'
              % (b['addr'], b['addr'] + b['length'] - 1, gpname(b['addr']),
                 b['id'], b['length'], gap))
        prev = b
    lo = min(x['addr'] for x in s)
    hi = max(x['addr'] + x['length'] for x in s)
    print()
    print('  tartomany: 0x%08X .. 0x%08X   (%d bajt)' % (lo, hi, hi - lo))
    sl = sorted(x['status'] for x in bl)
    print('  statusz-bajtok: 0x%08X .. 0x%08X  (%d db, folytonos: %s)'
          % (sl[0], sl[-1], len(sl),
             'igen' if sl[-1] - sl[0] == len(sl) - 1 else 'nem'))


def cmd_hvac(d):
    bl, _, _ = blocks(d)
    print('=== Amit a klimamodul atment a gyujtason ===')
    print()
    for bid in (16, 15, 4):
        b = [x for x in bl if x['id'] == bid][0]
        name, detail, conf = KNOWN[bid]
        print('id %d -- %s  (%d bajt, %s)  [%s]'
              % (bid, name, b['length'], gpname(b['addr']), conf))
        for line in _wrap(detail, 72):
            print('   %s' % line)
        print()
    print('KOVETKEZMENYEK')
    print('  - a 39.4 ketcsomopontos modell allapota (T_levego, T_tomeg) TULELI')
    print('    a gyujtast -- ezert ad a FUN_4AEF6 konstans 3-at ("mindig ervenyes"),')
    print('    es ezert tud a 39.11 indulaskor a soak-becslesbol dolgozni.')
    print('  - modulcsere / NVM-torles utan a 39.11 az alapertelmezesre esik')
    print('    (cal.h[290] = 10,4 C), es amig a statusz < 4, a 39.4 modell NEM fut.')
    print('  - a leptetok tanult pozicioi is itt vannak (id 15): egy torles utan')
    print('    a modul ujra-referal (lasd a 0xFD06/00 IO-control parancsot).')
    print('  - a DTC-k es oregedesi szamlaloik szinten (id 4).')
    print('  - a 26-os blokk a KONFIGURACIOS rekord (44.4): ez kapcsolja be az')
    print('    utolagos szaritast es allitja az A/C egyik uzemmodjat.')


def main():
    d = load()
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'map'
    if cmd == 'map':
        cmd_map(d)
    elif cmd == 'layout':
        cmd_layout(d)
    elif cmd == 'hvac':
        cmd_hvac(d)
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
