#!/usr/bin/env python3
"""AUTO fuvasi-irany LED patch a F1ET-18D619-AM DEATC firmware-hez -- V2.

Reszletes leiras: HVAC_ELEMZES.md 9., 50., 51. es 52. szakasz.

MIERT V2
    A V1 a mode-9 allapotfuggvenybe (FUN_37820, 0x37848) akaszkodott be.
    AUTOBAN KIPROBALVA: egy LED kigyulladt, de SOHA NEM VALTOTT.
    Ok: a mod-diszpecsert a 0x2EF34-nel egy kapu (gp-31922) vedi, ezert a
    FUN_37820 nem fut ciklusonkent -- a harom iranybajt AUTO-ba lepeskor
    egyszer beallt, es befagyott.  (52.1)

    A V2 ezert a FOGYASZTOI oldalra akaszkodik: oda, ahol a firmware
    ciklusonkent atmasolja a harom bajtot a LED-struktuiraba (gp-31888).
    Ez konstrukcional fogva minden ciklusban fut -- ez az a kod, ami a
    LED-eket eteti.

MIT CSINAL
    Harom 4 bajtos csere, mindegyik egy `ld.bu`-t valt ki egy `jarl`-ra:

        0x31420  ld.bu -32097[gp], r1   ->  jarl LAB_rutin,  lp
        0x31440  ld.bu -32088[gp], r1   ->  jarl FEJ_rutin,  lp
        0x31460  ld.bu -32087[gp], r1   ->  jarl SZEL_rutin, lp

    Mindharom rutin r1-ben adja vissza az erteket; a csere utani, VALTOZATLAN
    `st.b r1, -3188x[gp]` tarolja el.  Mindharom rutin eloszor megnezi, hogy
    `gp-32091 == 9` (AUTO):

        ha NEM AUTO  ->  visszaadja az EREDETI bajtot   (manualis mod valtozatlan)
        ha AUTO      ->  szamol a ket mod-ajto parancsabol:

            d1 = gp-29044   (mod-ajto #1, 0..100 %,  UDS 9B01, lepteto 1)
            d2 = gp-29048   (mod-ajto #2, 0..100 %,  UDS 9834, lepteto 4)

            FEJ      = d1 >= 27      ; (33+21)/2
            LAB      = d1 <  47      ; (59+33)/2
            SZELVEDO = d2 >= 48      ; (40+55)/2

    A kuszobok a felhasznalo sajat, autoban mert manualis tablajabol jonnek
    (50.5) -- nem a dokumentaciobol, ami a fej/lab hozzarendelest forditva
    tartalmazta (50.3).

    A LAB-nak a V1-ben volt also kuszobe is (d1 >= 5), hogy a tiszta
    szelvedo-allast (d1 = 0) elvalassza.  A V2-ben erre NINCS SZUKSEG: az ag
    csak AUTO-ban fut, ahol a mert d1-tartomany 17..60, es manualis modban a
    rutin az eredeti bajtot adja vissza.  Igy egy `setf` elintezi.

HOGYAN
    A `jarl` elrontja az lp-t.  Ez itt BIZTONSAGOS: a befoglalo fuggveny a
    0x2E8C8-nal `prepare 9, 0x79F0`-val menti, a 0x314FA-nal
    `dispose 9, 0x79FF, [lp]`-vel allitja vissza, es maga is hiv `jarl`-t
    a testeben (0x30D56, 0x31510).  (52.2)

    A rutinok CSAK az r1-et es az lp-t irjak -- nincs verem-hasznalat.

    A patch-terulet a belso flash-CRC hatokoren BELUL van (0x8000..0x77FF3),
    ezert utana KOTELEZO:  python tools/fwcrc.py resign <bin>

HASZNALAT
    python tools/patch_led_auto.py build  F1ET-18D619-AM_00008000.bin out.bin
    python tools/patch_led_auto.py verify out.bin
"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import v850dis as V                                   # noqa: E402

BASE = 0x8000
FREE_END = 0x77FF4      # innentol a belso CRC nem szamol

# --- valtozok ---------------------------------------------------------------
GP_MODE = -32091        # a mod-allapotgep sajat mode-valtozoja (9 == AUTO)
GP_D1 = -29044          # mod-ajto #1 parancs (halfword, 0..100)
GP_D2 = -29048          # mod-ajto #2 parancs (halfword, 0..100)
GP_FEJ = -32088         # a mode 2 (FEJ gomb) ide ir 1-et    -> LED csatorna 16
GP_LAB = -32097         # a mode 1 (LAB gomb) ide ir 1-et    -> LED csatorna 17
GP_SZEL = -32087        # a mode 3 (SZELVEDO) ide ir 1-et    -> LED csatorna 15

AUTO_MODE = 9

# --- kuszobok (HVAC_ELEMZES.md 50.7, meresbol) ------------------------------
T_FEJ = 27              # FEJ  ha d1 >= 27
T_LAB = 47              # LAB  ha d1 <  47   (azaz d1 <= 46)
T_SZEL = 48             # SZEL ha d2 >= 48

# --- regiszterszamok es feltetelkodok ---------------------------------------
R0, R1, GP, LP = 0, 1, 4, 31
COND_Z, COND_NZ = 2, 10
COND_LT, COND_GE = 6, 14


# ============================================================ kodolas ========
def _f1(opc, r1, r2):
    return struct.pack('<H', (r2 << 11) | (opc << 5) | r1)


def _f2(opc, imm5, r2):
    return struct.pack('<H', (r2 << 11) | (opc << 5) | (imm5 & 0x1F))


def enc_cmp_imm5(imm, reg2):
    return _f2(0x13, imm, reg2)                 # reg2 - imm5


def enc_jmp_lp():
    return _f1(0x03, LP, R0)                    # jmp [lp]


def enc_addi(imm16, reg1, reg2):
    """Format VI: addi imm16, reg1, reg2  -- a flageket beallitja."""
    return struct.pack('<HH', (reg2 << 11) | (0x30 << 5) | reg1, imm16 & 0xFFFF)


def enc_ld_bu(disp, reg1, reg2):
    """Format V-slot: a disp bit0-ja az opcode also bitjeben ul."""
    d = disp & 0xFFFF
    opc = 0x3C | (d & 1)
    return struct.pack('<HH', (reg2 << 11) | (opc << 5) | reg1, (d & 0xFFFE) | 1)


def enc_ld_hu(disp, reg1, reg2):
    return struct.pack('<HH', (reg2 << 11) | (0x3F << 5) | reg1, (disp & 0xFFFE) | 1)


def enc_setf(cond, reg2):
    """Format IX: setf cond, reg2  -- reg2 = feltetel ? 1 : 0."""
    return struct.pack('<HH', (reg2 << 11) | (0x3F << 5) | (cond & 0x1F), 0x0000)


def enc_branch(cond, va, target):
    """Format III: feltételes ag, disp9."""
    disp = target - va
    if disp % 2 or not -256 <= disp <= 254:
        raise ValueError('disp9 hataron kivul: %d' % disp)
    v = (disp >> 1) & 0xFF
    return struct.pack('<H', (((v >> 3) & 0x1F) << 11) | 0x580 | ((v & 7) << 4) | cond)


def enc_jarl(va, target, reg2=LP):
    disp = target - va
    if disp % 2 or not -(1 << 21) <= disp < (1 << 21):
        raise ValueError('disp22 hataron kivul: %d' % disp)
    d = disp & 0x3FFFFF
    return struct.pack('<HH', (reg2 << 11) | (0x3C << 5) | ((d >> 16) & 0x3F), d & 0xFFFE)


# ============================================================== a rutinok ====
#  Mindharom rutin azonos alaku, 28 bajt:
#    +00  ld.bu MODE, r1            4
#    +04  cmp   9, r1               2
#    +06  bnz   M                   2
#    +08  ld.hu Dx, r1              4
#    +0C  addi  -T, r1, r1          4
#    +10  setf  <cond>, r1          4
#    +14  jmp   [lp]                2
#    +16  M: ld.bu ORIG, r1         4
#    +1A  jmp   [lp]                2
ROUTINE_SIZE = 0x1C


def build_one(at, name, gp_src, thresh, cond, gp_orig):
    """Egy rutin bajtjai + a vart disassembly."""
    manual = at + 0x16
    seq = [
        (enc_ld_bu(GP_MODE, GP, R1),            'ld.bu    %d[gp], r1' % GP_MODE),
        (enc_cmp_imm5(AUTO_MODE, R1),           'cmp      %d, r1' % AUTO_MODE),
        (enc_branch(COND_NZ, at + 0x06, manual), 'bnz      0x%05X' % manual),
        (enc_ld_hu(gp_src, GP, R1),             'ld.hu    %d[gp], r1' % gp_src),
        (enc_addi(-thresh, R1, R1),             'addi     %d, r1, r1' % -thresh),
        (enc_setf(cond, R1),                    'setf     %s, r1' % V.COND[cond]),
        (enc_jmp_lp(),                          'jmp      [lp]'),
        (enc_ld_bu(gp_orig, GP, R1),            'ld.bu    %d[gp], r1' % gp_orig),
        (enc_jmp_lp(),                          'jmp      [lp]'),
    ]
    blob, expect, va = b'', [], at
    for raw, txt in seq:
        expect.append((va, txt))
        blob += raw
        va += len(raw)
    assert len(blob) == ROUTINE_SIZE, '%s: %d bajt' % (name, len(blob))
    return blob, expect


# (hook cim, eredeti 4 bajt, rutin neve, forras, kuszob, feltetel, eredeti bajt)
HOOKS = [
    (0x31420, 'a40f9f82', 'LAB',  GP_D1, T_LAB,  COND_LT, GP_LAB),
    (0x31440, '840fa982', 'FEJ',  GP_D1, T_FEJ,  COND_GE, GP_FEJ),
    (0x31460, 'a40fa982', 'SZEL', GP_D2, T_SZEL, COND_GE, GP_SZEL),
]
ROUTINE_BASE = 0x77E00


def layout():
    """[(hook, orig, nev, rutin_cime, forras, kuszob, cond, eredeti_bajt), ...]"""
    out, at = [], ROUTINE_BASE
    for hook, orig, name, src, th, cond, gp_orig in HOOKS:
        out.append((hook, bytes.fromhex(orig), name, at, src, th, cond, gp_orig))
        at += ROUTINE_SIZE
    return out


def leds(d1, d2, mode=AUTO_MODE):
    """A patch logikaja Pythonban -- az onteszthez (csak AUTO agra)."""
    assert mode == AUTO_MODE
    return (('F' if d1 >= T_FEJ else '-')
            + ('L' if d1 < T_LAB else '-')
            + ('S' if d2 >= T_SZEL else '-'))


# ============================================================== epites =======
def build(src_path, dst_path, verbose=True):
    d = bytearray(open(src_path, 'rb').read())
    plan = layout()

    def rd(a, n):
        return bytes(d[a - BASE:a - BASE + n])

    for hook, orig, name, *_ in plan:
        cur = rd(hook, 4)
        if cur != orig:
            raise SystemExit('HIBA: a 0x%05X (%s) nem az eredeti 4 bajtot tartalmazza.\n'
                             '  vart:   %s\n  talalt: %s\n'
                             '  (mar patchelt fajl, vagy mas firmware-verzio)\n'
                             '  MINDIG az ERINTETLEN F1ET-18D619-AM_00008000.bin-bol indulj!'
                             % (hook, name, orig.hex(), cur.hex()))

    total = len(plan) * ROUTINE_SIZE
    if ROUTINE_BASE + total > FREE_END:
        raise SystemExit('HIBA: a rutinok tullognanak a belso CRC hatokoren')
    if any(b != 0xFF for b in rd(ROUTINE_BASE, total)):
        raise SystemExit('HIBA: a 0x%05X terulet NEM ures' % ROUTINE_BASE)

    for hook, orig, name, at, src, th, cond, gp_orig in plan:
        blob, _ = build_one(at, name, src, th, cond, gp_orig)
        d[at - BASE:at - BASE + len(blob)] = blob
        j = enc_jarl(hook, at)
        d[hook - BASE:hook - BASE + 4] = j

    open(dst_path, 'wb').write(bytes(d))

    if verbose:
        print('patch kiirva: %s' % dst_path)
        for hook, orig, name, at, *_ in plan:
            print('  0x%05X  %-4s hook -> 0x%05X   (%s -> %s)'
                  % (hook, name, at, orig.hex(), enc_jarl(hook, at).hex()))
        print('  0x%05X  %d bajt rutin, %d bajt szabad flash marad'
              % (ROUTINE_BASE, total, 0x77F00 - ROUTINE_BASE - total))
        print()
        print('KOVETKEZO LEPES (kotelezo, kulonben U3000-41):')
        print('  python tools/fwcrc.py resign %s' % dst_path)
    return dst_path


# ============================================================== ellenorzes ===
def _dis(d, va, count):
    out, off = [], va - BASE
    for _ in range(count):
        i = V.decode(d, off, BASE + off)
        txt = str(i).split('  ', 1)[-1].strip().split(';')[0].strip()
        out.append((BASE + off, bytes(d[off:off + i.size]), txt))
        off += i.size
    return out


def verify(path):
    d = open(path, 'rb').read()
    plan = layout()
    ok = True

    print('=== 1. A harom beakasztas -- a csere UTANI utasitas valtozatlan? ===')
    for hook, orig, name, at, *_ in plan:
        got = _dis(d, hook, 2)
        want = 'jarl     0x%05X, lp' % at
        bad = got[0][2] != want
        print('  %05X  %-4s %-10s %-26s%s'
              % (hook, name, got[0][1].hex(), got[0][2],
                 '   <<< ELTERES, vart: %s' % want if bad else ''))
        print('         %-4s %-10s %-26s' % ('', got[1][1].hex(), got[1][2]))
        if bad or not got[1][2].startswith('st.b     r1, -3188'):
            ok = False

    print()
    print('=== 2. A harom rutin -- VISSZADISASSEMBLALVA ===')
    for hook, orig, name, at, src, th, cond, gp_orig in plan:
        print('  --- %s (0x%05X) ---' % (name, at))
        _, expect = build_one(at, name, src, th, cond, gp_orig)
        got = _dis(d, at, len(expect))
        for (va, raw, txt), (eva, etxt) in zip(got, expect):
            bad = (va != eva or txt != etxt)
            print('  %05X  %-10s %-26s%s'
                  % (va, raw.hex(), txt, '   <<< ELTERES, vart: %s' % etxt if bad else ''))
            if bad:
                ok = False

    print()
    print('=== 3. Elagazasok ===')
    for hook, orig, name, at, *_ in plan:
        for va, raw, txt in _dis(d, at, 9):
            if txt.startswith(('bnz', 'bl ', 'jr ')):
                t = int(txt.split('0x')[1], 16)
                inside = at <= t < at + ROUTINE_SIZE
                print('  %-4s 0x%05X -> 0x%05X   %s'
                      % (name, va, t, 'a rutinon belul' if inside else '!! KIVUL'))
                if not inside:
                    ok = False

    print()
    print('=== 4. Logikai onteszt: a MERT manualis tabla (50.5) ===')
    print('    (a patch manualis modban az EREDETI bajtot adja vissza --')
    print('     ez a teszt azt mutatja, hogy a kuszobok akkor is helyesek volnanak)')
    for name, d1, d2, want in (
            ('FEJ',            59, 0,   'F--'),
            ('FEJ+LAB',        33, 0,   'FL-'),
            ('LAB',            21, 40,  '-L-'),
            ('LAB+SZELVEDO',    9, 55,  '-LS'),
            ('FEJ+SZELVEDO',  100, 65,  'F-S'),
            ('MIND3',          45, 75,  'FLS')):
        g = leds(d1, d2)
        if g != want:
            ok = False
        print('  %s %-14s d1=%3d d2=%3d  ->  %s   (vart %s)'
              % ('OK ' if g == want else '!! ', name, d1, d2, g, want))

    print()
    print('=== 5. Az AUTO mert tartomanya (50.6) -- EZ AZ, AMI VALTOZNI FOG ===')
    for label, d1, d2 in (('AUTO LO  (max hutes)', 59, 0),
                          ('AUTO meleg 21-22 C',   59, 0),
                          ('AUTO hideg 21-22 C',   55, 32),
                          ('AUTO kozep',           33, 32),
                          ('AUTO HI  (max futes)', 17, 40)):
        print('  %-22s d1=%3d d2=%3d  ->  %s' % (label, d1, d2, leds(d1, d2)))

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
