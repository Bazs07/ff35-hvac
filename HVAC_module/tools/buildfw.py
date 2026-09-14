#!/usr/bin/env python3
"""Egyben-epito a F1ET-18D619-AM DEATC firmware-hez.

Az eredeti VBF-bol EGY LEPESBEN allit elo egy flashelheto VBF-et, tetszoleges
modositas-kombinacioval:  kicsomagol -> kod-patch -> kalibracio-patch ->
belso flash-CRC ujraalairas -> VBF becsomagolas -> TELJES ELLENORZES.

Igy nem kell a patch_autodist.py / calpatch.py / fwcrc.py / vbf.py lancot
kezzel osszefuzni, es nem lehet elfelejteni a `resign`-t.

HASZNALAT
    python tools/buildfw.py list
    python tools/buildfw.py build autodist dualzone -o F1ET-18D619-AM_COMBO.vbf
    python tools/buildfw.py build dualzone --value 64 -o dz64.vbf
    python tools/buildfw.py verify F1ET-18D619-AM_COMBO.vbf

MODOSITASOK
    autodist            kod-patch: AUTO adaptiv legelosztas (33. szakasz)
    <recept nev>        a calpatch.py barmelyik receptje (dualzone, ...)

A --value CSAK akkor ertelmes, ha PONTOSAN EGY kalibracio-receptet kersz;
tobbnel mindegyik az alapertelmezett erteket kapja.

AMI GARANTALT
  - az eredeti VBF-hez SOSEM nyulunk (csak olvassuk);
  - a kod-patch ellenorzi az eredeti 8 bajtot es a celterulet uressegét;
  - a kalibracio-patch minden tetelnel ellenorzi a vart jelenlegi erteket;
  - a vegen a blokk-CRC-nek B9A6-nak KELL lennie (a 2.5 invarians), kulonben
    a script HIBAVAL all le.
"""
import sys
import os
import re
import zlib
import struct
import argparse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
sys.path.insert(0, HERE)

import patch_autodist as AUTODIST                      # noqa: E402
import patch_led_auto as LEDAUTO                       # noqa: E402
import patch_can_dir as CANDIR                         # noqa: E402
import calpatch as CALPATCH                            # noqa: E402

BASE = 0x8000
IMG_LEN = 0x70000
CRC_AT = 0x77FF4              # a belso flash-CRC helye (big endian)
CRC_TBL = 0x11FC6             # a CRC-tabla a flashben
BLOCK_CRC_OK = 0xB9A6         # a 2.5 invarians: resign utan MINDIG ez

ORIG_VBF = os.path.join(ROOT, 'F1ET-18D619-AM.VBF')


# ===================================================== VBF ki/be =============
def _split(raw):
    i = raw.index(b'header')
    depth, j = 0, i
    while True:
        c = raw[j:j + 1]
        if c == b'{':
            depth += 1
        elif c == b'}':
            depth -= 1
            if depth == 0:
                break
        j += 1
    off = j + 1
    while raw[off] in (10, 13, 32, 9):
        off += 1
    return raw[:off], raw[off:]


def crc16(data, poly=0x1021, init=0xFFFF):
    c = init
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c


def vbf_unpack(path):
    """-> (header, addr, adat)"""
    hdr, body = _split(open(path, 'rb').read())
    addr, ln = struct.unpack('>II', body[:8])
    data = body[8:8 + ln]
    chk = struct.unpack('>H', body[8 + ln:10 + ln])[0]
    if crc16(data) != chk:
        raise SystemExit('HIBA: a forras VBF blokk-CRC-je nem stimmel')
    return hdr, addr, bytearray(data)


def vbf_pack(hdr, addr, data, out):
    nb = struct.pack('>II', addr, len(data)) + bytes(data) + \
        struct.pack('>H', crc16(bytes(data)))
    nh = re.sub(rb'file_checksum\s*=\s*0x[0-9A-Fa-f]+',
                b'file_checksum = 0x%08x' % (zlib.crc32(nb) & 0xFFFFFFFF), hdr)
    open(out, 'wb').write(nh + nb)
    return crc16(bytes(data))


# ===================================================== belso flash-CRC =======
def flash_crc(d):
    o = CRC_TBL - BASE
    t = [int.from_bytes(d[o + 2 * i:o + 2 * i + 2], 'little') for i in range(256)]
    c = 0
    for b in d[:CRC_AT - BASE]:
        c = (t[((c >> 8) ^ b) & 0xFF] ^ ((c << 8) & 0xFFFF)) & 0xFFFF
    return c


def flash_resign(d):
    c = flash_crc(d)
    d[CRC_AT - BASE] = c >> 8
    d[CRC_AT - BASE + 1] = c & 0xFF
    return c


# ===================================================== modositasok ===========
CODE_MODS = {
    'led_auto': ('AUTO fuvasi-irany LED-ek (52. szakasz) -- FLASHELVE, MUKODIK', LEDAUTO),
    'can_dir': ('AUTO fuvasi-irany CAN-bitek, 0x190 B5 (55. szakasz)', CANDIR),
    'autodist': ('AUTO adaptiv legelosztas (33.) -- ELVETVE, lasd 50.2', AUTODIST),
}


def mods_available():
    return list(CODE_MODS) + sorted(CALPATCH.RECIPES)


def describe(name):
    if name in CODE_MODS:
        return ('kod-patch', CODE_MODS[name][0])
    r = CALPATCH.RECIPES[name]
    return ('kalibracio', '%s  [alap %d, %d..%d]'
            % (r['title'], r['default'], r['lo'], r['hi']))


def apply_mods(data, mods, value, variants, tmpdir):
    """Sorban alkalmazza a modositasokat a nyers kepre.  -> valtozas-lista"""
    log = []
    src = os.path.join(tmpdir, 'stage0.bin')
    open(src, 'wb').write(bytes(data))

    for k, name in enumerate(mods):
        dst = os.path.join(tmpdir, 'stage%d.bin' % (k + 1))
        if name in CODE_MODS:
            mod = CODE_MODS[name][1]
            mod.build(src, dst, verbose=False)
            if name == 'autodist':
                where = ('0x%05X hook + 0x%05X rutin + 0x%05X tabla'
                         % (mod.HOOK, mod.ROUTINE, mod.TABLE))
            elif name == 'led_auto':
                where = ('3 hook (%s) + 0x%05X rutinok'
                         % (', '.join('0x%05X' % h[0] for h in mod.HOOKS), mod.ROUTINE_BASE))
            else:
                where = '0x%05X hook + 0x%05X rutin' % (mod.HOOK, mod.ROUTINE)
            log.append((name, 'kod', where))
        else:
            r = CALPATCH.RECIPES[name]
            val = value if value is not None else r['default']
            if not (r['lo'] <= val <= r['hi']):
                raise SystemExit('HIBA: %s ertek %d a %d..%d tartomanyon kivul'
                                 % (name, val, r['lo'], r['hi']))
            cur = src
            for v in variants:
                ed = CALPATCH.Editor(cur, v)
                ed.apply(r['fn'](val))
                ed.save(dst)
                cur = dst
                for var, what, old, new in ed.changes:
                    log.append((name, var, '%s  %d -> %d' % (what, old, new)))
        src = dst
    return bytearray(open(src, 'rb').read()), log


# ===================================================== parancsok =============
def cmd_list(a):
    print('Elerheto modositasok:\n')
    print('  %-18s %-12s %s' % ('nev', 'fajta', 'mit csinal'))
    for name in mods_available():
        kind, what = describe(name)
        print('  %-18s %-12s %s' % (name, kind, what))
    print()
    print('Pelda:  python tools/buildfw.py build autodist dualzone -o combo.vbf')


def cmd_build(a):
    import tempfile
    for m in a.mods:
        if m not in mods_available():
            raise SystemExit('HIBA: ismeretlen modositas: %s' % m)
    cal_mods = [m for m in a.mods if m not in CODE_MODS]
    if a.value is not None and len(cal_mods) != 1:
        raise SystemExit('HIBA: a --value csak PONTOSAN EGY kalibracio-recept '
                         'eseten ertelmes (most %d van)' % len(cal_mods))
    variants = (CALPATCH.EU_VARIANTS if a.variant == 'eu' else
                (list(CALPATCH.Cal('C346').blocks) if a.variant == 'all'
                 else [a.variant]))

    print('forras VBF : %s' % a.src)
    print('modositasok: %s' % ', '.join(a.mods))
    if cal_mods:
        print('valtozatok : %s' % ', '.join(variants))
    print()

    hdr, addr, data = vbf_unpack(a.src)
    if len(data) != IMG_LEN:
        raise SystemExit('HIBA: varatlan kepmeret 0x%X' % len(data))
    before = flash_crc(data)

    with tempfile.TemporaryDirectory() as td:
        data, log = apply_mods(data, a.mods, a.value, variants, td)

    print('--- valtoztatasok ---')
    for who, where, what in log:
        print('  %-12s %-8s %s' % (who, where, what))
    print()

    new_crc = flash_resign(data)
    print('belso flash-CRC: %04X -> %04X  (ujraalairva)' % (before, new_crc))
    blk = vbf_pack(hdr, addr, data, a.out)
    print('blokk-CRC      : %04X  %s' % (blk, 'OK (B9A6 invarians)'
                                         if blk == BLOCK_CRC_OK else '<<< HIBA'))
    if blk != BLOCK_CRC_OK:
        raise SystemExit('HIBA: a blokk-CRC nem B9A6 -- valami nem stimmel a '
                         'resign-nal.  A fajl NEM flashelheto.')
    print('kiirva         : %s  (%d bajt)' % (a.out, os.path.getsize(a.out)))
    print()
    _verify(a.out, a.mods, verbose=True)


def _verify(path, mods=None, verbose=True):
    hdr, body = _split(open(path, 'rb').read())
    fc = int(re.search(rb'file_checksum\s*=\s*0x([0-9A-Fa-f]+)', hdr).group(1), 16)
    calc32 = zlib.crc32(body) & 0xFFFFFFFF
    addr, ln = struct.unpack('>II', body[:8])
    data = bytearray(body[8:8 + ln])
    chk = struct.unpack('>H', body[8 + ln:10 + ln])[0]

    rows = [
        ('VBF file_checksum', '%08X' % fc, '%08X' % calc32, fc == calc32),
        ('VBF blokk-CRC', '%04X' % chk, '%04X' % crc16(bytes(data)),
         chk == crc16(bytes(data))),
        ('blokk-CRC = B9A6 (2.5)', 'B9A6', '%04X' % chk, chk == BLOCK_CRC_OK),
        ('belso flash-CRC', '%04X' % ((data[CRC_AT - BASE] << 8) |
                                      data[CRC_AT - BASE + 1]),
         '%04X' % flash_crc(data),
         ((data[CRC_AT - BASE] << 8) | data[CRC_AT - BASE + 1]) == flash_crc(data)),
    ]
    print('--- ELLENORZES: %s ---' % os.path.basename(path))
    print('  %-26s %-10s %-10s %s' % ('mit', 'tarolt', 'szamolt', ''))
    ok = True
    for what, a_, b_, good in rows:
        ok &= good
        print('  %-26s %-10s %-10s %s' % (what, a_, b_, 'OK' if good else 'HIBA'))

    if mods and 'autodist' in mods:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            t = os.path.join(td, 'v.bin')
            open(t, 'wb').write(bytes(data))
            print()
            try:
                AUTODIST.verify(t)
            except SystemExit as e:
                ok = False
                print('  autodist verify HIBA: %s' % e)
    print()
    print('EREDMENY: %s' % ('minden rendben -- flashelheto' if ok
                            else 'HIBA -- NE flasheld'))
    return ok


def cmd_verify(a):
    sys.exit(0 if _verify(a.file, a.mods) else 1)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd')

    sub.add_parser('list').set_defaults(fn=cmd_list)

    s = sub.add_parser('build')
    s.add_argument('mods', nargs='+', help='autodist es/vagy calpatch receptek')
    s.add_argument('-o', '--out', required=True)
    s.add_argument('--src', default=ORIG_VBF)
    s.add_argument('--value', type=int, default=None)
    s.add_argument('--variant', default='eu', help='eu | all | C346 | ...')
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser('verify')
    s.add_argument('file')
    s.add_argument('--mods', nargs='*', default=None)
    s.set_defaults(fn=cmd_verify)

    a = p.parse_args()
    if not getattr(a, 'fn', None):
        p.print_help()
        return 0
    return a.fn(a) or 0


if __name__ == '__main__':
    sys.exit(main())
