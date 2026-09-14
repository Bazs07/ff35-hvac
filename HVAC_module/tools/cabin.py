#!/usr/bin/env python3
"""A DEATC ketcsomopontos utaster-homerseklet modellje (HVAC_ELEMZES.md 39. szakasz).

A firmware 0x42FA2 ciklikus feladatanak egy-az-egyben ujraszamolasa, a VALODI
kalibracios tablakbol taplalva (tools/calmap.py).

Hasznalat:
    python tools/cabin.py selftest                 # onellenorzo tesztek
    python tools/cabin.py coeffs [--variant C346]  # a kiolvasott egyutthatok
    python tools/cabin.py step --oat 5 --duct 40 --sun 0 --minutes 60
    python tools/cabin.py soak --oat 35 --sun 255  # allo auto felmelegedese
    python tools/cabin.py compare C346 C346NA

Egysegek (mint a firmware-ben):
    homerseklet   : 0,1 fok C
    X1 / X2       : Q22, azaz  T[0,1 C] * 2^22
    aramlas       : gp-29052/29054/29056 nyers egysege
    napszenzor    : 0..255
"""
import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from calmap import Cal, interp, clip   # noqa: E402

PERIOD = None          # cal.h[288], idozito-egysegben (feltehetoen ms)
Q = 22                 # az allapotvaltozok fixpontja


def sat16(v):
    return -32768 if v < -32768 else (32767 if v > 32767 else v)


class CabinModel:
    """A 0x42FA2 feladat allapota es egy lepese."""

    def __init__(self, variant='C346'):
        c = self.cal = Cal(variant)
        self.variant = variant
        # --- idozito-periodusok ---
        self.period = c.h(288)          # a modell lepeskoze
        self.period_out = c.h(300)      # a kimeneti szuro
        # --- egyutthatok (39.4) ---
        self.k_duct_pf = c.h(322)       # padlo+szelvedo befujas
        self.k_duct_pn = c.h(316)       # panel befujas
        self.k_shell = c.h(308)         # karosszeria-vesztes
        self.k_speed = c.h(330)         # ennek sebessegfuggese
        self.k_ownsens = c.h(312)       # a sajat kulso szenzor fele
        self.k_mass = c.h(310)          # levego <-> tomeg
        self.k_air2mass = c.h(320)      # tomeg <- levego
        self.k_sun = c.h(332)           # napterheles
        self.k_door = c.h(324)          # nyitott ajtok
        self.k_lowspd = c.h(318)        # kikapcsolt tag (C346: 0)
        self.k_unused = c.h(328)        # kikapcsolt tag (C346: 0)
        self.w_duct = c.h(314)          # a kifuvasi ho sulya a becslesben
        self.cap_above = c.sbv(655)     # felso korlat a kulso ho felett, fok C
        self.n_cool = c.b(647)          # kimeneti szuro, hulesre
        self.n_warm = c.b(648)          # kimeneti szuro, melegedesre
        # --- allapot ---
        self.reset()

    def reset(self, t0=200):
        """t0 = kezdeti homerseklet 0,1 fok C-ban (mindket csomopont)."""
        self.x1 = t0 << Q               # tomeg-csomopont
        self.x2 = t0 << Q               # levego-csomopont
        self.out = t0 * 64              # gp-31264 (Q6), a szurt becsles
        self.rem = 0                    # a kimeneti szuro maradeka

    # --- kenyelmi olvasok, a firmware getterei szerint ---------------------
    @property
    def t_mass(self):
        return self.x1 >> Q             # gp-29066

    @property
    def t_air(self):
        return self.x2 >> Q             # gp-29064

    @property
    def t_incar(self):
        return self.out / 64.0          # gp-29062 / 64, 0,1 fok C

    # ----------------------------------------------------------------------
    def step(self, oat, t_duct_pf, t_duct_pn,
             flow_pf=0, flow_pn=0, speed=0, sun=0, doors=0, own_sens=None,
             t_amb_slow=None):
        """Egy 0x42FA2 ciklus.

        oat        : kulso homerseklet (FUN_45264), 0,1 C
        t_duct_pf  : a padlo/szelvedo NTC-par ATLAGA, 0,1 C
        t_duct_pn  : a panel NTC-par ATLAGA, 0,1 C
        flow_pf    : gp-29052 + gp-29056
        flow_pn    : gp-29054
        speed      : szurt sebesseg km/h (FUN_4997E)
        sun        : max napszenzor 0..255 (FUN_475FA)
        doors      : nyitott zarak szama (FUN_4AA54)
        own_sens   : a sajat kulso szenzor (FUN_3EEDE), 0,1 C; None -> oat
        t_amb_slow : gp-29072 >> 6, a korlatozashoz; None -> oat
        """
        if own_sens is None:
            own_sens = oat
        if t_amb_slow is None:
            t_amb_slow = oat

        t2_32 = self.x2 >> 17           # T2 * 32
        t1_32 = self.x1 >> 17           # T1 * 32

        # --- tomeg-csomopont (0x42FE4) ------------------------------------
        d64 = (self.x2 - self.x1) >> 16                  # (T2-T1)*64
        term = (d64 * self.k_air2mass) // 65536 + (d64 * 8) // 125
        x1_new = self.x1 + (term << 10)

        acc = 0
        # 1. padlo + szelvedo befujas (0x430EE)
        r23 = flow_pf * 4
        g = (r23 * self.k_duct_pf) // 65536 + r23 // 195
        acc += (((t_duct_pf * 32 - t2_32) * g) >> 14) << 15
        # 2. panel befujas (0x4313A)
        g = (flow_pn * self.k_duct_pn) // 8192 + (flow_pn * 12) // 293
        acc += (((t_duct_pn * 32 - t2_32) * g) >> 14) << 14
        # 3. karosszeria-vesztes, sebessegfuggo (0x4319E)
        sp20 = oat * 32 - t2_32
        g = (sp20 * self.k_shell) // 65536 + (sp20 * 2) // 125
        r22 = speed * 128
        f = ((r22 * self.k_speed) // 65536 + r22 // 781) // 2 + 8192
        acc += ((sat16(f) * g) >> 14) << 12
        # 4. a sajat kulso szenzor fele (0x431FE)
        sp22 = own_sens * 32 - t2_32
        acc += ((sp22 * self.k_ownsens) // 65536 + sp22 // 781) << 8
        # 5. tomeg-csere (0x4322A)
        sp24 = t1_32 - t2_32
        acc += ((sp24 * self.k_mass) // 65536 + sp24 // 125) << 13
        # 6. napterheles (0x43272)
        acc += ((sun * self.k_sun) // 512 + (sun * 77) // 47) << 8
        # --- innentol X2/4 skala (0x432A4):  r27 = acc/2 + X2/4 -----------
        r27 = (acc >> 1) + (self.x2 >> 2)
        # 7. nyitott ajtok (0x432B0) -- MAR a r27 skalan, azaz X2-re x4
        base = 9472 - (self.x2 >> 16)
        r27 += ((((base * self.k_door) // 65536) * (doors << 11)) >> 14) << 11
        # 8. alacsony sebessegu tag (0x432E6) -- C346-on cal.h[318] = 0
        if self.k_lowspd and speed <= 2:
            d = ((own_sens * 16) - (self.x2 >> 18)) << 1
            r27 += ((self.k_lowspd * d) >> 9) << 4
        x2_new = r27 << 2

        # --- a becsult belso ho (0x433AC) ---------------------------------
        w = (((flow_pf >> 4) << 7) * self.w_duct) >> 8
        w = sat16(w)
        t2n_32 = x2_new >> 17
        a = ((16384 - w) * t2n_32) >> 14 >> 1                  # T2 * 16 * (1-w)
        b = ((w * t_duct_pf) >> 8) >> 2                        # a kifuvasi resz
        est = ((a + b) << 2) + interp(self.cal.curve(1552), oat) * 64

        # --- korlatozas (0x43582) -----------------------------------------
        sun_corr = self.solar_correction(oat, sun)
        hi = (t_amb_slow + self.cap_above * 10) * 64
        lo = t_amb_slow * 64 - sun_corr * 16
        x2_new = max(min(x2_new, hi << 16), lo << 16)

        # X1 also korlat (0x4365E):  clip(OAT, +-200) - cal+1588
        lo1 = (clip(oat, -200, 200) << Q) - (interp(self.cal.curve(1588), oat) * 4 << 20)
        x1_new = max(x1_new, lo1)

        self.x1, self.x2 = x1_new, x2_new

        # --- kimeneti szuro (FUN_437C0) -----------------------------------
        n = self.n_cool if self.out > est else self.n_warm
        self.out = self._iir(est, n)
        return self.out

    def solar_correction(self, oat, sun):
        """gp-26250, 0,1 fok C  (0x434C8)."""
        sp60 = interp(self.cal.curve(1620), sun)
        sp58 = interp(self.cal.curve(1598), oat)
        return (sat16(sp58 * sp60) * 5243) >> 19

    def _iir(self, new, n):
        """FUN_4B29E / FUN_4B248 (39.0), elojeles bemenettel."""
        if n >= 16:
            self.rem = 0
            return new
        n = min(n, 15)
        mask = (1 << n) - 1
        if self.rem > mask:
            self.rem = 0
        t = new + self.out * ((1 << n) - 1) + self.rem
        self.rem = t & mask
        return t >> n


# --- parancsok ---------------------------------------------------------------
def cmd_coeffs(a):
    m = CabinModel(a.variant)
    print('valtozat: %s   (blokk bazis 0x%X)' % (m.variant, m.cal.base))
    print()
    rows = [
        ('cal.h[288]', 'modell lepeskoz', m.period, ''),
        ('cal.h[300]', 'kimeneti szuro lepeskoz', m.period_out, ''),
        ('cal.h[322]', 'padlo+szelvedo befujas', m.k_duct_pf, '%.5f' % (m.k_duct_pf / 65536 + 1 / 195)),
        ('cal.h[316]', 'panel befujas', m.k_duct_pn, '%.5f' % (m.k_duct_pn / 8192 + 12 / 293)),
        ('cal.h[308]', 'karosszeria-vesztes', m.k_shell, '%.5f' % (m.k_shell / 65536 + 2 / 125)),
        ('cal.h[330]', ' - sebessegfuggese', m.k_speed, '%.3f /kmh' % (m.k_speed / 65536 * 128 / 2 + 128 / 781 / 2)),
        ('cal.h[312]', 'sajat kulso szenzor fele', m.k_ownsens, '%.5f' % (m.k_ownsens / 65536 + 1 / 781)),
        ('cal.h[310]', 'tomeg -> levego', m.k_mass, '%.5f' % (m.k_mass / 65536 + 1 / 125)),
        ('cal.h[320]', 'levego -> tomeg', m.k_air2mass, '%.5f' % (m.k_air2mass / 65536 + 8 / 125)),
        ('cal.h[332]', 'napterheles', m.k_sun, '%.4f' % (m.k_sun / 512 + 77 / 47)),
        ('cal.h[324]', 'nyitott ajtok', m.k_door, '%.5f' % (m.k_door / 65536)),
        ('cal.h[314]', 'kifuvasi ho sulya', m.w_duct, ''),
        ('cal.h[318]', 'alacsony sebessegu tag', m.k_lowspd, 'KI' if not m.k_lowspd else ''),
        ('cal.h[328]', 'nem hasznalt tag', m.k_unused, 'KI' if not m.k_unused else ''),
        ('cal.b[655]', 'felso korlat a kulso ho felett', m.cap_above, 'fok C'),
        ('cal.b[647]', 'kimeneti szuro, hulesre  (N)', m.n_cool, '%d periodus' % (1 << m.n_cool)),
        ('cal.b[648]', 'kimeneti szuro, melegedesre (N)', m.n_warm, '%d periodus' % (1 << m.n_warm)),
    ]
    print('%-12s %-34s %8s  %s' % ('cal', 'mit allit', 'ertek', 'szamitva'))
    print('-' * 78)
    for k, d, v, x in rows:
        print('%-12s %-34s %8d  %s' % (k, d, v, x))
    print()
    print('cal+1552 (OAT-eltolas)     :', m.cal.curve(1552))
    print('cal+1588 (X1 also korlat)  :', m.cal.curve(1588))
    print('cal+1598 (napkorr. suly %) :', m.cal.curve(1598))
    print('cal+1620 (napkorr. gorbe)  :', m.cal.curve(1620))


def _run(m, minutes, **kw):
    n = int(minutes * 60 * 1000 / m.period)
    for _ in range(n):
        m.step(**kw)
    return n


def cmd_step(a):
    m = CabinModel(a.variant)
    m.reset(a.start)
    print('valtozat %s, lepeskoz %d (feltetelezve ms)' % (m.variant, m.period))
    print('OAT %.1f C  kifuvas padlo/szel %.1f C  panel %.1f C  aramlas %d/%d'
          % (a.oat / 10, a.duct / 10, a.duct_panel / 10, a.flow, a.flow_panel))
    print('sebesseg %d km/h  nap %d  nyitott zar %d' % (a.speed, a.sun, a.doors))
    print()
    print('%6s  %8s  %8s  %8s' % ('perc', 'T_levego', 'T_tomeg', 'becsles'))
    kw = dict(oat=a.oat, t_duct_pf=a.duct, t_duct_pn=a.duct_panel,
              flow_pf=a.flow, flow_pn=a.flow_panel, speed=a.speed,
              sun=a.sun, doors=a.doors)
    print('%6.1f  %8.1f  %8.1f  %8.1f' % (0, m.t_air / 10, m.t_mass / 10, m.t_incar / 10))
    for k in range(a.minutes):
        _run(m, 1, **kw)
        if (k + 1) % a.every == 0 or k == a.minutes - 1:
            print('%6.1f  %8.1f  %8.1f  %8.1f'
                  % (k + 1, m.t_air / 10, m.t_mass / 10, m.t_incar / 10))


def cmd_soak(a):
    """Allo auto: nincs fuvo, nincs sebesseg, csak nap es karosszeria."""
    m = CabinModel(a.variant)
    m.reset(a.oat)
    print('Allo jarmu, OAT %.1f C, napszenzor %d, fuvo ki.' % (a.oat / 10, a.sun))
    print('(a modell felso korlatja: kulso ho + %d C)' % m.cap_above)
    print()
    print('%6s  %8s  %8s  %8s' % ('perc', 'T_levego', 'T_tomeg', 'becsles'))
    kw = dict(oat=a.oat, t_duct_pf=a.oat, t_duct_pn=a.oat,
              flow_pf=0, flow_pn=0, speed=0, sun=a.sun, doors=0)
    for k in range(a.minutes):
        _run(m, 1, **kw)
        if (k + 1) % a.every == 0 or k == a.minutes - 1:
            print('%6.1f  %8.1f  %8.1f  %8.1f'
                  % (k + 1, m.t_air / 10, m.t_mass / 10, m.t_incar / 10))


def _tau(m, dt=100, **kw):
    """Idoallando becslese: mekkora a valtozas egy ciklus alatt dt elteresre."""
    m.reset(200)
    before = m.x2
    m.step(**kw)
    d = (m.x2 - before) / float(1 << Q)      # 0,1 C / ciklus
    if d == 0:
        return None
    return abs(dt / d) * m.period / 1000.0   # masodperc


def cmd_selftest(a):
    m = CabinModel(a.variant)
    ok = fail = 0

    def chk(name, cond, extra=''):
        nonlocal ok, fail
        if cond:
            ok += 1
            print('  OK   %-52s %s' % (name, extra))
        else:
            fail += 1
            print('  HIBA %-52s %s' % (name, extra))

    print('=== 39.0  a szuro (FUN_4B248) ===')
    m.reset(0)
    m.out = 0
    chk('N=16 -> atkotes', m._iir(1234, 16) == 1234)
    m.out, m.rem = 0, 0
    for _ in range(200):
        m.out = m._iir(64, 3)
    chk('N=3 lepesvalasz beall pontosan 64-re', m.out == 64, 'vegertek %d' % m.out)
    m.out, m.rem = 0, 0
    for _ in range(400):
        m.out = m._iir(1, 6)
    chk('kis jel is atmegy (nincs holtsav)', m.out == 1, 'vegertek %d' % m.out)

    print()
    print('=== 39.4  egyensuly ===')
    m = CabinModel(a.variant)
    m.reset(200)
    kw = dict(oat=200, t_duct_pf=200, t_duct_pn=200, flow_pf=500, flow_pn=500,
              speed=50, sun=0, doors=0)
    _run(m, 120, **kw)
    chk('minden 20 C -> marad 20 C', abs(m.t_air - 200) <= 1,
        'T_levego %.1f C' % (m.t_air / 10))
    chk('a tomeg-csomopont is', abs(m.t_mass - 200) <= 1,
        'T_tomeg %.1f C' % (m.t_mass / 10))
    off = interp(m.cal.curve(1552), 200)          # cal+1552 eltolas 20 C-on
    chk('a becsles = T_levego + cal+1552 eltolas',
        abs(m.t_incar - (200 + off)) <= 2,
        'becsles %.1f C, eltolas %+.1f C' % (m.t_incar / 10, off / 10))

    print()
    print('=== idoallandok (a 39.4 tablazat ellenorzese) ===')
    for name, kw2, exp in [
        ('karosszeria-vesztes, allo', dict(oat=100, t_duct_pf=200, t_duct_pn=200,
                                           flow_pf=0, flow_pn=0, speed=0, sun=0, doors=0), 499),
        ('karosszeria-vesztes, 100 km/h', dict(oat=100, t_duct_pf=200, t_duct_pn=200,
                                               flow_pf=0, flow_pn=0, speed=100, sun=0, doors=0), None),
        ('tomeg -> levego', dict(oat=200, t_duct_pf=200, t_duct_pn=200,
                                 flow_pf=0, flow_pn=0, speed=0, sun=0, doors=0,
                                 own_sens=200), None),
    ]:
        mm = CabinModel(a.variant)
        if name.startswith('tomeg'):
            mm.reset(200)
            mm.x1 = 300 << Q
            before = mm.x2
            mm.step(**kw2)
            d = (mm.x2 - before) / float(1 << Q)
            t = abs(100 / d) * mm.period / 1000.0 if d else None
        else:
            t = _tau(mm, 100, **kw2)
        print('  %-34s tau = %s' % (name, ('%.0f s = %.1f perc' % (t, t / 60)) if t else 'n/a'))
        if exp:
            chk('  ... a 39.4 tablazat szerint ~%d s' % exp, abs(t - exp) / exp < 0.10)

    print()
    print('=== napterheles allandosult allapotban ===')
    for sun in (0, 128, 255):
        mm = CabinModel(a.variant)
        mm.reset(250)
        _run(mm, 240, oat=250, t_duct_pf=250, t_duct_pn=250, flow_pf=0,
             flow_pn=0, speed=0, sun=sun, doors=0)
        print('  nap=%3d ->  T_levego %.1f C   (OAT 25,0 C)  emelkedes %+.1f C'
              % (sun, mm.t_air / 10, (mm.t_air - 250) / 10))
    mm = CabinModel(a.variant)
    mm.reset(250)
    _run(mm, 240, oat=250, t_duct_pf=250, t_duct_pn=250, flow_pf=0,
         flow_pn=0, speed=0, sun=255, doors=0)
    chk('a felso korlat (kulso + %d C) tartja' % m.cap_above,
        mm.t_air <= 250 + m.cap_above * 10 + 5, 'T_levego %.1f C' % (mm.t_air / 10))

    print()
    print('=== 39.7  aszimmetrikus kimeneti szuro ===')
    up = CabinModel(a.variant)
    up.reset(200)
    up.out = 200 * 64
    n_up = 0
    while up.out < 300 * 64 - 64 and n_up < 100000:
        up.out = up._iir(300 * 64, up.n_warm)
        n_up += 1
    dn = CabinModel(a.variant)
    dn.reset(300)
    dn.out = 300 * 64
    n_dn = 0
    while dn.out > 200 * 64 + 64 and n_dn < 100000:
        dn.out = dn._iir(200 * 64, dn.n_cool)
        n_dn += 1
    print('  10 C ugras 90 %%-a:  melegedes %d, hules %d periodus (%.2f s / %.2f s)'
          % (n_up, n_dn, n_up * m.period_out / 1000, n_dn * m.period_out / 1000))
    chk('hulesre lassabb, mint melegedesre', n_dn > n_up)

    print()
    print('%d rendben, %d hiba' % (ok, fail))
    return 1 if fail else 0


def cmd_compare(a):
    ms = [CabinModel(v) for v in a.variants]
    keys = ['period', 'k_duct_pf', 'k_duct_pn', 'k_shell', 'k_speed', 'k_ownsens',
            'k_mass', 'k_air2mass', 'k_sun', 'k_door', 'w_duct', 'k_lowspd',
            'k_unused', 'cap_above', 'n_cool', 'n_warm']
    print('%-14s' % 'mezo' + ''.join('%12s' % m.variant for m in ms))
    print('-' * (14 + 12 * len(ms)))
    for k in keys:
        vals = [getattr(m, k) for m in ms]
        mark = '   <<<' if len(set(vals)) > 1 else ''
        print('%-14s' % k + ''.join('%12d' % v for v in vals) + mark)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--variant', default='C346')
    sub = p.add_subparsers(dest='cmd')

    sub.add_parser('coeffs').set_defaults(fn=cmd_coeffs)
    sub.add_parser('selftest').set_defaults(fn=cmd_selftest)

    s = sub.add_parser('step')
    s.add_argument('--oat', type=int, default=50, help='kulso ho, 0,1 C')
    s.add_argument('--start', type=int, default=200, help='kezdeti ho, 0,1 C')
    s.add_argument('--duct', type=int, default=400, help='padlo/szelvedo kifuvas, 0,1 C')
    s.add_argument('--duct-panel', type=int, default=400, help='panel kifuvas, 0,1 C')
    s.add_argument('--flow', type=int, default=400, help='gp-29052 + gp-29056')
    s.add_argument('--flow-panel', type=int, default=0, help='gp-29054')
    s.add_argument('--speed', type=int, default=0)
    s.add_argument('--sun', type=int, default=0)
    s.add_argument('--doors', type=int, default=0)
    s.add_argument('--minutes', type=int, default=30)
    s.add_argument('--every', type=int, default=2)
    s.set_defaults(fn=cmd_step)

    s = sub.add_parser('soak')
    s.add_argument('--oat', type=int, default=350)
    s.add_argument('--sun', type=int, default=255)
    s.add_argument('--minutes', type=int, default=60)
    s.add_argument('--every', type=int, default=5)
    s.set_defaults(fn=cmd_soak)

    s = sub.add_parser('compare')
    s.add_argument('variants', nargs='+')
    s.set_defaults(fn=cmd_compare)

    a = p.parse_args()
    if not getattr(a, 'fn', None):
        p.print_help()
        return 0
    return a.fn(a) or 0


if __name__ == '__main__':
    sys.exit(main())
