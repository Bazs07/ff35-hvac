#!/usr/bin/env python3
"""Kalibracio-modosito a F1ET-18D619-AM DEATC firmware-hez.

Recept-vezerelt, biztonsagi ellenorzesekkel es MODELL-ALAPU elozetes
kiertekelessel: minden receptet le lehet futtatni "szarazon", es a
tools/model.py megmutatja, mit valtoztat a viselkedesen -- flasheles elott.

HASZNALAT
    python tools/calpatch.py list
    python tools/calpatch.py show  dualzone
    python tools/calpatch.py show  dualzone --value 64
    python tools/calpatch.py apply dualzone <in.bin> <out.bin> [--value 48]
    python tools/calpatch.py diff  <patched.bin> <orig.bin>

A VALTOZAT-BLOKK
    A firmware hat jarmu-valtozat kalibraciojat tartalmazza; hogy melyik az
    aktiv, azt a modul konfiguracioja donti el (8. szakasz).  Europai,
    balkormanyos Focus eseten ez tipikusan C346 (vagy C346FAP).  Ha nem
    biztos, a --variant all mindegyiket modositja.

A PATCH UTAN KOTELEZO
    python tools/fwcrc.py resign <out.bin>
    python tools/vbf.py pack F1ET-18D619-AM.VBF <out.bin> uj.vbf
"""
import sys
import os
import argparse
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calmap import Cal, BASE                            # noqa: E402
from model import Deatc                                 # noqa: E402

EU_VARIANTS = ['C346', 'C346FAP']


# ============================================================== receptek =====
# Minden recept: nev -> dict(leiras, tetelek, ertekeles)
#   tetelek: lista (fajta, offset, vart_regi_ertek, uj_ertek_fn)
#   fajta: 'b' = u8, 'sb' = i8, 'h' = u16
RECIPES = {}


def recipe(name, **kw):
    def deco(fn):
        RECIPES[name] = dict(fn=fn, **kw)
        return fn
    return deco


@recipe('dualzone',
        title='Dual-zone szetvalasztas erositese',
        detail=(
            'A ket zona homerseklet-kulonbseget a cal[569] erositi:\n'
            '  keveroajto += (alapjel_oldal - alapjel_atlag) * cal[569] / 4\n'
            'Gyari ertek EU-ban 32, Eszak-Amerikaban 18.  Emeles = fuggetlenebb\n'
            'zonak (a jobb oldal kevesbe koveti a balt).\n'
            'BIZTONSAGI TULAJDONSAG: azonos alapjelnel a tag PONTOSAN NULLA,\n'
            'tehat ha mindket oldal ugyanarra van allitva, semmi nem valtozik.\n'
            'A kozos csatornakat (fuvo, legelosztas) sem erinti.'),
        default=48, lo=8, hi=100)
def _dualzone(value):
    return [('sb', 569, 32, value)]


@recipe('autoblower_quiet',
        title='AUTO fuvo csendesitese a kozepso tartomanyban',
        detail=(
            'A cal+2060 U-alaku AUTO fuvogorbe minimuma 30 %.  A "value" a\n'
            'gorbe kozepso harom pontjanak uj erteke (80/107/130-nal).\n'
            'FIGYELEM: tul alacsony ertek gyenge legcserehez es parasodashoz\n'
            'vezethet -- 24 ala ne menj.'),
        default=27, lo=22, hi=40)
def _autoblower(value):
    # a gorbe 5., 6., 7. pontjanak y-ja (x = 80, 107, 130)
    return [('curve_y', 2060, (80, 31), value),
            ('curve_y', 2060, (107, 30), value),
            ('curve_y', 2060, (130, 33), value + 3)]


@recipe('maxdefrost_quiet',
        title='MAX DEFROST fuvo-minimum csokkentese',
        detail=(
            'MAX defrost (mode 3) alatt a fuvo minimuma cal[513] = 64 %.\n'
            'FIGYELEM: ez BIZTONSAGI funkcio (szelvedo-parátlanitas).\n'
            'Csak ovatosan, es tudd, hogy lassabban tisztul a szelvedo.'),
        default=55, lo=40, hi=64)
def _maxdefrost(value):
    return [('b', 513, 64, value)]


@recipe('lowspeed_anchor',
        title='Alvo modell-tag: alacsony sebessegu horgony a sajat szenzorhoz',
        detail=(
            'A 39.4 utaster-modell 8. tagja (0x432E6) a C346-on KI VAN\n'
            'KAPCSOLVA (cal.h[318] = 0), de a C344GM valtozaton EL (262).\n'
            'Amit csinal: allo jarmuben (sebesseg <= 2 km/h) a becsult belso\n'
            'homersekletet a modul SAJAT kulso szenzora fele huzza:\n'
            '    X2 += cal.h[318] * (sajat_szenzor - T_levego) * 4   / ciklus\n'
            '\n'
            'MERT NEM AJANLOTT (39.4 / 41.2):\n'
            '  - a hatasa kicsi: 5 C-os szenzor-elteresnel kb. +0,5 C;\n'
            '  - a sajat szenzor allo jarmuben eppen a legkevesbe megbizhato\n'
            '    (motorterbol atmelegszik) -- a tag ilyenkor a ROSSZ ertek fele huz;\n'
            '  - menet kozben (sebesseg > 2) a tag automatikusan kikapcsol,\n'
            '    tehat epp akkor nem hat, amikor a szenzor jo lenne.\n'
            'Csak akkor van ertelme, ha meressel igazolod, hogy a becsult belso\n'
            'homerseklet allo jarmuben tul lassan koveti a valosagot.'),
        default=262, lo=0, hi=1024)
def _lowspeed(value):
    return [('h', 318, 0, value)]


# ============================================================== motor ========
class Editor:
    def __init__(self, path, variant):
        self.d = bytearray(open(path, 'rb').read())
        self.cal = Cal(variant, path=path)
        self.variant = variant
        self.base = self.cal.base
        self.changes = []

    def _a(self, off):
        return self.base + off - BASE

    def read(self, kind, off):
        a = self._a(off)
        if kind == 'b':
            return self.d[a]
        if kind == 'sb':
            v = self.d[a]
            return v - 256 if v & 0x80 else v
        if kind == 'h':
            return struct.unpack('<H', self.d[a:a + 2])[0]
        raise ValueError(kind)

    def write(self, kind, off, val, expect=None):
        old = self.read(kind, off)
        if expect is not None and old != expect:
            raise SystemExit(
                'HIBA (%s): cal[%d] jelenlegi erteke %d, de %d volt varhato.\n'
                '  Mar modositott fajl, vagy mas valtozat/firmware.'
                % (self.variant, off, old, expect))
        a = self._a(off)
        if kind in ('b', 'sb'):
            self.d[a] = val & 0xFF
        else:
            self.d[a:a + 2] = struct.pack('<H', val & 0xFFFF)
        self.changes.append((self.variant, 'cal[%d]' % off, old, val))

    def write_curve_y(self, off, xy, newy):
        """Egy bajtos gorbe (FUN_4B2E0) adott x-hez tartozo y-janak atirasa."""
        x, expect_y = xy
        a = self._a(off)
        n = self.d[a]
        for i in range(n):
            px, py = self.d[a + 1 + 2 * i], self.d[a + 2 + 2 * i]
            if px == x:
                if py != expect_y:
                    raise SystemExit('HIBA: cal+%d x=%d y=%d, de %d volt varhato'
                                     % (off, x, py, expect_y))
                self.d[a + 2 + 2 * i] = newy & 0xFF
                self.changes.append((self.variant, 'cal+%d @x=%d' % (off, x), py, newy))
                return
        raise SystemExit('HIBA: cal+%d gorbeben nincs x=%d toresspont' % (off, x))

    def apply(self, items):
        for kind, off, expect, val in items:
            if kind == 'curve_y':
                self.write_curve_y(off, expect, val)
            else:
                self.write(kind, off, val, expect)

    def save(self, path):
        open(path, 'wb').write(bytes(self.d))


# ============================================================== kiertekeles ==
def evaluate(name, value, variant, path=None):
    """Modell-alapu elotte/utana osszevetes -- flasheles nelkul."""
    import tempfile
    ed = Editor(path or Cal(variant).__dict__ and _default_bin(), variant)
    before = Deatc(variant)
    ed.apply(RECIPES[name]['fn'](value))
    tmp = os.path.join(tempfile.gettempdir(), 'calpatch_eval.bin')
    ed.save(tmp)
    after = Deatc.__new__(Deatc)
    after.c = Cal(variant, path=tmp)
    after.variant = variant
    after.lhd = True

    print('--- MODELL: elotte / utana (%s) ---' % variant)
    if name == 'dualzone':
        print('%22s %14s %14s' % ('helyzet', 'elotte A/B', 'utana A/B'))
        for lbl, da, db, oat in (('mindketto 22 C', 44, 44, 100),
                                 ('bal 20 / jobb 24', 40, 48, 100),
                                 ('bal 18 / jobb 26', 36, 52, 100),
                                 ('bal 18 / jobb 26 (hideg)', 36, 52, -50)):
            rb = before.climate(oat, da, db)
            ra = after.climate(oat, da, db)
            print('%22s   %4d /%-4d     %4d /%-4d   (kulonbseg %d -> %d)'
                  % (lbl, rb['gp28663'], rb['gp28664'], ra['gp28663'], ra['gp28664'],
                     abs(rb['gp28663'] - rb['gp28664']), abs(ra['gp28663'] - ra['gp28664'])))
        print()
        print('  A fuvo es a legelosztas (kozos csatorna) valtozatlan:')
        rb = before.climate(100, 36, 52)
        ra = after.climate(100, 36, 52)
        print('    cel-kifuvasi ho: %d -> %d   |  mod-ajtok fele: %d -> %d'
              % (rb['gp28667'], ra['gp28667'], rb['gp28665'], ra['gp28665']))
    elif name == 'lowspeed_anchor':
        from cabin import CabinModel
        print('%22s %12s %12s' % ('helyzet', 'elotte', 'utana'))
        for lbl, oat, own, speed in (
                ('allo, szenzor +5 C', 250, 300, 0),
                ('allo, szenzor -5 C', 250, 200, 0),
                ('allo, szenzor = OAT', 250, 250, 0),
                ('50 km/h, szenzor +5 C', 250, 300, 50)):
            out = []
            for k in (0, value):
                m = CabinModel(variant)
                m.k_lowspd = k
                m.reset(oat)
                for _ in range(int(240 * 60 * 1000 / m.period)):
                    m.step(oat=oat, t_duct_pf=oat, t_duct_pn=oat, flow_pf=0,
                           flow_pn=0, speed=speed, sun=0, doors=0, own_sens=own)
                out.append(m.t_air / 10.0)
            print('%22s %11.1fC %11.1fC   (%+.1f C)'
                  % (lbl, out[0], out[1], out[1] - out[0]))
        print()
        print('  (allandosult allapot 4 ora utan, fuvo ki, nap 0)')
    elif name in ('autoblower_quiet', 'maxdefrost_quiet'):
        print('%8s %12s %12s' % ('OAT C', 'fuvo elotte', 'fuvo utana'))
        for t in (30, 20, 10, 0, -10, -20):
            oat = t * 10
            rb = before.climate(oat, 44, 44)
            ra = after.climate(oat, 44, 44)
            _, db = before.blower(rb['gp28667'], oat)
            _, da_ = after.blower(ra['gp28667'], oat)
            print('%8d %12d %12d' % (t, db, da_))
        if name == 'maxdefrost_quiet':
            rb = before.climate(0, 44, 44)
            ra = after.climate(0, 44, 44)
            _, db = before.blower(rb['gp28667'], 0, mode=3)
            _, da_ = after.blower(ra['gp28667'], 0, mode=3)
            print('  MAX DEFROST (mode 3): %d %% -> %d %%' % (db, da_))
    return ed


def _default_bin():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..',
                        'F1ET-18D619-AM_00008000.bin')


# ============================================================== parancsok ====
def cmd_list(a):
    print('Elerheto receptek:\n')
    for name, r in RECIPES.items():
        print('  %-18s %s' % (name, r['title']))
        print('  %-18s alapertelmezett ertek: %d  (tartomany %d..%d)'
              % ('', r['default'], r['lo'], r['hi']))
        print()


def cmd_show(a):
    r = RECIPES[a.recipe]
    val = a.value if a.value is not None else r['default']
    _check_range(r, val)
    print('=== %s: %s ===' % (a.recipe, r['title']))
    print(r['detail'])
    print()
    variants = EU_VARIANTS if a.variant == 'eu' else (
        list(Cal('C346').blocks) if a.variant == 'all' else [a.variant])
    for v in variants:
        ed = evaluate(a.recipe, val, v, a.bin)
        print()
        print('  valtoztatasok (%s):' % v)
        for var, what, old, new in ed.changes:
            print('    %-16s %4d -> %4d' % (what, old, new))
        print()


def cmd_apply(a):
    r = RECIPES[a.recipe]
    val = a.value if a.value is not None else r['default']
    _check_range(r, val)
    variants = EU_VARIANTS if a.variant == 'eu' else (
        list(Cal('C346').blocks) if a.variant == 'all' else [a.variant])
    src = a.src
    for v in variants:
        ed = Editor(src, v)
        ed.apply(r['fn'](val))
        ed.save(a.dst)
        src = a.dst                       # a kovetkezo valtozat mar erre epul
        for var, what, old, new in ed.changes:
            print('  %-8s %-16s %4d -> %4d' % (var, what, old, new))
    print()
    print('kiirva: %s' % a.dst)
    print()
    print('KOVETKEZO LEPES (kotelezo, kulonben 22-es DTC):')
    print('  python tools/fwcrc.py resign %s' % a.dst)
    print('  python tools/vbf.py pack F1ET-18D619-AM.VBF %s uj.vbf' % a.dst)


def cmd_diff(a):
    x = open(a.patched, 'rb').read()
    y = open(a.orig, 'rb').read()
    runs, i = [], 0
    while i < min(len(x), len(y)):
        if x[i] != y[i]:
            j = i
            while j < len(x) and x[j] != y[j]:
                j += 1
            runs.append((BASE + i, j - i))
            i = j
        else:
            i += 1
    tot = sum(n for _, n in runs)
    print('eltero tartomanyok: %d db, osszesen %d bajt' % (len(runs), tot))
    for va, n in runs:
        print('  0x%05X  %3d bajt   %s -> %s'
              % (va, n, y[va - BASE:va - BASE + n].hex(), x[va - BASE:va - BASE + n].hex()))


def _check_range(r, val):
    if not r['lo'] <= val <= r['hi']:
        raise SystemExit('HIBA: az ertek (%d) kivul esik a %d..%d tartomanyon'
                         % (val, r['lo'], r['hi']))


def main():
    p = argparse.ArgumentParser(description='DEATC kalibracio-modosito')
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('list').set_defaults(fn=cmd_list)
    s = sub.add_parser('show')
    s.set_defaults(fn=cmd_show)
    s.add_argument('recipe', choices=list(RECIPES))
    s.add_argument('--value', type=int)
    s.add_argument('--variant', default='C346')
    s.add_argument('--bin', default=None)
    ap = sub.add_parser('apply')
    ap.set_defaults(fn=cmd_apply)
    ap.add_argument('recipe', choices=list(RECIPES))
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--value', type=int)
    ap.add_argument('--variant', default='C346')
    df = sub.add_parser('diff')
    df.set_defaults(fn=cmd_diff)
    df.add_argument('patched')
    df.add_argument('orig')
    a = p.parse_args()
    if not getattr(a, 'fn', None):
        p.print_help()
        return
    a.fn(a)


if __name__ == '__main__':
    main()
