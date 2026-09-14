#!/usr/bin/env python3
"""UDS-reteg kiolvaso a F1ET-18D619-AM DEATC firmware-bol.

  python tools/uds.py services        # a tamogatott UDS-szolgaltatasok (42. szakasz)
  python tools/uds.py dids            # a 0xB2CC DID-tabla (48 bejegyzes)
  python tools/uds.py io              # a 0x2F IO-control engedelyezett lista
  python tools/uds.py dtcs            # a 0xBC34 DTC-tabla (30 bejegyzes)
  python tools/uds.py sensors         # ADC-erzekelo -> DTC parositas
  python tools/uds.py all

TABLASZERKEZETEK (visszafejtve, HVAC_ELEMZES.md 36. szakasz)

  DID-tabla @0xB2CC, 48 x 16 bajt   (JAVITVA -- 40. szakasz):
      +0  u16  DID  (novekvo sorrendben, FUN_1CFA8 binarisan keres 0..47)
      +2  u16  adathossz bajtban
      +4  u32  hozzaferesi/session flagek   (0x2F vagy 0x3F ...)
      +8  u32  flagek 2                     (mindenutt 0x0F)
      +12 u32  a kezelo fuggveny cime

    A KORABBI (36. szakasz) olvasas 0xB2D0-tol, +12-nel vette a DID-et --
    ezzel MINDEN DID a SZOMSZEDJA kezelojehez parosodott.  Innen jott a
    "0x9927 = OAT" es a "0x981A = fuvo" tevedes (helyesen 0x9924 es 0x9805).

  0x2F (InputOutputControlByIdentifier) engedelyezett lista @0xB281:
      24 x 3 bajt:  DID_hi, DID_lo, alfunkcio      (DID BIG ENDIAN = drot-sorrend)
      alfunkcio 00 = returnControlToECU, 03 = shortTermAdjustment
    A leiro @0x0ADD4:  `0F 33 2F 04 04 18 21 00`
      -> szolgaltatas 0x2F, kulcshossz 3 (a 0x33 also nibble-je),
         24 rekord (0x18), a keszlet kezdete a 0xB260 pool +0x21 offsetjen.

  DTC-tabla @0xBC34, 30 x 4 bajt:
      +0  u8   FTB (failure type byte)
      +1  u16  DTC-kod, LITTLE ENDIAN, ISO 14229 2 bajtos alak
      +3  u8   0
    Az index 1-tol szamozodik; a statusz-bajtok a gp-27368 tombben allnak
    (FUN_247FA: ervenyes ha 1 <= index <= 30).
"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

BASE = 0x8000
BIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                   'F1ET-18D619-AM_00008000.bin')

DID_TABLE = 0xB2CC
DID_COUNT = 48
IO_TABLE = 0xB281
IO_COUNT = 24
IO_HANDLERS = 0xB004
DTC_TABLE = 0xBC34
DTC_COUNT = 30

# A het ADC-erzekelo leirotablaja (24.2); a +16/+17 bajt a DTC-index.
SENSOR_TABLE = 0xE1F0
SENSOR_COUNT = 7

# Amit a DTC-kodokrol tudni lehet.  A Ford-fele szoveg [E] -- a kod maga [B].
DTC_HINT = {
    'B1A61': 'kulso homerseklet-erzekelo',
    'B1A63': 'napszenzor (egyik oldal)',
    'B1A64': 'napszenzor (masik oldal)',
    'B1081': 'Left Temperature Damper Motor -- keveroajto A / BAL (lepteto 2) [Ford]',
    'B1082': 'Right Temperature Damper Motor -- keveroajto B / JOBB (lepteto 3) [Ford]',
    'B1083': 'Recirculation Damper Motor -- recirkulacios ajto (lepteto 0) [Ford]',
    'B1086': 'Air Distribution Damper Motor -- mod-ajto #1, register/footwell (lepteto 1) [Ford]',
    'B125B': 'Air Distribution Damper "B" Motor -- mod-ajto #2 (lepteto 4) [Ford]; '
             'a szelvedo-ajto azonositas a mi kodelemzesunk, 46.2',
    'B10B3': 'homerseklet-erzekelo 1',
    'B10B4': 'homerseklet-erzekelo 2',
    'B10B5': 'homerseklet-erzekelo 3',
    'B10B6': 'homerseklet-erzekelo 4',
    'U3000': 'vezerloegyseg belso hiba (FTB 41 = checksum) -- ezt allitja a belso flash-CRC',
    'U3003': 'tapfeszultseg (FTB 16 = alacsony, 17 = magas)',
    'U0140': 'kommunikacio a BCM-mel',
    'U0155': 'kommunikacio a muszerfallal',
    'U0166': 'kommunikacio -- HVAC/segedmodul',
    'U0422': 'ervenytelen adat a BCM-tol',
}

SUBFUNC = {0x00: 'returnControlToECU', 0x03: 'shortTermAdjustment'}

# --- session / security (42. szakasz) ---------------------------------------
# A DID-tabla +4 es az IO-tabla +12 also bajtja:
#     bit 5..3 = engedelyezett SESSION maszk,  bit 2..0 = SECURITY maszk
SESSION_BIT = {1: 'default (10 01)', 2: 'programming (10 02)',
               4: 'EXTENDED (10 03)'}
SERVICE_TABLE = 0xADB4 - 0x18      # 0xAD9C
SERVICE_MAP = 0xAD55               # SID -> leiro-index
SERVICES = [(0x10, 'DiagnosticSessionControl'), (0x11, 'ECUReset'),
            (0x14, 'ClearDiagnosticInformation'), (0x19, 'ReadDTCInformation'),
            (0x22, 'ReadDataByIdentifier'), (0x27, 'SecurityAccess'),
            (0x2E, 'WriteDataByIdentifier'),
            (0x2F, 'InputOutputControlByIdentifier'),
            (0x31, 'RoutineControl'), (0x34, 'RequestDownload'),
            (0x36, 'TransferData'), (0x37, 'RequestTransferExit'),
            (0x3E, 'TesterPresent'), (0x85, 'ControlDTCSetting')]
POOL = 0xB260                      # a kulcs-lista bajt-pool


def sessions(flag):
    """A flags-bajtbol olvashato session-lista."""
    m = (flag >> 3) & 7
    names = [v for k, v in sorted(SESSION_BIT.items()) if m & k]
    return '+'.join(n.split(' ')[0] for n in names) or 'egyik sem'


def seclevels(flag):
    return flag & 7

# Ismert szabvanyos DID-ek (a tobbi Ford-specifikus).
DID_HINT = {
    0x9805: 'fuvo kitoltes (gp-23235, % = b*100/255)',
    0x9834: 'mod-ajto #2 / szelvedo -- lepteto 4 (%)',
    0x9924: 'kulso homerseklet OAT (gp-29040, C = (b-80)*0,2)',
    0x9927: 'sajat kulso szenzor, nyers (gp-29068, C = (b-40)*0,4)',
    0x9B00: 'recirkulacios ajto -- lepteto 0 (%)',
    0x9B01: 'mod-ajto #1 / panel-padlo -- lepteto 1 (%)',
    0x9B02: 'keveroajto A -- lepteto 2 (%)',
    0x9B03: 'keveroajto B -- lepteto 3 (%)',
    0x9B04: 'kifuvasi ho: padlo/szelvedo A (ADC11, C = (b-40)*0,4)',
    0x9B05: 'kifuvasi ho: panel A (ADC10, C = (b-40)*0,4)',
    0x9B06: 'kifuvasi ho: padlo/szelvedo B (ADC13, C = (b-40)*0,4)',
    0x9B07: 'kifuvasi ho: panel B (ADC12, C = (b-40)*0,4)',
    0xF106: 'aktiv diagnosztikai session adatok',
    0xF110: 'ECU cikkszam (core assembly)',
    0xF111: 'ECU cikkszam (hardver)',
    0xF113: 'ECU cikkszam (szoftver)',
    0xF188: 'ECU szoftver-verzio',
    0xF18C: 'ECU sorozatszam / cikkszam',
    0xF190: 'VIN',
    0xFD0A: 'konfiguracios blokk (As-Built)',
}


def load():
    return open(BIN, 'rb').read()


def dtc_name(code):
    return '%s%d%X%02X' % ('PCBU'[(code >> 14) & 3], (code >> 12) & 3,
                           (code >> 8) & 0xF, code & 0xFF)


def read_dids(d):
    out = []
    for i in range(DID_COUNT):
        a = DID_TABLE - BASE + 16 * i
        did, length = struct.unpack('<HH', d[a:a + 4])
        f1, f2, h = struct.unpack('<III', d[a + 4:a + 16])
        out.append(dict(idx=i, flags1=f1, flags2=f2, handler=h,
                        did=did, length=length))
    return out


def read_io(d):
    """A 0x2F engedelyezett (DID, alfunkcio) parok."""
    out = []
    for i in range(IO_COUNT):
        a = IO_TABLE - BASE + 3 * i
        out.append(dict(did=(d[a] << 8) | d[a + 1], sub=d[a + 2]))
    return out


def read_dtcs(d):
    out = []
    for i in range(DTC_COUNT):
        a = DTC_TABLE - BASE + 4 * i
        ftb = d[a]
        code = d[a + 1] | (d[a + 2] << 8)
        out.append(dict(idx=i + 1, ftb=ftb, code=code, name=dtc_name(code)))
    return out


def read_sensors(d):
    out = []
    for i in range(SENSOR_COUNT):
        a = SENSOR_TABLE - BASE + 20 * i
        e = d[a:a + 20]
        out.append(dict(idx=i, adc=e[0], curve=struct.unpack('<I', e[4:8])[0],
                        dtc1=e[16], dtc2=e[17]))
    return out


def cmd_services(d):
    print('=== Tamogatott UDS-szolgaltatasok ===')
    print('A 0x%05X SID->index tabla es a 0x%05X leirok alapjan (42. szakasz).'
          % (SERVICE_MAP, SERVICE_TABLE))
    print()
    print('%-6s %-32s %-6s %-8s %s'
          % ('SID', 'nev', 'kulcs', 'rekord', 'engedelyezett alfunkciok / kulcsok'))
    ent = []
    for i, (sid, name) in enumerate(SERVICES):
        a = SERVICE_TABLE - BASE + 8 * i
        r = d[a:a + 8]
        ent.append((sid, name, r[1] & 0xF, r[5], r[6] | (r[7] << 8)))
    for i, (sid, name, kw, idx, off) in enumerate(ent):
        nxt = ent[i + 1] if i + 1 < len(ent) else (0, '', 0, idx + 1, off)
        n = nxt[3] - idx
        keys = ''
        if kw and n:
            for k in range(n):
                a = POOL - BASE + off + kw * k
                keys += ' ' + ''.join('%02X' % x for x in d[a:a + kw])
            keys = keys.strip()
        elif n:
            keys = '(kulon tabla)'
        print('%-6s %-32s %-6s %-8d %s'
              % ('0x%02X' % sid, name, kw or '-', n, keys))


def cmd_dids(d):
    io = {}
    for e in read_io(d):
        io.setdefault(e['did'], []).append(e['sub'])
    print('=== UDS DID-tabla (0x%05X, %d bejegyzes) ===' % (DID_TABLE, DID_COUNT))
    print('%-4s %-7s %-6s %-9s %-6s %-18s %s'
          % ('#', 'DID', 'hossz', 'kezelo', '0x2F', 'session (0x22)', 'jelentes'))
    for e in read_dids(d):
        subs = io.get(e['did'])
        tag = '/'.join('%02X' % x for x in subs) if subs else ''
        print('%-4d 0x%04X  %-6d 0x%05X   %-6s %-18s %s'
              % (e['idx'], e['did'], e['length'], e['handler'], tag,
                 sessions(e['flags1'] & 0xFF),
                 DID_HINT.get(e['did'], '')))


def cmd_io(d):
    known = {e['did']: e for e in read_dids(d)}
    print('=== 0x2F InputOutputControlByIdentifier -- engedelyezett lista'
          ' (0x%05X, %d bejegyzes) ===' % (IO_TABLE, IO_COUNT))
    print('%-8s %-30s %-6s %s' % ('DID', 'jelentes', 'hossz', 'alfunkcio'))
    seen = {}
    for e in read_io(d):
        seen.setdefault(e['did'], []).append(e['sub'])
    for did in sorted(seen):
        r = known.get(did)
        ln = '%d' % r['length'] if r else 'n/a'
        subs = ', '.join('%02X %s' % (s, SUBFUNC.get(s, '?')) for s in seen[did])
        print('0x%04X   %-30s %-6s %s' % (did, DID_HINT.get(did, ''), ln, subs))
    print()
    print('n/a hossz = a DID a 0x22 olvaso tablaban NINCS benne -> csak irhato.')
    print()
    io_ses = {}
    for i in range(IO_COUNT):
        a = IO_HANDLERS - BASE + 20 * i
        io_ses.setdefault(read_io(d)[i]['did'], set()).add(d[a + 12] & 0xFF)
    print('SESSION-KOVETELMENY (a 0xB004 tabla +12 bajtja):')
    for did in sorted(io_ses):
        for f in sorted(io_ses[did]):
            print('  0x%04X  flags=0x%02X  ->  session: %-12s  security-maszk: %d'
                  % (did, f, sessions(f), seclevels(f)))
    print()
    print('  ==> A 0x2F-hez EXTENDED session kell:  10 03')
    print('      (a 0x22 olvasas default sessionben is megy)')
    print('      SecurityAccess NEM kell: a security-maszk 7, az alap szint 1.')
    print('      Tartsd eletben:  3E 80  (TesterPresent, ~2 masodpercenkent)')


def cmd_dtcs(d):
    print('=== DTC-tabla (0x%05X, %d bejegyzes) ===' % (DTC_TABLE, DTC_COUNT))
    print('%-4s %-10s %-5s %s' % ('idx', 'DTC', 'FTB', 'megjegyzes'))
    for e in read_dtcs(d):
        tag = '%s-%02X' % (e['name'], e['ftb'])
        print('%-4d %-10s %-5s %s'
              % (e['idx'], tag, '%02X' % e['ftb'], DTC_HINT.get(e['name'], '')))


def cmd_sensors(d):
    dtcs = {e['idx']: e for e in read_dtcs(d)}
    print('=== ADC-erzekelo -> DTC parositas ===')
    print('%-5s %-5s %-9s %-6s %-10s %s'
          % ('idx', 'ADC', 'gorbe', 'DTCix', 'DTC', 'jelentes'))
    for e in read_sensors(d):
        t = dtcs.get(e['dtc1'])
        print('%-5d %-5d 0x%05X  %-6d %-10s %s'
              % (e['idx'], e['adc'], e['curve'], e['dtc1'],
                 t['name'] if t else '?',
                 DTC_HINT.get(t['name'], '') if t else ''))


def main():
    d = load()
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    if cmd in ('services', 'all'):
        cmd_services(d)
        print()
    if cmd in ('dids', 'all'):
        cmd_dids(d)
        print()
    if cmd in ('io', 'all'):
        cmd_io(d)
        print()
    if cmd in ('dtcs', 'all'):
        cmd_dtcs(d)
        print()
    if cmd in ('sensors', 'all'):
        cmd_sensors(d)


if __name__ == '__main__':
    main()
