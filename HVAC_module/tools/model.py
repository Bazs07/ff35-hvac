"""A F1ET-18D619-AM DEATC szabalyozo Python-modellje.

A HVAC_ELEMZES.md 24-29. szakaszaban dokumentalt egyenletek egy az egyben,
a VALODI kalibracios tablakbol taplalva (tools/calmap.py).

Cel:
  1. a megertes ellenorzese  -- egy CAN-log visszajatszasaval;
  2. kalibracio-valtoztatas kiprobalasa FLASHELES ELOTT (model-in-the-loop);
  3. a tervezett kodpatch-ek offline validalasa.

Hasznalat:
    python tools/model.py selftest              # tablazatos vegigsopres
    python tools/model.py point --oat 5 --set 22 --sun 0
    python tools/model.py blowermap             # az AUTO fuvogorbe kiirasa
    python tools/model.py doors                 # a mod -> ajtopozicio tabla
    python tools/model.py compare C346 C346NA   # ket valtozat osszevetese

Egysegek:
    OAT, homersekletek : 0,1 fok C  (a firmware belso egysege)
    alapjel (dial)     : 30..60  =  15,0 .. 30,0 fok C  (0,5 fok / lepes)
    fuvo               : kitoltes %
    ajtopozicio        : 0..100 %
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calmap import Cal, interp, clip, pct, s16, sb   # noqa: E402

CLIP = 4080          # a modell belso vagasi hatara (0x3F3C8 stb.)

# --- mode enum (18. szakasz) -------------------------------------------------
MODE_NAMES = {0: 'ki', 1: 'fej', 2: 'lab', 3: 'MAX defrost', 4: 'fej+lab',
              5: 'lab+szel', 6: 'fej+szel', 7: 'mind3', 8: 'szelvedo',
              9: 'AUTO', 10: 'mode10'}
PANEL_MODES = {1, 4, 6, 7}
FLOOR_MODES = {2, 4, 5, 7}
DEFR_MODES = {3, 5, 6, 7, 8}


def direction_bits(mode):
    """gp-30695 iranybitek a mode-bol (FUN_4CC42, 0x4CD58..0x4CDAA)."""
    return dict(panel=mode in PANEL_MODES,
                floor=mode in FLOOR_MODES,
                defrost=mode in DEFR_MODES,
                auto=(mode == 9))


def bittag(mode):
    b = direction_bits(mode)
    return ''.join(t if b[k] else '-'
                   for k, t in (('panel', 'F'), ('floor', 'L'), ('defrost', 'S')))


class Deatc:
    def __init__(self, variant='C346', lhd=True):
        self.c = Cal(variant)
        self.variant = variant
        self.lhd = lhd

    # ---------------------------------------------------------------- alapjel
    def setpoint(self, dial, offset=0):
        """Tarcsaertek (30..60) -> belso homerseklet-skala.

        FUN_4AD32 / FUN_4ACA6 a tarcsat KETSZEREZVE adja a 0xD01C gorbenek
        (0x4AD28: shl 1). A cal.h[174] = 98 referencia ~22,0 fok C-nak felel meg.
        """
        return self.c.fg(0xD01C, dial * 2) + offset

    # ------------------------------------------------- kozponti klimaszamitas
    def climate(self, oat, dial_a, dial_b, sun_a=0, sun_b=0,
                incar=None, trans_a=0, trans_b=0):
        """FUN_3F2CE (25-26. szakasz). Visszaad egy dict-et az ot kimenettel.

        oat     : kulso homerseklet 0,1 fok C
        dial_*  : tarcsaertek 30..60
        sun_*   : napterheles (0..250)
        incar   : becsult belso homerseklet a belso skalan; None = tokeletes
                  szabalyozas (hiba = 0)
        trans_* : alapjel-valtozasi tranziens (gp-29028 / gp-29026)
        """
        c = self.c
        t_a, t_b = self.setpoint(dial_a), self.setpoint(dial_b)
        lo = dial_a < 30 or dial_b < 30          # MAX LO
        hi = dial_a > 60 or dial_b > 60          # MAX HI

        f108 = c.f(1146, oat)      # alapszint
        f104 = c.f(1114, oat)      # napterheles-suly
        f106 = c.f(1132, oat)      # alapjel-erosites
        ref = c.h(174)             # 98

        def base(tset, sun):
            sun_t = clip((sun * f104 * 655) >> 12, -CLIP, CLIP)
            set_t = clip(f106 * (tset - ref), -CLIP, CLIP)
            return s16((f108 << 2) - sun_t + set_t + (c.b(579) << 4))

        base_a = base(t_a, sun_a)
        base_b = base(t_b, sun_b)
        diff = s16((base_a - base_b) << 3)

        # --- szabalyozasi hiba (26.3) ---
        r22 = s16((t_a + t_b) << 1)
        if incar is None:
            incar = r22 << 4                     # hiba = 0
        err = s16((r22 << 4) - incar)
        egain = c.f(1266, oat)

        def limit(e, trans):
            if abs(trans) > c.b(581) * 4 and abs(e) > (egain << 6):
                return (egain << 6) * (1 if e > 0 else -1)
            return e

        e_a = limit(err, trans_a)
        e_b = limit(err, trans_b)
        e_avg = (e_a + e_b) >> 1

        # --- tranziens keverek (25.4) ---
        w = c.b(580)
        t_mix = s16(((trans_a * w) >> 4) + ((trans_b * (16 - w)) >> 4))

        def split(p):
            """ket oldal keverese p szazalekkal (25.3)"""
            q = p if self.lhd else 100 - p
            return s16((base_b << 2) - ((pct(q) * diff) >> 7))

        def finish(val):
            v = val >> 2
            if lo or v <= 0:
                return 0
            if hi or v >= 255:
                return 255
            return v

        out = {}

        # gp-28667: a cel-kifuvasi homerseklet (a fuvonak es a mod-ajtoknak)
        sp56 = split(c.b(573))
        sp58 = s16(t_mix * c.sbv(571))
        g112 = c.f(1200, e_avg >> 6)
        r26 = clip((e_avg * g112) >> 6, -CLIP, CLIP)
        out['gp28667'] = finish(s16((sp56 >> 4) + (sp58 >> 2) + (r26 >> 2)))

        # gp-28666: kiszamolodik, de senki nem olvassa (31.2)
        shape = c.fg(0xCFA8, e_avg >> 6)
        r28 = clip(((e_avg * shape) >> 2) >> 4, -CLIP, CLIP)
        out['gp28666'] = finish(s16((sp56 >> 4) + (sp58 >> 2) + (r28 >> 2)))

        # gp-28665: a mod-ajtok fele
        sp68 = s16(t_mix * c.sbv(575))
        g116 = c.f(1222, e_avg >> 6)
        sp42 = clip((e_avg * g116) >> 6, -CLIP, CLIP)
        out['gp28665'] = finish(
            s16((split(c.b(576)) >> 4) + (sp68 >> 2) + (sp42 >> 2)))

        # gp-28663 / gp-28664: a ket keveroajto
        sp82 = clip(diff >> 7, -c.b(584), c.b(584))
        cross = pct(c.b(577) if self.lhd else c.b(574)) * sp82
        for key, bs, ts, tr, es in (('gp28663', base_a, t_a, trans_a, e_a),
                                    ('gp28664', base_b, t_b, trans_b, e_b)):
            g1156 = c.f(1156, es >> 6)
            sp28 = clip((g1156 * es) >> 6, -CLIP, CLIP)
            sp80 = s16(tr * c.b(578))
            v = s16(((bs << 2) - cross) >> 4)
            v = s16(v + (sp80 >> 2))
            v = s16(v + (sp28 >> 2))
            v = s16(v + (((ts - (r22 >> 2)) * c.sbv(569)) >> 2))
            out[key] = finish(v)

        out['_base_a'] = base_a
        out['_base_b'] = base_b
        out['_err'] = err
        out['_tset_a'] = t_a
        return out

    # ------------------------------------------------------------------ fuvo
    def blower(self, target_discharge, oat, sun=0, sun_valid=True,
               mode=9, blower_mode=1, level=0, hi=False, lo=False,
               warmup=False, af1a=True):
        """FUN_3A380 (27. szakasz). Visszaad: (auto_igeny, vegso_kitoltes)."""
        c = self.c
        floor_ = c.f(848, oat)                       # 20
        sun_b = c.f(888, sun)                        # napterheles-lokes
        temp_b = c.fb(2060, target_discharge)        # A FO KARAKTERISZTIKA
        sp15 = max(sun_b, temp_b) if sun_valid else temp_b
        auto = min(100, max(sp15, floor_))
        if hi or lo:
            auto = c.b(537)                          # 89

        if blower_mode == 0:
            cmd = 0
        elif blower_mode == 2:
            cmd = c.fb(2123, level)
            if mode == 1:
                cmd = min(cmd, c.b(531))
        else:
            sp7 = (c.f(924, oat << 6) * auto) >> 8 if af1a else c.b(38)
            cmd = min(auto, sp7)

        v = cmd if mode in (3, 10) else min(89, cmd)

        # a vegso vagasok (0x3B8A2 .. 0x3BA96)
        if mode == 3 and blower_mode == 1:
            v = max(v, c.b(513))
        elif mode == 8 and blower_mode == 1:
            v = max(v, c.b(514))
        elif warmup:
            v = min(v, c.f(874, oat))                # 35
        v = min(v, c.b(518))                         # 89
        v = max(v, c.b(519))                         # 20
        return auto, v

    # ------------------------------------------------------------- mod-ajtok
    def mode_doors(self, mode, hi=False, lo=False, auto_d2=None):
        """FUN_444E6 (20. szakasz). Visszaad: (ajto1, ajto2) 0..100."""
        c = self.c
        if mode == 9:
            d1 = c.h(358) >> 1                       # 58 -- ALLANDO
            d2 = 0 if auto_d2 is None else auto_d2
            if lo:
                d1, d2 = c.b(673), c.b(672)
            if hi:
                d1, d2 = c.b(671), c.b(670)
        else:
            d1 = c.fb(2320, mode)
            d2 = c.fb(2299, mode)
        d1 = clip(d1, c.b(669), c.b(666))
        d2 = clip(d2, c.b(663), c.b(662))
        return d1, d2

    def mode_from_doors(self, d1, d2):
        """A tervezett patch inverze (20.4): a legkozelebbi mode a tablabol."""
        c = self.c
        best, bd = None, 10 ** 9
        for m in (1, 2, 3, 4, 5, 6, 7, 8):
            dd = abs(d1 - c.fb(2320, m)) + abs(d2 - c.fb(2299, m))
            if dd < bd:
                best, bd = m, dd
        return best, bd



# ============================================================ PATCH-TERVEK ===
# Az AUTO adaptiv legelosztas javasolt gorbeje (0x44C44 patch).
# Bemenet: gp-28665 (a mod-ajtok fele meno kozponti ertek, 0..255)
# Kimenet: ajto1 pozicio.  A toresspontok a firmware SAJAT manualis tablajanak
# (cal+2320) ertekei: fej=21, fej+lab=33, lab=60.
PATCH_AUTO_DIST = [(0, 21), (80, 21), (110, 33), (160, 60), (255, 60)]

# A LED-szarmaztatas kuszobei (20.4 helyett).  A manualis tabla szomszedos
# ertekeinek felezopontjai:  (21+33)/2 = 27,  (33+60)/2 = 46.
# A szelvedo-bit kuszobe 48: a mode 1 (fej) ajto2 = 40 meg NEM szelvedo,
# a legalacsonyabb szelvedos mode (6) ajto2 = 55 mar igen.
LED_PANEL_MAX = 27
LED_FLOOR_MIN = 46
LED_DEFROST_MIN = 48


def patch_auto_door1(demand):
    """A javasolt patch: allando 58 helyett gorbe a fuvesi igenybol."""
    return interp(PATCH_AUTO_DIST, demand)


def patch_leds(d1, d2):
    """Iranybitek az ajtopoziciokbol, kuszobokkel (a nearest-neighbour helyett)."""
    return dict(panel=d1 <= LED_FLOOR_MIN,
                floor=d1 >= LED_PANEL_MAX,
                defrost=d2 >= LED_DEFROST_MIN)


def cmd_patch(a):
    m = Deatc(a.variant)
    d1_now = m.c.h(358) >> 1
    print('AUTO adaptiv legelosztas -- a javasolt patch hatasa (%s)' % a.variant)
    print()
    print('%7s %7s %9s %8s %8s   %-14s %s'
          % ('OAT C', 'set C', 'gp28665', 'ajto1 MA', 'ajto1 UJ', 'LED MA', 'LED UJ'))
    for t, d in ((35, 44), (30, 44), (25, 44), (20, 44), (15, 44),
                 (10, 44), (5, 44), (0, 44), (-5, 44), (-10, 44), (-20, 44),
                 (25, 36), (25, 52), (-5, 36), (-5, 52)):
        oat = t * 10
        r = m.climate(oat, d, d)
        dem = r['gp28665']
        d1_new = patch_auto_door1(dem)
        d2 = 5                       # AUTO ajto2 -- a firmware szamolja
        old = patch_leds(d1_now, d2)
        new = patch_leds(d1_new, d2)
        fmt = lambda x: ''.join(t2 if x[k] else '-' for k, t2 in
                                (('panel', 'F'), ('floor', 'L'), ('defrost', 'S')))
        print('%7d %7.1f %9d %8d %8d   %-14s %s'
              % (t, d / 2.0, dem, d1_now, d1_new, fmt(old) + ' (allando)', fmt(new)))
    print()
    print('MA: az ajto1 mindig %d -> a LED mindig ugyanaz -> ezert nincs kijelzes.' % d1_now)
    print('UJ: az ajto1 koveti az igenyt -> fej (hutes) ... fej+lab ... lab (futes).')

# ============================================================== parancssor ===
def cmd_blowermap(a):
    m = Deatc(a.variant)
    print('AUTO fuvogorbe (cal+2060) -- bemenet: gp-28667 cel-kifuvasi homerseklet')
    print('  %-6s %-11s' % ('cel', 'kitoltes %'))
    for x in range(0, 256, 8):
        v = m.c.fb(2060, x)
        print('  %-6d %3d  %s' % (x, v, '#' * (v // 2)))


def cmd_doors(a):
    m = Deatc(a.variant)
    print('mode -> ajtopozicio  (%s)   iranybitek: F=fej L=lab S=szelvedo'
          % a.variant)
    print('  %-3s %-12s %6s %6s   %s' % ('m', 'jelentes', 'ajto1', 'ajto2', 'bitek'))
    for mode in range(0, 11):
        if mode == 9:
            d1, d2 = m.mode_doors(9)
            extra = '   <- AUTO: ajto1 ALLANDO, ajto2 szamitott'
        else:
            d1, d2 = m.c.fb(2320, mode), m.c.fb(2299, mode)
            extra = ''
        print('  %-3d %-12s %6d %6d   %s%s'
              % (mode, MODE_NAMES.get(mode, '?'), d1, d2, bittag(mode), extra))
    print()
    d1auto = m.mode_doors(9)[0]
    print('A tervezett LED-patch (20.4) szimulacioja: ajto1 = %d (AUTO allando)' % d1auto)
    for d2 in (0, 20, 40, 55, 70, 85, 100):
        mm, dd = m.mode_from_doors(d1auto, d2)
        print('   ajto2 = %3d  ->  mode %d (%-11s)  LED %s   tavolsag %d'
              % (d2, mm, MODE_NAMES[mm], bittag(mm), dd))


def cmd_point(a):
    m = Deatc(a.variant)
    oat = int(round(a.oat * 10))
    dial = int(round(a.set * 2))            # fok C -> tarcsaertek (0,5 fok/lepes)
    r = m.climate(oat, dial, dial, a.sun, a.sun)
    auto, duty = m.blower(r['gp28667'], oat, a.sun, mode=a.mode)
    d1, d2 = m.mode_doors(a.mode)
    print('valtozat %s   OAT %.1f C   alapjel %.1f C   nap %d'
          % (a.variant, a.oat, a.set, a.sun))
    print('  alapjel a belso skalan     : %d   (referencia cal.h[174] = %d)'
          % (r['_tset_a'], m.c.h(174)))
    print('  celertek A / B             : %d / %d' % (r['_base_a'], r['_base_b']))
    print('  keveroajto A / B           : %d / %d  (0..255)'
          % (r['gp28663'], r['gp28664']))
    print('  cel-kifuvasi ho (gp-28667) : %d' % r['gp28667'])
    print('  mod-ajtok fele  (gp-28665) : %d' % r['gp28665'])
    print('  AUTO fuvoigeny / kitoltes  : %d %% / %d %%' % (auto, duty))
    print('  mod %d (%s) ajtok : %d / %d'
          % (a.mode, MODE_NAMES.get(a.mode, '?'), d1, d2))


def cmd_selftest(a):
    m = Deatc(a.variant)
    print('=== %s: alapjel 22 C, nap 0, AUTO ===' % a.variant)
    print('%6s %8s %8s %10s %10s %9s'
          % ('OAT C', 'celA', 'keverA', 'celkifuv', 'fuvoigeny', 'kitoltes'))
    for t in range(-20, 41, 5):
        oat = t * 10
        r = m.climate(oat, 44, 44)
        auto, duty = m.blower(r['gp28667'], oat)
        print('%6d %8d %8d %10d %10d %9d'
              % (t, r['_base_a'], r['gp28663'], r['gp28667'], auto, duty))
    print()
    print('=== %s: OAT 25 C, alapjel vegigsopres ===' % a.variant)
    print('%6s %8s %8s %10s %9s'
          % ('set C', 'celA', 'keverA', 'celkifuv', 'kitoltes'))
    for d in range(30, 61, 3):
        r = m.climate(250, d, d)
        auto, duty = m.blower(r['gp28667'], 250)
        print('%6.1f %8d %8d %10d %9d'
              % (d / 2.0, r['_base_a'], r['gp28663'], r['gp28667'], duty))
    print()
    print('=== napterheles hatasa (OAT 25 C, alapjel 22 C) ===')
    print('%6s %8s %10s %9s' % ('nap', 'celA', 'celkifuv', 'kitoltes'))
    for s in (0, 50, 100, 150, 200, 250):
        r = m.climate(250, 44, 44, s, s)
        auto, duty = m.blower(r['gp28667'], 250, s)
        print('%6d %8d %10d %9d' % (s, r['_base_a'], r['gp28667'], duty))


def cmd_compare(a):
    """Ket valtozat osszevetese ugyanazon a menetrenden."""
    ma, mb = Deatc(a.left), Deatc(a.right)
    print('=== %s vs %s : dual-zone szetvalas (bal 18 C, jobb 26 C) ==='
          % (a.left, a.right))
    print('%6s %14s %14s' % ('OAT C', a.left, a.right))
    for t in (-10, 0, 10, 20, 30):
        oat = t * 10
        ra = ma.climate(oat, 36, 52)
        rb = mb.climate(oat, 36, 52)
        print('%6d   %4d / %-4d    %4d / %-4d'
              % (t, ra['gp28663'], ra['gp28664'], rb['gp28663'], rb['gp28664']))
    print()
    print('(a ket szam a ket keveroajto 0..255; minel nagyobb a kulonbseg,')
    print(' annal fuggetlenebb a ket zona)')


def main():
    p = argparse.ArgumentParser(description='F1ET-18D619-AM DEATC modell')
    p.add_argument('--variant', default='C346')
    sub = p.add_subparsers(dest='cmd')
    sub.add_parser('selftest').set_defaults(fn=cmd_selftest)
    sub.add_parser('blowermap').set_defaults(fn=cmd_blowermap)
    sub.add_parser('doors').set_defaults(fn=cmd_doors)
    q = sub.add_parser('point')
    q.set_defaults(fn=cmd_point)
    q.add_argument('--oat', type=float, default=20.0)
    q.add_argument('--set', type=float, default=22.0)
    q.add_argument('--sun', type=int, default=0)
    q.add_argument('--mode', type=int, default=9)
    r = sub.add_parser('compare')
    r.set_defaults(fn=cmd_compare)
    r.add_argument('left', nargs='?', default='C346')
    r.add_argument('right', nargs='?', default='C346NA')
    sub.add_parser('patch').set_defaults(fn=cmd_patch)
    a = p.parse_args()
    if not getattr(a, 'fn', None):
        p.print_help()
        return
    a.fn(a)


if __name__ == '__main__':
    main()
