#!/usr/bin/env python3
"""AUTO fuvasi-irany CAN-bitek patch a F1ET-18D619-AM DEATC firmware-hez.

Reszletes leiras: HVAC_ELEMZES.md 55. szakasz.
Testverpatch: `patch_led_auto.py` (52.) -- ugyanaz a javitas, masik kimeneten.

MIT CSINAL
    A modul a `0x190` MS-CAN uzenet B5 bajtjaban (`gp-30695`) kikuldi a
    fuvasi iranyt.  A harom bitet a 0x4CD48..0x4CDAA szamolja, KIZAROLAG a
    `mode`-bol:

        bit0  ha mode in {1,4,6,7}      -> LAB        (a meres szerint, 50.3)
        bit1  MINDIG 1
        bit2  ha mode in {2,4,5,7}      -> FEJ
        bit3  ha mode in {3,5,6,7,8}    -> SZELVEDO

    AUTO (mode 9) egyik halmazba sem esik  ->  mind a harom bit torlodik
    ->  B5 = 0xF2.  Ezt a passziv MS-CAN log is igazolja (50.4).

    A patch AUTO-ban a ket mod-ajto TENYLEGES parancsabol szamolja a harom
    bitet, ugyanazokkal a MERT kuszobokkel, mint a LED-patch (50.7):

        d1 = gp-29044   (mod-ajto #1, 0..100 %,  UDS 9B01)
        d2 = gp-29048   (mod-ajto #2, 0..100 %,  UDS 9834)

        FEJ (bit2)      = d1 >= 27
        LAB (bit0)      = d1 <  47
        SZELVEDO (bit3) = d2 >= 48

HOGYAN
    Beakasztas: `0x4CDAA`  `clr1 3, -30695[gp]`  ->  `jarl rutin, lp` (4 bajt).

    Ez a cim a SZELVEDO-feltetel bukott aga, es AUTO-ban MINDIG erre fut
    (9 nincs benne a {3,5,6,7,8} halmazban).  Manualis modban vagy ide fut
    (ekkor a rutin csak az eredeti `clr1`-et vegzi el es kilep), vagy a
    0x4CDA4 `set1`-re ugrik -- oda nem nyulunk.

    Az `lp` elrontasa biztonsagos: a befoglalo fuggveny a 0x4CCC6-nal
    `prepare 31, 0x1870`-nel menti, es maga is hiv `jarl`-t (0x4CDAE).
    A rutin csak az `r1`-et es az `lp`-t irja, verem nelkul.

    A patch-terulet a belso flash-CRC hatokoren BELUL van, ezert utana
    KOTELEZO:  python tools/fwcrc.py resign <bin>

SZABAD FLASH
    0x77E00..0x77E53   a led_auto harom rutinja (84 bajt)
    0x77E54..0x77E97   EZ a rutin              (68 bajt)
    0x77E98..0x77EFF   szabad                  (104 bajt)

HASZNALAT
    python tools/patch_can_dir.py build  F1ET-18D619-AM_00008000.bin out.bin
    python tools/patch_can_dir.py verify out.bin
"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v850dis as V                                   # noqa: E402
import patch_led_auto as LED                          # noqa: E402

BASE = 0x8000
FREE_END = 0x77FF4

HOOK = 0x4CDAA
ORIG_HOOK = bytes.fromhex('c49f1988')                 # clr1 3, -30695[gp]
ROUTINE = 0x77E54                                     # a led_auto rutinjai UTAN

GP_CAN = -30695         # a 0x190 B5 bitmezo
GP_MODE = LED.GP_MODE   # -32091
GP_D1 = LED.GP_D1       # -29044
GP_D2 = LED.GP_D2       # -29048
AUTO_MODE = LED.AUTO_MODE

T_FEJ = LED.T_FEJ       # 27
T_LAB = LED.T_LAB       # 47
T_SZEL = LED.T_SZEL     # 48

BIT_LAB, BIT_FEJ, BIT_SZEL = 0, 2, 3

R0, R1, GP, LP = 0, 1, 4, 31
COND_R, COND_NZ = 5, 10                 # br (mindig) / bnz
COND_LT, COND_GE = 6, 14

ROUTINE_LEN = 0x44


# ============================================================ kodolas ========
def enc_bitop(op, bit, disp, reg1=GP):
    """Format VIII: set1/not1/clr1/tst1 bit, disp16[reg1]."""
    mode = {'set1': 0, 'not1': 1, 'clr1': 2, 'tst1': 3}[op]
    return struct.pack('<HH',
                       (mode << 14) | (bit << 11) | (0x3E << 5) | reg1,
                       disp & 0xFFFF)


# ============================================================== a rutin ======
#  +00  clr1  3, CAN          4   <- az EREDETI utasitas, amit lecsereltunk
#  +04  ld.bu MODE, r1        4
#  +08  cmp   9, r1           2
#  +0A  bnz   L_done          2   nem AUTO -> kesz
#  +0C  ld.hu D1, r1          4   --- FEJ ---
#  +10  addi  -27, r1, r1     4
#  +14  blt   L_nofej         2
#  +16  set1  2, CAN          4
#  +1A  br    L_lab           2
#  +1C  L_nofej: clr1 2, CAN  4
#  +20  L_lab: ld.hu D1, r1   4   --- LAB ---
#  +24  addi  -47, r1, r1     4
#  +28  bge   L_nolab         2
#  +2A  set1  0, CAN          4
#  +2E  br    L_szel          2
#  +30  L_nolab: clr1 0, CAN  4
#  +34  L_szel: ld.hu D2, r1  4   --- SZELVEDO ---
#  +38  addi  -48, r1, r1     4
#  +3C  blt   L_done          2   (a bit3-at a +00 mar torolte)
#  +3E  set1  3, CAN          4
#  +42  L_done: jmp [lp]      2
def build_routine(at=ROUTINE):
    L_nofej, L_lab = at + 0x1C, at + 0x20
    L_nolab, L_szel = at + 0x30, at + 0x34
    L_done = at + 0x42
    seq = [
        (enc_bitop('clr1', BIT_SZEL, GP_CAN),          'clr1     %d, %d[gp]' % (BIT_SZEL, GP_CAN)),
        (LED.enc_ld_bu(GP_MODE, GP, R1),               'ld.bu    %d[gp], r1' % GP_MODE),
        (LED.enc_cmp_imm5(AUTO_MODE, R1),              'cmp      %d, r1' % AUTO_MODE),
        (LED.enc_branch(COND_NZ, at + 0x0A, L_done),   'bnz      0x%05X' % L_done),
        (LED.enc_ld_hu(GP_D1, GP, R1),                 'ld.hu    %d[gp], r1' % GP_D1),
        (LED.enc_addi(-T_FEJ, R1, R1),                 'addi     %d, r1, r1' % -T_FEJ),
        (LED.enc_branch(COND_LT, at + 0x14, L_nofej),  'blt      0x%05X' % L_nofej),
        (enc_bitop('set1', BIT_FEJ, GP_CAN),           'set1     %d, %d[gp]' % (BIT_FEJ, GP_CAN)),
        (LED.enc_branch(COND_R, at + 0x1A, L_lab),     'br       0x%05X' % L_lab),
        (enc_bitop('clr1', BIT_FEJ, GP_CAN),           'clr1     %d, %d[gp]' % (BIT_FEJ, GP_CAN)),
        (LED.enc_ld_hu(GP_D1, GP, R1),                 'ld.hu    %d[gp], r1' % GP_D1),
        (LED.enc_addi(-T_LAB, R1, R1),                 'addi     %d, r1, r1' % -T_LAB),
        (LED.enc_branch(COND_GE, at + 0x28, L_nolab),  'bge      0x%05X' % L_nolab),
        (enc_bitop('set1', BIT_LAB, GP_CAN),           'set1     %d, %d[gp]' % (BIT_LAB, GP_CAN)),
        (LED.enc_branch(COND_R, at + 0x2E, L_szel),    'br       0x%05X' % L_szel),
        (enc_bitop('clr1', BIT_LAB, GP_CAN),           'clr1     %d, %d[gp]' % (BIT_LAB, GP_CAN)),
        (LED.enc_ld_hu(GP_D2, GP, R1),                 'ld.hu    %d[gp], r1' % GP_D2),
        (LED.enc_addi(-T_SZEL, R1, R1),                'addi     %d, r1, r1' % -T_SZEL),
        (LED.enc_branch(COND_LT, at + 0x3C, L_done),   'blt      0x%05X' % L_done),
        (enc_bitop('set1', BIT_SZEL, GP_CAN),          'set1     %d, %d[gp]' % (BIT_SZEL, GP_CAN)),
        (LED.enc_jmp_lp(),                             'jmp      [lp]'),
    ]
    blob, expect, va = b'', [], at
    for raw, txt in seq:
        expect.append((va, txt))
        blob += raw
        va += len(raw)
    assert len(blob) == ROUTINE_LEN, 'a rutin merete elcsuszott: 0x%X' % len(blob)
    addrs = {v for v, _ in expect}
    for lbl, nm in ((L_nofej, 'L_nofej'), (L_lab, 'L_lab'), (L_nolab, 'L_nolab'),
                    (L_szel, 'L_szel'), (L_done, 'L_done')):
        assert lbl in addrs, 'a %s cimke nem utasitashataron van' % nm
    return blob, expect


def bits(d1, d2):
    """A patch logikaja Pythonban -- az onteszthez (AUTO ag)."""
    v = 1 << 1                                  # bit1 mindig 1
    if d1 >= T_FEJ:
        v |= 1 << BIT_FEJ
    if d1 < T_LAB:
        v |= 1 << BIT_LAB
    if d2 >= T_SZEL:
        v |= 1 << BIT_SZEL
    return v


def label(v):
    return (('F' if v & (1 << BIT_FEJ) else '-')
            + ('L' if v & (1 << BIT_LAB) else '-')
            + ('S' if v & (1 << BIT_SZEL) else '-'))


# ============================================================== epites =======
def build(src_path, dst_path, verbose=True):
    d = bytearray(open(src_path, 'rb').read())

    def rd(a, n):
        return bytes(d[a - BASE:a - BASE + n])

    cur = rd(HOOK, 4)
    if cur != ORIG_HOOK:
        raise SystemExit('HIBA: a 0x%05X nem az eredeti 4 bajtot tartalmazza.\n'
                         '  vart:   %s\n  talalt: %s'
                         % (HOOK, ORIG_HOOK.hex(), cur.hex()))

    routine, _ = build_routine()
    if ROUTINE + len(routine) > FREE_END:
        raise SystemExit('HIBA: a rutin tullogna a belso CRC hatokoren')
    if any(b != 0xFF for b in rd(ROUTINE, len(routine))):
        raise SystemExit('HIBA: a 0x%05X terulet NEM ures (utkozes egy masik '
                         'patch rutinjaval?)' % ROUTINE)

    d[ROUTINE - BASE:ROUTINE - BASE + len(routine)] = routine
    d[HOOK - BASE:HOOK - BASE + 4] = LED.enc_jarl(HOOK, ROUTINE)
    open(dst_path, 'wb').write(bytes(d))

    if verbose:
        print('patch kiirva: %s' % dst_path)
        print('  0x%05X  hook -> 0x%05X   (%s -> %s)'
              % (HOOK, ROUTINE, ORIG_HOOK.hex(), LED.enc_jarl(HOOK, ROUTINE).hex()))
        print('  0x%05X  rutin %d bajt, %d bajt szabad flash marad'
              % (ROUTINE, len(routine), 0x77F00 - ROUTINE - len(routine)))
        print()
        print('KOVETKEZO LEPES (kotelezo):  python tools/fwcrc.py resign %s' % dst_path)
    return dst_path


# ============================================================== ellenorzes ===
def verify(path):
    d = open(path, 'rb').read()
    ok = True

    print('=== 1. A beakasztas (0x%05X) ===' % HOOK)
    got = LED._dis(d, HOOK, 1)[0]
    want = 'jarl     0x%05X, lp' % ROUTINE
    print('  %05X  %-10s %-26s%s'
          % (got[0], got[1].hex(), got[2], '' if got[2] == want else
             '   <<< ELTERES, vart: %s' % want))
    if got[2] != want:
        ok = False

    print()
    print('=== 2. Az uj rutin (0x%05X) -- VISSZADISASSEMBLALVA ===' % ROUTINE)
    _, expect = build_routine()
    for (va, raw, txt), (eva, etxt) in zip(LED._dis(d, ROUTINE, len(expect)), expect):
        bad = (va != eva or txt != etxt)
        print('  %05X  %-10s %-26s%s'
              % (va, raw.hex(), txt, '   <<< ELTERES, vart: %s' % etxt if bad else ''))
        if bad:
            ok = False

    print()
    print('=== 3. Elagazasok ===')
    for va, raw, txt in LED._dis(d, ROUTINE, len(expect)):
        if txt.split()[0] in ('bnz', 'blt', 'bge', 'br'):
            t = int(txt.split('0x')[1], 16)
            inside = ROUTINE <= t < ROUTINE + ROUTINE_LEN
            print('  0x%05X -> 0x%05X   %s' % (va, t, 'a rutinon belul' if inside
                                               else '!! KIVUL'))
            if not inside:
                ok = False

    print()
    print('=== 4. Az AUTO mert tartomanya -- ez megy ki a 0x190 B5-ben ===')
    print('  (a felso nibble gordulo szamlalo; itt csak az also 4 bit szamit)')
    for lab, d1, d2 in (('AUTO LO  (max hutes)', 59, 0),
                        ('AUTO meleg 21-22 C',   59, 0),
                        ('AUTO hideg 21-22 C',   55, 32),
                        ('AUTO kozep',           33, 32),
                        ('AUTO HI  (max futes)', 17, 40)):
        v = bits(d1, d2)
        print('  %-22s d1=%3d d2=%3d  ->  B5 also nibble 0x%X  = %s'
              % (lab, d1, d2, v, label(v)))
    print('  (patch elott mindegyik esetben 0x2 = "egyik sem")')

    print()
    print('=== 5. Konzisztencia a LED-patchcsel (52.) ===')
    for d1, d2 in ((59, 0), (33, 32), (17, 40), (21, 40), (45, 75)):
        a, b = LED.leds(d1, d2), label(bits(d1, d2))
        if a != b:
            ok = False
        print('  %s d1=%3d d2=%3d  LED=%s  CAN=%s' % ('OK ' if a == b else '!! ',
                                                      d1, d2, a, b))

    print()
    print('EREDMENY: %s' % ('MINDEN RENDBEN' if ok else 'HIBA -- NE FLASHELD'))
    return ok


if __name__ == '__main__':
    if len(sys.argv) >= 4 and sys.argv[1] == 'build':
        build(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == 'verify':
        sys.exit(0 if verify(sys.argv[2]) else 1)
    else:
        print(__doc__)
