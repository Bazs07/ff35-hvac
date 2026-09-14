# HVAC — Klíma / DEATC (0x733, MS-CAN)

Arch: **V850 (Visteon)** [B — ©Visteon 1998, `EV850T06…V105`, korábbi teljes visszafejtés] ·
Fő EXE: F1ET-18D619-AM (0.46 MB) · SBL F1ET-18D618-AA.

## 1. Szerep / állapot
Automata klíma: hőmérséklet-szabályozás, fúvó, légelosztás, recirkuláció, A/C, gomb-LED visszajelzés.
**Teljesen visszafejtve korábban** (`HVAC_ELEMZES.md`, `HANDOFF.md`): szabályozó egyenletek,
kalibráció-térkép, CAN-táblák, UDS DID/DTC, és kész patch-ek (AUTO légelosztás, dual-zone).

## 2. Integritás
- **Belső flash-CRC16 megfejtve**: poly 0x1021, init 0, tárolva 0x77FF4 (BE), gyári 0xD8DF;
  patch után `fwcrc.py resign` (különben 22-es DTC). VBF-CRC OK.

## 3. Mit érdemes módosítani
- AUTO légelosztás-adaptivitás, dual-zone szétválasztás, ülésfűtés-automatika/memória, auto-recirk
  — kész eszközök (`calpatch.py`, `patch_autodist.py`), lásd korábbi HVAC-munka.

## Bizonyosság
- [B] minden (korábbi teljes visszafejtés + round-trip-tesztelt patch-ek).
