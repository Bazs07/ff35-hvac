#!/usr/bin/env python3
"""Elo adatpanel es IO-control a F1ET-18D619-AM DEATC modulhoz.

A DID-ek es a skalazasok a firmware kezelo-fuggvenyeibol vannak visszafejtve
(HVAC_ELEMZES.md 40. szakasz).  A szerszam TRANSZPORT-FUGGETLEN: kiirja,
mit kell kikuldeni, es dekodolja, ami visszajott.  Igy barmilyen eszkozzel
hasznalhato, ami tud nyers UDS-kerest kuldeni (UCDS, FORScan, sajat
J2534-kliens, python-can + isotp, ...).

  python tools/livedata.py list                 # mit tudunk lekerdezni
  python tools/livedata.py requests             # a kikuldendo 0x22 keresek
  python tools/livedata.py iocontrol            # a 0x2F parancsok (vezerles!)
  python tools/livedata.py plan                 # a 40.5 meresi terv
  python tools/livedata.py decode 9924 A0       # egy valasz dekodolasa
  python tools/livedata.py panel valaszok.txt   # teljes panel egy valaszfajlbol
  python tools/livedata.py demo                 # offline proba a modellbol

A valaszfajl formatuma (soronkent, a '#' utan megjegyzes):
    9924 A0
    9B01 31
    9805 62

Diagnosztikai cimzes:  keres 0x733, valasz 0x73B  (a firmware RX-szurojebol,
35.3 szakasz).

SESSION (42. szakasz, [B]):
  0x22 olvasas  -> DEFAULT sessionben is megy
  0x2F vezerles -> CSAK EXTENDED sessionben:  eloszor kuldj  10 03
  SecurityAccess (0x27) NEM kell.
  Tartsd eletben:  3E 80  kb. 2 masodpercenkent, kulonben visszaall default-ra.

FIGYELEM -- a 36-37. szakasz DID-listaja EL VOLT CSUSZVA egy bejegyzessel
(minden DID a szomszedja kezelojehez parosodott).  Ez a fajl a javitott,
0xB2CC-tol olvasott tablat hasznalja.  Ha regi jegyzetben `0x9927 = OAT`
vagy `0x981A = fuvo` szerepel, az a `0x9924` illetve a `0x9805`.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REQ_ID = 0x733
RSP_ID = 0x73B


# --- dekodolok (mind a kezelo-fuggvenybol, [B]) ------------------------------
def pos(b):
    """Lepteto tenyleges pozicioja: a kezelo (lepes+10)/20-at ir ki -> %."""
    return '%d %%' % b


def duty(b):
    """0x9805: byte = kitoltes_% * 255 / 100   (gp-23235, PWM 18)."""
    return '%.0f %%' % (b * 100.0 / 255.0)


def oat(b):
    """0x9924: byte = T[0,1C]/2 + 80  ->  C = (b - 80) * 0,2."""
    return '%.1f C' % ((b - 80) * 0.2)


def t04(b):
    """0x9927 / 0x9B04..07: byte = T[0,1C]/4 + 40  ->  C = (b - 40) * 0,4."""
    return '%.1f C' % ((b - 40) * 0.4)


def raw(b):
    return str(b)


# did -> (nev, dekodolo, megbizhatosag, forras)
CATALOG = {
    0x9805: ('fuvo kitoltes', duty, 'B', 'gp-23235 -> PWM 18'),
    0x9834: ('mod-ajto #2 (szelvedo)', pos, 'B', 'lepteto 4'),
    0x9924: ('kulso homerseklet (OAT)', oat, 'B', 'FUN_45264 = gp-29040'),
    0x9927: ('sajat kulso szenzor (nyers)', t04, 'B', 'FUN_42B9A = gp-29068'),
    0x9B00: ('recirkulacios ajto', pos, 'B', 'lepteto 0'),
    0x9B01: ('mod-ajto #1 (panel/padlo)', pos, 'B', 'lepteto 1'),
    0x9B02: ('keveroajto A', pos, 'B', 'lepteto 2'),
    0x9B03: ('keveroajto B', pos, 'B', 'lepteto 3'),
    0x9B04: ('kifuvasi ho: padlo/szel A', t04, 'B', 'gp-29094, ADC 11'),
    0x9B05: ('kifuvasi ho: panel A', t04, 'B', 'gp-29096, ADC 10'),
    0x9B06: ('kifuvasi ho: padlo/szel B', t04, 'B', 'gp-29090, ADC 13'),
    0x9B07: ('kifuvasi ho: panel B', t04, 'B', 'gp-29092, ADC 12'),
    0x9961: ('napterheles-szarmazek A', raw, 'E', 'gp-28613'),
    0x9962: ('napterheles-szarmazek B', raw, 'E', 'gp-28612'),
    0x9969: ('FUN_26C64 szarmazek', raw, 'E', 'gp-27076 (tapfesz.?)'),
    0x9850: ('u16 allapot', raw, 'E', 'gp-23294'),
    0x981A: ('4 bajtos blokk', None, 'E', 'FUN_4BCA6'),
    0x4056: ('konfiguracio A', raw, 'E', '0xBCB0 tabla + FUN_53B12'),
    0x4057: ('konfiguracio B', raw, 'E', '0xBCB0 tabla + FUN_53B18'),
    0xFD0C: ('5 bajtos blokk', None, 'E', '0xBCF6'),
    0xF18C: ('cikkszam', None, 'B', 'F1ET-18D619-AM'),
    0xF188: ('szoftver-verzio', None, 'B', ''),
    0xFD0A: ('As-Built konfiguracios blokk', None, 'B',
             '88 bajt; az elso 3 = a 44.4 konfig-rekord'),
}

# A panelen ebben a sorrendben jelenjen meg:
PANEL = [0x9924, 0x9927, 0x9805,
         0x9B02, 0x9B03, 0x9B01, 0x9834, 0x9B00,
         0x9B04, 0x9B06, 0x9B05, 0x9B07]

# A 0x2F-fel vezerelheto DID-ek (a firmware 0xB281 engedelyezett listajabol).
# did -> (nev, a 03 vezerlo bajtja, a 00 hatasa, megbizhatosag, kezelo)
IOCTL = {
    0x9805: ('fuvo kitoltes', '1 bajt 0..255,  % = b*100/255',
             'FUVO KI (0 %)', 'B', 0x25F38),
    0x9834: ('mod-ajto #2 (szelvedo)', '1 bajt = POZICIO %, 0..100',
             'befagyaszt a mostani helyere', 'B', 0x25FFA),
    0x9B00: ('recirkulacios ajto', '1 bajt = POZICIO %, 0..100',
             'befagyaszt a mostani helyere', 'B', 0x2613A),
    0x9B01: ('mod-ajto #1 (panel/padlo)', '1 bajt = POZICIO %, 0..100',
             'befagyaszt a mostani helyere', 'B', 0x261F8),
    0x9B02: ('keveroajto A', '1 bajt = POZICIO %, 0..100',
             'befagyaszt a mostani helyere', 'B', 0x262B6),
    0x9B03: ('keveroajto B', '1 bajt = POZICIO %, 0..100',
             'befagyaszt a mostani helyere', 'B', 0x26374),
    0x4056: ('konfiguracio A', '1 bajt, ?', '?', 'E', 0x25D3A),
    0x4057: ('konfiguracio B', '1 bajt, ?', '?', 'E', 0x25E38),
    0x9969: ('FUN_26C64 szarmazek', '1 bajt, ?', '?', 'E', 0x26088),
    0xFD04: ('15 bajtos RAM-blokk (gp-30840)', '15 bajt (PONTOSAN)',
             'a flash alapertelmezes (0xBD05)', 'B', 0x26428),
    0xFD06: ('LEPTETO-KARBANTARTAS', '2 bajt: motor index, parameter',
             'MIND AZ OT lepteto ujra-referalasa', 'B', 0x264D8),
    0xFD0C: ('5 bajtos blokk', '?', '?', 'E', 0x257E4),
}

# A modul altal hasznalt negativ valaszkodok (FUN_1C408)
NRC = {0x13: 'incorrectMessageLengthOrInvalidFormat (rossz adathossz)',
       0x31: 'requestOutOfRange (a vezerlo bajt tartomanyon kivul, pl. > 100)'}


def cmd_list():
    print('Lekerdezheto DID-ek (0x22)   B = bizonyitott skalazas, E = becsult\n')
    print('%-8s %-4s %-30s %s' % ('DID', 'megb', 'jelentes', 'forras'))
    for did in sorted(CATALOG):
        n, dec, conf, note = CATALOG[did]
        print('0x%04X   %-4s %-30s %s' % (did, conf, n, note))


def frame22(did):
    return '22 %02X %02X' % (did >> 8, did & 0xFF)


def frame2f(did, sub, state=None):
    f = '2F %02X %02X %02X' % (did >> 8, did & 0xFF, sub)
    if state is not None:
        f += ' %02X' % state
    return f


def cmd_requests():
    print('Diagnosztikai cimzes: keres 0x%03X -> valasz 0x%03X\n' % (REQ_ID, RSP_ID))
    print('%-30s %-12s %s' % ('jel', 'UDS', 'ISO-TP single frame'))
    for did in PANEL:
        f = frame22(did)
        print('%-30s %-12s 03 %s 00 00 00 00' % (CATALOG[did][0], f, f))
    print()
    print('A valasz elso bajtjai: 62 <DID_hi> <DID_lo> <adat...>')


def cmd_iocontrol():
    print('0x2F  InputOutputControlByIdentifier')
    print('Feherlista: 0xB281 (24 x 3 bajt).  Kezelok: 0xB004 (24 x 20 bajt),')
    print('indexrol indexre egyezik -- ezert a lenti hozzarendeles [B].')
    print('A vezerlo bajt jelentese a kezelo-fuggvenyekbol olvasva (40.4).')
    print()
    print('%-8s %-4s %-30s %-32s %s'
          % ('DID', 'megb', 'jelentes', '03 = shortTermAdjustment', 'kezelo'))
    for did in sorted(IOCTL):
        n, unit, ret, conf, h = IOCTL[did]
        print('0x%04X   %-4s %-30s %-32s 0x%05X' % (did, conf, n, unit, h))
    print()
    print('%-8s %s' % ('DID', '00 = returnControlToECU hatasa'))
    for did in sorted(IOCTL):
        print('0x%04X   %s' % (did, IOCTL[did][2]))
    print()
    print('Negativ valaszkodok (FUN_1C408):')
    for k in sorted(NRC):
        print('  0x%02X  %s' % (k, NRC[k]))
    print()
    print('Peldak (ISO-TP single frame, keres 0x%03X):' % REQ_ID)
    for did, val, what in [(0x9B01, 21, 'mod-ajto #1 -> 21 %  (a "fej" allas)'),
                           (0x9B01, 60, 'mod-ajto #1 -> 60 %  (a "lab" allas)'),
                           (0x9834, 100, 'mod-ajto #2 -> 100 % (szelvedo)'),
                           (0x9B02, 0, 'keveroajto A -> 0 %  (teljes hutes)'),
                           (0x9B02, 100, 'keveroajto A -> 100 % (teljes futes)'),
                           (0x9805, 128, 'fuvo -> kb. 50 % (0..255 skala!)')]:
        print('  05 %-18s %s' % (frame2f(did, 0x03, val), what))
    print()
    print('Zaras (a fuvot MINDENKEPP add vissza -- a 00 KIKAPCSOLJA):')
    for did in (0x9B00, 0x9B01, 0x9B02, 0x9B03, 0x9834, 0x9805):
        print('  04 %-18s %s' % (frame2f(did, 0x00), CATALOG.get(did, ('?',))[0]))
    print()
    print('ELOFELTETEL -- EXTENDED SESSION (42. szakasz):')
    print('  02 10 03            -> 10 03 DiagnosticSessionControl (extended)')
    print('  02 3E 80            -> TesterPresent, kb. 2 mp-enkent, vegig')
    print('  Default sessionben a 0x2F NRC 0x7E-t ad (subFunctionNotSupported')
    print('  InActiveSession).  SecurityAccess (0x27) NEM kell.')
    print()
    print('FIGYELMEZTETESEK')
    print('  - ISMETELD A PARANCSOT kb. 100 ms-onkent!  A kimeneti fokozat')
    print('    (0x49C1A, utemezett) normal uzemallapotban minden ciklusban')
    print('    ujraszamolja az ajtokat es felulirhatja a diag-parancsot (40.6).')
    print('    Olvasd vissza 0x22-vel, hogy megfogott-e.')
    print('  - allo jarmuben, gyujtas be, motor le.')
    print('  - a 0xFD06/03 KEZI lepteto-vezerlest kapcsol be (gp-27058) --')
    print('    invazivabb, mint a pozicio-parancs, a mereshez NEM kell.')
    print('  - a 0xFD04/03 egy 15 bajtos RAM-blokkot ir felul.  NE probald ki.')


def _doors(mode):
    """A mod -> ajtopozicio tabla a VALODI kalibraciobol (model.py)."""
    from model import Deatc
    m = Deatc('C346')
    if mode == 9:
        return m.mode_doors(9)
    return m.c.fb(2320, mode), m.c.fb(2299, mode)


def cmd_asbuilt(argv):
    """A 0xFD0A As-Built blokk elso 3 bajtjanak dekodolasa (44.4 / 45.2)."""
    print('=== 0xFD0A -- As-Built konfiguracios blokk ===')
    print()
    print('OLVASAS (default sessionben is megy, kockazatmentes):')
    print('   03 22 FD 0A 00 00 00 00    -> valasz: 62 FD 0A <88 bajt>')
    print()
    print('Az elso HAROM bajt a 44.4 konfiguracios rekord:')
    print('   [0] gp-32550   a rekord elso bajtja')
    print('   [1] gp-32549   az A/C allapotgep uzemmodja (0x39762): 1 vagy 2')
    print('   [2] gp-32548   BITMEZO:')
    print('        bit0 (FUN_29EDE) -> A gep (FUN_54728, gp-22932)')
    print('        bit1 (FUN_29EEE) -> B gep (FUN_54946, gp-22931)')
    print('        KET KULON, azonos felepitesu rutin -- kulon idozitokkel')
    print('        es kulon szamlaloval (44.3)')
    print()
    if argv:
        data = parse_hex(' '.join(argv))
        if len(data) >= 3 and data[0] == 0x62:
            data = data[3:]
        if len(data) >= 3:
            print('A MEGADOTT ADAT:')
            print('   [0] = 0x%02X (%d)' % (data[0], data[0]))
            print('   [1] = 0x%02X -> A/C uzemmod %d' % (data[1], data[1]))
            b = data[2]
            print('   [2] = 0x%02X -> bit0=%d bit1=%d -> 44.3 rutinok: %s'
                  % (b, b & 1, (b >> 1) & 1,
                     {0:'egyik sem',1:'csak A',2:'csak B',3:'A es B'}[b & 3]))
            print()
        else:
            print('(legalabb 3 bajt kell)')
            print()
    print('IRAS -- FIGYELEM, ez NEM default sessionben megy:')
    print('   a 0x2E kezelo-tabla (0x0AF00) szerint a 0xFD0A flags = 0x12:')
    print('     session-maszk 2 = programmingSession  ->  10 02')
    print('     security-maszk 2 = SecurityAccess SZINT 2 kell  ->  0x27')
    print('   Az alapszint 1, tehat 2 & 1 = 0  ->  NRC 0x33 SecurityAccessDenied.')
    print()
    print('   A seed/key algoritmus NINCS visszafejtve -- de ez a szokasos')
    print('   Ford As-Built programozas, amit a FORScan / UCDS mar tud.')
    print('   Vagyis a funkcio bekapcsolasahoz NEM kell flashelni, es NEM kell')
    print('   nekunk a security-t megfejteni: eleg egy As-Built szerkeszto.')
    print()
    print('   ELOBB OLVASD KI es IRD LE a jelenlegi 88 bajtot.')


def cmd_plan():
    print('=== 40.5  MERESI TERV -- az ajto-geometria lezarasa ===')
    print()
    print('Allo jarmu, gyujtas be, UDS-kepes eszkoz, keres 0x733.')
    print()
    print('A) PASSZIV -- a panel gombjaival, csak 0x22 olvasas')
    print('   Minden allasban olvasd ki:  9B01 (mod-ajto #1) es 9834 (mod-ajto #2)')
    print('   A varhato ertekek a VALODI kalibraciobol (cal+2320 / cal+2299):')
    print()
    print('   %-19s %-14s %s' % ('gomb (mode)', '9B01 varhato', '9834 varhato'))
    for mode, name in [(1, 'fej'), (4, 'fej + lab'), (2, 'lab'),
                       (5, 'lab + szelvedo'), (6, 'fej + szelvedo'),
                       (7, 'mind3'), (8, 'szelvedo'), (3, 'MAX defrost')]:
        print('   %-19s %-14d %d' % ('%s (%d)' % (name, mode),
                                     _doors(mode)[0], _doors(mode)[1]))
    d1, d2 = _doors(9)
    print('   %-19s %-14s %s' % ('AUTO (9)', '%d (ALLANDO!)' % d1,
                                 '%d most, valtozik' % d2))
    print()
    print('   Ez igazolja a cal+2320 / cal+2299 tablat es az "AUTO-ban beegetett')
    print('   58"-at -- vagyis pontosan azt, amire a 33. szakasz patch-e epul.')
    print()
    print('B) AKTIV -- 0x2F shortTermAdjustment, ez donti el a GEOMETRIAT')
    print('   0. EXTENDED SESSION (kotelezo, 42. szakasz):')
    print('      02 10 03 00 00 00 00 00      -> valasz: 50 03 ...')
    print('      utana 3E 80 kb. 2 mp-enkent, kulonben visszaall default-ra')
    print('      (default sessionben a 0x2F NRC 0x7E-t ad!)')
    print('   FONTOS: minden parancsot ISMETELJ kb. 100 ms-onkent, es olvasd')
    print('   vissza 0x22-vel -- a szabalyozo kulonben felulirhatja (40.6).')
    print('   Fuvo kozepre:            05 %s' % frame2f(0x9805, 3, 128))
    print('   1. mod-ajto #1 -> 21 %%:  05 %s   -> honnan fuj?' % frame2f(0x9B01, 3, 21))
    print('   2. mod-ajto #1 -> 60 %%:  05 %s   -> honnan fuj?' % frame2f(0x9B01, 3, 60))
    print('      ha 21 %-nal ARC es 60 %-nal LAB  ->  a lepteto 1 a panel/padlo ajto')
    print('   3. mod-ajto #2 -> 100 %%: 05 %s   -> honnan fuj?' % frame2f(0x9834, 3, 100))
    print('      ha SZELVEDO  ->  a lepteto 4 a szelvedo-ajto')
    print('   4. recirk -> 100 %%:      05 %s   -> hallhato-e a beszivo valtas?'
          % frame2f(0x9B00, 3, 100))
    print('      ha igen  ->  a lepteto 0 a recirkulacios ajto')
    print('   Zaras:                   04 %s  ... (mindegyikre)'
          % frame2f(0x9B01, 0))
    print()
    print('C) A 39.3 NTC-PAROSITAS ELLENORZESE  -- 30 masodperc, csak 0x22')
    print('   Kapcsold a keveroajtot melegre (9B02/9B03 -> 100 %), a fuvot kozepre,')
    print('   majd valtogasd a mod-ajtot panel <-> padlo kozott, es olvasd:')
    print('     9B04, 9B06  (a modell szerint PADLO/SZELVEDO par)')
    print('     9B05, 9B07  (a modell szerint PANEL par)')
    print('   A 39.3 joslata: a ket par KULON mozog -- amelyik kifuvason megy a')
    print('   levego, az a par koveti a keveroajtot, a masik ott ragad.')
    print('   Ha mind a negy egyutt mozog, a 39.3 parositas TEVES.')


def decode_one(did, data):
    if did not in CATALOG:
        return '0x%04X ismeretlen: %s' % (did, bytes(data).hex())
    name, dec, conf, note = CATALOG[did]
    if dec is None:
        txt = bytes(data).hex()
    elif len(data) >= 1:
        txt = dec(data[0])
    else:
        txt = '(ures)'
    return '%-30s %-12s [%s]' % (name, txt, conf)


def parse_hex(s):
    s = s.replace('0x', '').replace(',', ' ')
    return bytes(int(x, 16) for x in s.split())


def cmd_decode(argv):
    did = int(argv[0], 16)
    data = parse_hex(' '.join(argv[1:]))
    if len(data) >= 3 and data[0] == 0x62 and (data[1] << 8 | data[2]) == did:
        data = data[3:]
    print(decode_one(did, data))


def cmd_panel(path):
    vals = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.split('#')[0].strip()
            if not line:
                continue
            p = line.split()
            vals[int(p[0], 16)] = parse_hex(' '.join(p[1:]))
    render(vals)


def render(vals):
    print('+' + '-' * 56 + '+')
    print('| %-54s |' % 'DEATC elo adatok')
    print('+' + '-' * 56 + '+')
    for did in PANEL:
        if did in vals:
            print('| %-54s |' % decode_one(did, vals[did]))
    extra = [d for d in vals if d not in PANEL]
    if extra:
        print('+' + '-' * 56 + '+')
        for did in extra:
            print('| %-54s |' % decode_one(did, vals[did]))
    print('+' + '-' * 56 + '+')


def cmd_demo():
    """Offline proba: a modellbol szamolt ertekeket kodoljuk vissza DID-alakba."""
    from model import Deatc
    m = Deatc('C346')
    oat_c = 5.0
    r = m.climate(int(oat_c * 10), 44, 44)
    _, d = m.blower(r['gp28667'], int(oat_c * 10))
    vals = {
        0x9924: bytes([int(oat_c * 10 / 2 + 80)]),
        0x9927: bytes([int(oat_c * 10 / 4 + 40)]),
        0x9805: bytes([int(d * 255 / 100)]),
        0x9B02: bytes([min(100, r['gp28663'] * 100 // 255)]),
        0x9B03: bytes([min(100, r['gp28664'] * 100 // 255)]),
        0x9B01: bytes([58]),          # a mai allando AUTO-ertek
        0x9834: bytes([20]),
        0x9B00: bytes([49]),
    }
    print('(szintetikus adatok a modellbol, OAT = %.1f C, alapjel 22 C)\n' % oat_c)
    render(vals)
    print()
    print('Valos meresnel ugyanez a panel jelenik meg, csak a modul valaszaibol.')


def main():
    a = sys.argv[1:]
    cmd = a[0] if a else 'list'
    if cmd == 'list':
        cmd_list()
    elif cmd == 'requests':
        cmd_requests()
    elif cmd == 'iocontrol':
        cmd_iocontrol()
    elif cmd == 'plan':
        cmd_plan()
    elif cmd == 'asbuilt':
        cmd_asbuilt(a[1:])
    elif cmd == 'decode':
        cmd_decode(a[1:])
    elif cmd == 'panel':
        cmd_panel(a[1])
    elif cmd == 'demo':
        cmd_demo()
    else:
        print(__doc__)


if __name__ == '__main__':
    main()
