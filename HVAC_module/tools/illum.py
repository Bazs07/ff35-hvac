#!/usr/bin/env python3
"""A HVAC megvilagitas-kalibracio (`0xFD0A` As-Built rekord) dekodere/szerkesztoje.

Reszletes leiras: HVAC_ELEMZES.md 53. szakasz.

A REKORD SZERKEZETE  (kodbol levezetve, meressel igazolva)
    A modul a 0xFE000080 NVM-blokkbol 86 bajtot tolt a gp-23218-tol
    (`0x53B8A`), majd ellenorzi (`0x53BAA`):

        43 x u16 (big endian):
          [0..41]  21 par (min, max)  --  minden parra KOTELEZO: min < max
          [42]     XOR(hw[0..41]) ^ 0x0042        (ellenorzo osszeg)

    Az UDS `22 FD 0A` olvasas ebbol a 84 adatbajtot adja vissza, plusz 4
    fixen nullazott bajtot (`0x25682`)  ->  osszesen 88 bajt.
    **Az ellenorzo osszeg NINCS benne az As-Built stringben.**

    Ha az ellenorzes megbukik, a modul a `0x53F6E`-nel a gyari, flashbeli
    alapertekekre esik vissza -- vagyis a hibas rekord BIZTONSAGOS.

A HASZNALATA
    FUN_540C8(csatorna, szint):
        raw = min + (max - min) * (szint - 1) / 1022        ; szint 1..1023
    FUN_5410A:
        tipus = tabla_0x11FAE[csatorna]                     ; 0 = tiltva
        pct   = (tipus == 1) ? gp-30801 : gp-30802          ; globalis fenyero
        ertek = max(1, raw * pct / 100)                     ; 16 bites PWM
        FUN_2B902(csatorna, ertek)

HASZNALAT
    python tools/illum.py decode <88-bajtos-hex>
    python tools/illum.py set    <hex> <csatorna> --max 0xC000 [--min 0x0600]
    python tools/illum.py scale  <hex> <csatorna> 1.25
"""
import sys

N_PAIRS = 21
N_CH = 23
RECORD_LEN = 88
DATA_LEN = 84
CHECK_XOR = 0x0042

# csatorna -> par index.  A 0x53E0A..0x53F66 mutatotabla-feltoltesbol.
# 0..17 egy-az-egyben; a 18/19 LETILTVA (NULL mutato); 20/21/22 -> 18/19/20.
CH2PAIR = {i: i for i in range(18)}
CH2PAIR.update({20: 18, 21: 19, 22: 20})
DISABLED = (18, 19)

# tipustabla 0x11FAE:  1 -> gp-30801,  2 -> gp-30802,  0 -> nem hajtott
CH_TYPE = [2, 2, 2, 1, 1, 1, 1, 2, 2, 2, 2, 1, 1, 1, 1,
           1, 1, 1, 0, 0, 1, 1, 1]

# amit a 9. szakasz lancabol biztosan tudunk (0x509F8..0x50A70)
CH_NAME = {
    15: 'SZELVEDO iranyLED   (gp-31886, struktura +2)',
    16: 'FEJ iranyLED        (gp-31887, struktura +1)',
    17: 'LAB iranyLED        (gp-31888, struktura +0)',
}
FULL_SCALE = 0xFFFF


def parse(hexstr):
    b = bytes.fromhex(hexstr.strip().replace(' ', '').replace('\n', ''))
    if len(b) != RECORD_LEN:
        raise SystemExit('HIBA: %d bajt, de %d kellene' % (len(b), RECORD_LEN))
    if b[DATA_LEN:] != b'\x00' * 4:
        print('FIGYELEM: az utolso 4 bajt nem nulla (a modul fixen nullazza)')
    hw = [int.from_bytes(b[i:i + 2], 'big') for i in range(0, DATA_LEN, 2)]
    return b, hw


def emit(hw):
    out = b''.join(v.to_bytes(2, 'big') for v in hw) + b'\x00' * 4
    return out.hex().upper()


def checksum(hw):
    x = 0
    for v in hw:
        x ^= v
    return x ^ CHECK_XOR


def validate(hw, verbose=True):
    ok = True
    for p in range(N_PAIRS):
        lo, hi = hw[2 * p], hw[2 * p + 1]
        if lo >= hi:
            ok = False
            if verbose:
                print('  !! %d. par: min 0x%04X >= max 0x%04X -- a modul '
                      'ELUTASITJA es alapertekre esik vissza' % (p, lo, hi))
    return ok


def decode(hexstr):
    _, hw = parse(hexstr)
    print('=== A 0xFD0A megvilagitas-kalibracio (%d bajt) ===\n' % RECORD_LEN)
    print('csat par tip  min      max      max %    bajtok   szerep')
    for ch in range(N_CH):
        if ch in DISABLED:
            print('%3d  --   %d   --       --       --      --       LETILTVA (NULL mutato)'
                  % (ch, CH_TYPE[ch]))
            continue
        p = CH2PAIR[ch]
        lo, hi = hw[2 * p], hw[2 * p + 1]
        off = 4 * p
        print('%3d  %2d   %d   0x%04X   0x%04X   %5.1f%%  %2d..%-2d  %s'
              % (ch, p, CH_TYPE[ch], lo, hi, 100.0 * hi / FULL_SCALE,
                 off, off + 3, CH_NAME.get(ch, '')))
    print()
    print('min < max mind a %d parra: %s' % (N_PAIRS, 'IGEN' if validate(hw) else 'NEM'))
    print('ellenorzo osszeg (a 43. halfword az NVM-ben, az As-Built stringben NINCS benne):'
          '  0x%04X' % checksum(hw))
    print()
    print('A "max %" a teljes 16 bites PWM-skalahoz kepest, a globalis')
    print('fenyero-szazalek (gp-30801/30802) ELOTT.')


def _set(hexstr, ch, new_min=None, new_max=None):
    _, hw = parse(hexstr)
    if ch in DISABLED or ch not in CH2PAIR:
        raise SystemExit('HIBA: a %d. csatorna nincs hasznalatban' % ch)
    p = CH2PAIR[ch]
    lo, hi = hw[2 * p], hw[2 * p + 1]
    nlo = lo if new_min is None else new_min
    nhi = hi if new_max is None else new_max
    for v, name in ((nlo, 'min'), (nhi, 'max')):
        if not 0 <= v <= 0xFFFF:
            raise SystemExit('HIBA: a %s (%d) nem fer bele 16 bitbe' % (name, v))
    if nlo >= nhi:
        raise SystemExit('HIBA: min (0x%04X) >= max (0x%04X) -- a modul elutasitana '
                         'es alapertekre esne vissza' % (nlo, nhi))
    hw[2 * p], hw[2 * p + 1] = nlo, nhi
    print('%d. csatorna (%d. par, %d..%d bajt): 0x%04X/0x%04X  ->  0x%04X/0x%04X'
          % (ch, p, 4 * p, 4 * p + 3, lo, hi, nlo, nhi))
    if CH_NAME.get(ch):
        print('  %s' % CH_NAME[ch])
    print('  max fenyero: %.1f%%  ->  %.1f%%'
          % (100.0 * hi / FULL_SCALE, 100.0 * nhi / FULL_SCALE))
    validate(hw)
    print()
    print('uj As-Built string (88 bajt):')
    print(emit(hw))
    return emit(hw)


def _num(s):
    return int(s, 16) if s.lower().startswith('0x') else int(s)


def main():
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == 'decode':
        decode(a[1])
    elif len(a) >= 4 and a[0] == 'set':
        ch = int(a[2])
        kw = {}
        i = 3
        while i < len(a) - 1:
            if a[i] == '--min':
                kw['new_min'] = _num(a[i + 1])
            elif a[i] == '--max':
                kw['new_max'] = _num(a[i + 1])
            else:
                raise SystemExit('ismeretlen kapcsolo: %s' % a[i])
            i += 2
        if not kw:
            raise SystemExit('adj meg --min es/vagy --max erteket')
        _set(a[1], ch, **kw)
    elif len(a) >= 4 and a[0] == 'scale':
        ch, f = int(a[2]), float(a[3])
        _, hw = parse(a[1])
        p = CH2PAIR[ch]
        _set(a[1], ch, new_max=min(0xFFFF, int(round(hw[2 * p + 1] * f))))
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
