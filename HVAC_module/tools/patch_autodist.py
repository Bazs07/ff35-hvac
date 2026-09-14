#!/usr/bin/env python3
"""AUTO adaptiv legelosztas patch a F1ET-18D619-AM DEATC firmware-hez.

Reszletes leiras: HVAC_ELEMZES.md 33. szakasz.

MIT CSINAL
    A 0x44C44-nel az AUTO ag a mod-ajto poziciojat egy BEEGETETT konstansbol
    veszi (cal.h[358] >> 1 = 58, mind a hat valtozatban ugyanaz).  Emiatt
    AUTO-ban a legelosztas nem alkalmazkodik, es az iranybitek/LED-ek sem
    valtoznak.

    A patch ezt a konstanst egy TORESSPONTOS GORBEVEL valtja ki, aminek a
    bemenete a gp-28665 (FUN_3F28A) -- az az ertek, amit a firmware maga
    kuld a mod-ajtok fele.

    A gorbe toresspontjai a firmware SAJAT manualis tablajanak (cal+2320)
    ertekei: fej = 21, fej+lab = 33, lab = 60.  A patch tehat nem tesz semmi
    ujat: AUTO-ban ugyanoda allitja az ajtot, ahova kezi modban a gomb.

HOGYAN
    A csere pontosan 8 bajt es HELYBEN elfer -- nem kell trambulin:
        0x44C44  ld.hu -31164[gp], r1   ->  jarl 0x77E00, lp
        0x44C48  st.h  r1,  -31160[gp]  ->  st.h r10, -31160[gp]
    Az uj rutin a szabad flashben (0x77E00), a gorbe tablaja 0x77E40-nel.
    A prolog/epilog BYTE-MASOLAT a FUN_4B0EA-bol (ugyanolyan alaku fuggveny),
    hogy a prepare/dispose par garantaltan konzisztens legyen.

    A patch-terulet a belso flash-CRC hatokoren BELUL van (0x8000..0x77FF3),
    ezert utana KOTELEZO:  python tools/fwcrc.py resign <bin>

HASZNALAT
    python tools/patch_autodist.py build  F1ET-18D619-AM_00008000.bin out.bin
    python tools/patch_autodist.py verify out.bin
    python tools/patch_autodist.py revert out.bin orig.bin      # osszevetes
"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v850dis as V                                   # noqa: E402

BASE = 0x8000

# --- cimek ------------------------------------------------------------------
HOOK = 0x44C44          # a lecserelendo ket utasitas
ROUTINE = 0x77E00       # az uj rutin
TABLE = 0x77E40         # a gorbe tablaja
FREE_END = 0x77FF4      # innentol a belso CRC nem szamol -> ne irjunk ide

SRC_GETTER = 0x3F28A    # FUN_3F28A -> r10 = gp-28665
SRC_INTERP = 0x4B3E0    # FUN_4B3E0(tabla, x, irany) toresspontos interpolacio
SRC_PROLOG = 0x4B0EA    # FUN_4B0EA prolog  (prepare 0, 0x0010)
SRC_EPILOG = 0x4B0FE    # FUN_4B0EA epilog  (dispose 0, 0x001F, [lp])

# --- az eredeti 8 bajt, amit lecserelunk (biztonsagi ellenorzeshez) ---------
ORIG_HOOK = bytes.fromhex('E40F4586' '640F4886')

# --- a javasolt gorbe (33.2) ------------------------------------------------
# (gp-28665, ajto1 pozicio) ; a toresspontok a cal+2320 tabla ertekei
CURVE = [(0, 21), (80, 21), (110, 33), (160, 60), (255, 60)]

LP = 31                 # link register


# ============================================================ kodolas ========
def enc_jarl(va, target, reg2=LP):
    """Format V: disp[21:16] a hw1[5:0]-ban, disp[15:1] a hw2[15:1]-ben.
    (A v850dis dekodolojabol visszafejtve, valodi hivasokon ellenorizve.)"""
    disp = target - va
    if disp % 2:
        raise ValueError('paratlan ugrastavolsag')
    if not -(1 << 21) <= disp < (1 << 21):
        raise ValueError('a jarl 22 bites hatarat tullepi: %d' % disp)
    d = disp & 0x3FFFFF
    hw1 = (reg2 << 11) | (0x3C << 5) | ((d >> 16) & 0x3F)
    hw2 = d & 0xFFFE
    return struct.pack('<HH', hw1, hw2)


def enc_mov_reg(src, dst):
    """Format I: mov reg1, reg2  (opcode 0x00)."""
    return struct.pack('<H', (dst << 11) | (0x00 << 5) | src)


def enc_mov_imm5(imm, dst):
    """Format II: mov imm5, reg2 (opcode 0x10)."""
    return struct.pack('<H', (dst << 11) | (0x10 << 5) | (imm & 0x1F))


def enc_mov_imm32(imm, dst):
    """V850E 48 bites: mov imm32, reg1 (a movea slotban, reg2 == 0)."""
    return struct.pack('<H', (0 << 11) | (0x31 << 5) | dst) + struct.pack('<I', imm)


def enc_curve(points):
    """FUN_4B3E0 tablaformatum: u16 n, majd n x (int16 x, int16 y)."""
    out = struct.pack('<H', len(points))
    for x, y in points:
        out += struct.pack('<hh', x, y)
    return out


def retarget_reg2(hw, reg2):
    """Egy 16 bites utasitas reg2 mezojenek atirasa (st.h r1 -> st.h r10)."""
    return (hw & 0x07FF) | (reg2 << 11)


# ============================================================== epites =======
def build(src_path, dst_path, curve=CURVE, verbose=True):
    d = bytearray(open(src_path, 'rb').read())

    def rd(a, n):
        return bytes(d[a - BASE:a - BASE + n])

    def wr(a, blob):
        d[a - BASE:a - BASE + len(blob)] = blob

    # --- 1. biztonsagi ellenorzesek -----------------------------------------
    cur = rd(HOOK, 8)
    if cur != ORIG_HOOK:
        raise SystemExit('HIBA: a 0x%05X nem az eredeti 8 bajtot tartalmazza.\n'
                         '  vart: %s\n  talalt: %s\n'
                         '  (mar patchelt fajl, vagy mas firmware-verzio)'
                         % (HOOK, ORIG_HOOK.hex(), cur.hex()))

    routine = (rd(SRC_PROLOG, 4)
               + enc_jarl(ROUTINE + 4, SRC_GETTER)
               + enc_mov_reg(10, 7)
               + enc_mov_imm32(TABLE, 6)
               + enc_mov_imm5(0, 8)
               + enc_jarl(ROUTINE + 18, SRC_INTERP)
               + rd(SRC_EPILOG, 4))
    table = enc_curve(curve)

    used_end = max(ROUTINE + len(routine), TABLE + len(table))
    if used_end > FREE_END:
        raise SystemExit('HIBA: a patch tullogna a belso CRC hatokoren (0x%05X)' % FREE_END)
    if ROUTINE + len(routine) > TABLE:
        raise SystemExit('HIBA: a rutin belelog a tablaba')
    for a, n, what in ((ROUTINE, len(routine), 'rutin'), (TABLE, len(table), 'tabla')):
        if any(b != 0xFF for b in rd(a, n)):
            raise SystemExit('HIBA: a 0x%05X (%s) terulet NEM ures' % (a, what))

    # --- 2. iras -------------------------------------------------------------
    wr(ROUTINE, routine)
    wr(TABLE, table)
    hook = enc_jarl(HOOK, ROUTINE)
    sth = struct.unpack('<H', ORIG_HOOK[4:6])[0]        # st.h r1, -31160[gp]
    hook += struct.pack('<H', retarget_reg2(sth, 10)) + ORIG_HOOK[6:8]
    assert len(hook) == 8
    wr(HOOK, hook)

    open(dst_path, 'wb').write(bytes(d))

    if verbose:
        print('patch kiirva: %s' % dst_path)
        print('  0x%05X  hook   %s   (%d bajt)' % (HOOK, hook.hex(), len(hook)))
        print('  0x%05X  rutin  %s   (%d bajt)' % (ROUTINE, routine.hex(), len(routine)))
        print('  0x%05X  tabla  %s   (%d bajt)' % (TABLE, table.hex(), len(table)))
        print()
        print('KOVETKEZO LEPES (kotelezo, kulonben 22-es DTC):')
        print('  python tools/fwcrc.py resign %s' % dst_path)
        print('  python tools/vbf.py pack F1ET-18D619-AM.VBF %s uj.vbf' % dst_path)
    return dst_path


# ============================================================== ellenorzes ===
def _dis(d, va, count):
    out = []
    off = va - BASE
    for _ in range(count):
        i = V.decode(d, off, BASE + off)
        txt = str(i).split('  ', 1)[-1].strip()
        txt = txt.split(';')[0].strip()          # a "; -> 0x.." megjegyzes levagasa
        out.append((BASE + off, bytes(d[off:off + i.size]), txt))
        off += i.size
    return out


def verify(path, curve=CURVE):
    d = open(path, 'rb').read()
    ok = True

    print('=== 1. A beakasztas (0x%05X) ===' % HOOK)
    for va, raw, txt in _dis(d, HOOK, 2):
        print('  %05X  %-12s %s' % (va, raw.hex(), txt))
    exp_tgt = 'jarl     0x%05X, lp' % ROUTINE
    got = _dis(d, HOOK, 1)[0][2]
    if got != exp_tgt:
        print('  !! vart: %s' % exp_tgt)
        ok = False
    if 'st.h     r10, -31160[gp]' not in _dis(d, HOOK, 2)[1][2]:
        print('  !! a masodik utasitasnak st.h r10, -31160[gp]-nek kell lennie')
        ok = False

    print()
    print('=== 2. Az uj rutin (0x%05X) ===' % ROUTINE)
    for va, raw, txt in _dis(d, ROUTINE, 7):
        print('  %05X  %-12s %s' % (va, raw.hex(), txt))
    txts = [t for _, _, t in _dis(d, ROUTINE, 7)]
    for want in ('jarl     0x%05X, lp' % SRC_GETTER, 'jarl     0x%05X, lp' % SRC_INTERP):
        if want not in txts:
            print('  !! hianyzik: %s' % want)
            ok = False

    print()
    print('=== 3. A gorbe tablaja (0x%05X) ===' % TABLE)
    o = TABLE - BASE
    n = struct.unpack('<H', d[o:o + 2])[0]
    pts = [struct.unpack('<hh', d[o + 2 + 4 * i:o + 6 + 4 * i]) for i in range(n)]
    print('  n = %d   %s' % (n, '  '.join('(%d,%d)' % p for p in pts)))
    if pts != [tuple(p) for p in curve]:
        print('  !! nem egyezik a vart gorbevel: %s' % curve)
        ok = False

    print()
    print('=== 4. Mit csinal (a modell szerint) ===')
    try:
        from model import Deatc, interp
        m = Deatc('C346')
        print('  %9s %10s %10s' % ('gp-28665', 'ajto1 regi', 'ajto1 uj'))
        for t in (30, 20, 10, 0, -10):
            dem = m.climate(t * 10, 44, 44)['gp28665']
            print('  %9d %10d %10d' % (dem, m.c.h(358) >> 1, interp(pts, dem)))
    except Exception as e:                              # pragma: no cover
        print('  (modell nem futtathato: %s)' % e)

    print()
    print('EREDMENY: %s' % ('OK' if ok else 'HIBA -- ne flashelj!'))
    return ok


def revert_diff(patched, orig):
    a = open(patched, 'rb').read()
    b = open(orig, 'rb').read()
    if len(a) != len(b):
        print('kulonbozo meret!')
        return
    runs = []
    i = 0
    while i < len(a):
        if a[i] != b[i]:
            j = i
            while j < len(a) and a[j] != b[j]:
                j += 1
            runs.append((BASE + i, j - i))
            i = j
        else:
            i += 1
    print('eltero tartomanyok (%d db):' % len(runs))
    for va, n in runs:
        print('  0x%05X  %3d bajt   %s -> %s'
              % (va, n, b[va - BASE:va - BASE + n].hex(), a[va - BASE:va - BASE + n].hex()))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    cmd = sys.argv[1]
    if cmd == 'build':
        build(sys.argv[2], sys.argv[3])
    elif cmd == 'verify':
        sys.exit(0 if verify(sys.argv[2]) else 1)
    elif cmd == 'revert':
        revert_diff(sys.argv[2], sys.argv[3])
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
