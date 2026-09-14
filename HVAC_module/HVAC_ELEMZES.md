# Ford Focus MK3.5 — DEATC (automata klíma) modul firmware-elemzés

Modul: **F1ET-18D619-AM** ("Ford C34x MCA DEATC", Visteon), egység-cikkszám a
firmware-ben: `DS-F1ET-18C612-AG`, kalibráció-azonosító `BE05F012`.
Buszcím (UDS/diag): **0x733**, hálózat: **MS-CAN**.
Elemzés kelte: 2026-08-21. Bizonyossági jelölés: **[B]** = bizonyított (kódból/adatból
levezetve és ellenőrizve), **[E]** = erős következtetés, **[H]** = hipotézis.

---

## 1. A mappa tartalma

| Fájl | Mi ez |
|---|---|
| `F1ET-18D619-AM.VBF` (459 474 B) | **A tényleges alkalmazás-firmware.** 1 blokk: `0x00008000`–`0x00077FFF` (448 KB). `sw_part_type = EXE`, törlési tartomány `0x8000..0x70000`. |
| `F1ET-18D618-AA.vbf` (4 591 B) | **SBL — másodlagos bootloader / flash-driver** ("Flash driver for V850 Fx4-L"). RAM-ba töltődik `0xFEDF8000`-re. Ez csak a flashelés eszköze, nem a modul működése. |
| `*.zip` | ugyanezek tömörítve, semmi extra. |

Kicsomagolva (`tools/vbf.py unpack`): `F1ET-18D619-AM_00008000.bin`,
`F1ET-18D618-AA_FEDF8000.bin`.

---

## 2. Platform

- Mag: **Renesas V850 (Fx4-L család)**, V850E1/ES-kompatibilis utasításkészlet. **[B]**
  (A HCM-projekt `v850dis.py` diszasszemblere 0,27 % ismeretlen dekódolással fut rá.)
- Flash: `0x00000000`–`0x00077FFF`; ebből a **bootloader `0x0000`–`0x7FFF`** (nincs a
  VBF-ben), az **alkalmazás `0x8000`–`0x77FFF`**.
- RAM: `0xFEDF8000`–`~0xFEE0C000`. `gp = 0xFEE04000`, `ep = 0xFEDFE698`,
  `sp = 0xFEDFFFCC`, `tp = 0x0001A1C8`. **[B]** (a startup 0x122BE-nél)
- Megszakítás-vektortábla: `0x8000`-től, 4 bájtos `jr` bejegyzések; a nem használt
  vektorok `0x122BA`-ra (reset/trap) mutatnak. Az ISR-ek `0x13D5E`-től, egyenként
  ~0xC8 bájt prológussal. **[B]**
- Stack-fill minta `0xF840F840` (stack-használat mérésére). **[B]**

### Perifériatérkép (konstans-propagációval kinyerve, `tools/sfr.py`) **[B]**

| Cím | Funkció | Használó fv. |
|---|---|---|
| `0xFF400000`–`0xFF404xxx` | **Portok** (be/kimenetek, H-hidak) | `0x13D2E`, `0x4Dxxx`–`0x4Fxxx` |
| `0xFF420000`–`0xFF42Axxx` | reset-ok, órajel-generátor, PLL init | `0x12502`, `0x18Bxx`–`0x18Fxx` |
| `0xFF43xxxx` | **flash-vezérlő** (önprogramozás) | `0x593xx`–`0x599xx` |
| `0xFF48xxxx` | **CAN (FCN)** — 64 bájtos mailboxok, `MCTRL` a +56-on | `0x1A174`, `0x1A23C`, `0x1B0BC` |
| `0xFF80xxxx` | időzítők | `0x123DC`, `0x18C48`, `0x190C4` |
| `0xFF809xxx` | időzítő/PWM-blokk (csatorna-regiszterek `+0x240`…`+0x26C`) | `0x22B88`, `0x26E56`, `0x2B772` |
| `0xFF81D000` | **A/D konverter**, 2 bank × 24 csatorna | `0x1272C` (init), `0x13846` (olvasás) |
| `0xFF811000` | CAN órajel | `0x1A04A` |

`AdcRead(csatorna, bank)` = **`FUN_13846`**, visszatérés `r10`-ben 16 bites nyers érték.
**[B]** — pl. `FUN_5391A` a 23., 21., 20. csatornát olvassa egymás után.

---

## 3. Szoftver-architektúra

- **Statikus ütemező (OSEK-szerű), függvénypointer-táblákkal a `0x9DE0`–`0xA1F0`
  konfigurációs területen.** **[B]**
  - `0x9E7C` (4 elem), `0x9E90` (6 elem): init/hook listák, NULL-lezárva.
  - `0x9EAC` (~125 elem) + `0xA0A4` (81 elem): a **periodikus feladatok listája**.
    `FUN_1952C` végigiterál rajta, `jmp [r29]`-nel hívja őket, amíg valamelyik 0-t nem ad.
  - `FUN_197AE` = a fő végtelen ciklus (`br 0x197F8`).
  - `FUN_1914A` = **tick-kezelő**: ~10 szoftver-időzítőt dekrementál, lejáratkor
    bitet állít `gp-28414`-en.
  - `FUN_22B3A` / `FUN_22B64` = **di/ei kritikus szakasz** be/ki (a két leggyakrabban
    hívott függvény: 319 ill. 337 hívás).
- **`0xA1F0`–`0xA820`: {függvénypointer, maszk} párok táblája** — eseményhez/üzemmódhoz
  kötött kezelők. **[E]**
- Összesen **1838 azonosított függvény**, kód gyakorlatilag `0xC000`–`0x5B000` között,
  plusz egy második blokk `0x57000`–`0x59000` (48 elemű pointer-tábla `0x59224`-nél)
  és a flash-önprogramozó könyvtár `0x59xxx`-ben (`EV850T06xxxxxxV105`).

### CAN **[B]**
- FCN kontroller, **32 mailbox**. A konfigurációs táblák `0xA98C`–`0xAA30`:
  - `0xA98C`: mailbox-index leképezés (9 TX + 23 RX)
  - `0xA9CC`: **DLC-tábla** — 32 bejegyzés (8,8,8,8,8,8,3,6,7,5,6,6,8,4,4,3,5,5,8,6,5,6,8,2,6,8,1,5,8,8,8,8)
  - `0xA9EC`, `0xAA0A`: csoport-index és bitmaszk üzenetenként
  - `0xAA88`: **7 TX puffer** RAM-pointere (`0xFEDFC7EC`-tól, 8 bájtonként)
  - `0xAB00`: RX pufferek pointerei (`0xFEDFC824`-től)
- `FUN_1A174` = RX mailbox kiolvasás, `FUN_1AAF4` = TX kérés.
- **Az üzenet-összeállítók megtalálva**: pl. **`FUN_39838`** és `FUN_3A37A`, `FUN_4CC42` —
  ezek getter-függvényeket hívnak, és bitmezőnként töltik a TX puffert
  (`gp-30712`…`gp-30692`), mindig `di`/`ei` közé zárva.
  Innen indulva végigkövethető, melyik belső állapot melyik CAN-bitre kerül.

### Érzékelők **[B]**
`0xE1F0`-től 20 bájtos bejegyzésekből álló tábla: `{ADC-csatorna, skálázó, típus,
határok, szűrő-konstansok}`. A `FUN_4FD12` ebből olvassa a csatornaszámot és hívja
`FUN_13846`-ot. **Ténylegesen 7 klíma-érzékelő van bekonfigurálva** (ADC csat. 11, 13,
10, 12, 14, 15, 6) + 3 csatorna a fűtött ülés NTC-khez (23, 21, 20). Több nincs —
gombsor-ellenálláslánc **nincs**, lásd 6. szakasz.

### Végrehajtók **[E]**
`FUN_4DF08`, `FUN_4E1CA`, `FUN_4E476`, `FUN_4E5E2`, `FUN_4EA22`, `FUN_4EB8E`,
`FUN_4F110`, `FUN_4F270`, `FUN_4F662`, `FUN_4F7C2` — ~10 egyforma szerkezetű
csatorna: bemeneti portbiteket olvasnak (`0xFF400200` 11./12. bit), és 4 kimeneti
bitet állítanak/törölnek H-híd irányvezérlésként (keverőajtók, mód-ajtó, recirkuláció).

---

## 4. Kalibráció (a legkönnyebben módosítható rész)

- `0xBB40`–`0xBD90`: fejléc-blokk — cikkszámok (`F1ET-18D619-AM`, `DS-F1ET-18C612-AG`,
  `BE05F012`), `Copyright 1998, Visteon Corp`, konfigurációs bájtok.
- `0xC800`–`0xE400`: **globális kalibrációs táblák**. **[B]** Példák:
  - `0xD140`-től: **ventilátor-feszültség térkép** 8.8 fixpontos értékekkel
    (`0x0600`=6,0 V … `0x0C00`=12,0 V), soronként 8–9 elem — ez az AUTO fúvó-jelleggörbe
    a hőmérséklet-hiba és a külső hő függvényében.
  - `0xCB82`, `0xE0BF`: 29 elemű felszálló sorok (0x20…0x3C) — a **16,0–30,0 °C-os
    alapjel 0,5 fokos lépései** (29 érték).
- `0xE2FA`-tól: **jármű-változatonkénti kalibrációs blokkok**, mindegyik
  `u16 hossz = 0x09E0` + 8 bájt név + adat: **[B]**

  | Blokk kezdete | Név |
  |---|---|
  | `0x0E2FA` | `C344GM` |
  | `0x0ECDA` | `C344CM` |
  | `0x0F6BA` | `C346` |
  | `0x1009A` | `C346NA` |
  | `0x10A7A` | `C346FAP` |
  | `0x1145A` | `C344NA` |

  (C346 = Focus, C344 = C-Max/Grand C-Max.) A kiválasztás konfigurációból történik, lásd 8. szakasz. A blokkokban ismétlődő, azonos szerkezetű
  szeletek vannak (`0xEB70`, `0xEB81`, `0xEB92`, `0xEBA3` … 0x11 bájtos lépéssel) —
  **[H]** ezek a mód-ajtó / keverőajtó menetrendek fokozatonként.
- `Calibration ok! BE05F012` szöveg `0xE2BB`-nél → van kalibráció-ellenőrző rutin. **[E]**

---

## 5. Ellenőrző összegek — MIND MEGFEJTVE **[B]**

Ez a módosítás előfeltétele, és teljesen kész.

1. **VBF blokk-checksum** = CRC16-CCITT, poly `0x1021`, init `0xFFFF`, a blokk adatán.
   Mindkét VBF-en pontosan egyezik.
2. **VBF `file_checksum`** = szabványos **CRC32** a header utáni teljes bináris testen.
   Mindkét VBF-en pontosan egyezik.
3. **Belső flash-integritás CRC** — `FUN_54218` háttérfeladat:
   - 512 bájtos adagokban végigmegy a `0x8000`–`0x77FF3` tartományon,
   - a kernel `FUN_542C8` **tábla-vezérelt CRC16** (poly `0x1021`, init `0x0000`,
     MSB-first), a 256×u16 tábla a flashben **`0x11FC6`**-nál,
   - az eredményt a **`0x77FF4`-en BIG ENDIAN tárolt** értékhez hasonlítja
     (gyári érték: **`0xD8DF`** — újraszámolva pontosan egyezik),
   - eltéréskor **`FUN_24B08(22)`** = 22-es DTC beállítása; egyezéskor `FUN_23DA0(22)`.

   Tehát **bármilyen bájtmódosítás után a `0x77FF4`-et újra kell írni**, különben a
   modul hibakódot dob. A `tools/fwcrc.py resign` ezt megcsinálja.

**A teljes patch-lánc működik és bitre visszaellenőrzött:**
`vbf.py unpack` → bájtmódosítás → `fwcrc.py resign` → `vbf.py pack` (round-trip teszt
változatlan bemeneten bitazonos VBF-et ad).

---

## 6. Ki-/bemenetek (részben pontosítva a 9. szakaszban) — mit vezérel ténylegesen ez a modul  **[B]**

Konstans-propagacios teljes atvizsgalas (`tools/portmap.py`, `tools/sfr.py`) utan a modul
**teljes** fizikai I/O-keszlete:

| Csoport | Darab | Hol |
|---|---|---|
| Analog erzekelo (klima) | **7** | `0xE1F0` tabla: ADC csat. 11, 13, 10, 12, 14, 15, 6 |
| Analog erzekelo (fuiott ules NTC) | 3 | ADC csat. 23 (referencia), 21, 20 — `FUN_5391A`, aranyszamitas `FUN_5397C` |
| Ajtomotor H-hid | ~12 csatorna | `FUN_4DF08`, `4E1CA`, `4E476`, `4E5E2`, `4EA22`, `4EB8E`, `4EFCE`, `4F110`, `4F270`, `4F662`, `4F7C2`, `4FBE0` — port bit 10/11 + bemeneti bit 11/12 (allas-visszajelzes) |
| Fuiott ules kimenet + szintjelzo | 11 pin | `FUN_503B4` / `FUN_50674`; a szintjelzo `FUN_53814` = **2 csatorna x 1-a-3-bol** (bal/jobb, 3 fokozat) |
| Diagnosztikai kimenet-felulbiralas | ugyanaz a 11 pin | `FUN_50D2A` egy **5 bajtos arnyekbitterkep**bol (`gp-25841`) hajtja a labakat; irja `FUN_50CE8`, torli `FUN_50CBA` — ez a UDS InputOutputControl ut |
| Egyeb digitalis | ~6 | `FUN_4BB30` (port-init), `FUN_534DE`, `FUN_50024/50042` |

**Nincs tobb.** Nincs LCD-vezerlo periferia, nincs soros kijelzo-adatregiszter, nincs
szegmens-kimenet, nincs 7-szegmenses fonttabla, es a kodteruleten **egyetlen osztas
sincs** (szamjegy-kiszedeshez elengedhetetlen lenne). Nincs ellenallaslancos
gombbeolvasas sem: mindossze 10 analog csatorna van hasznalatban, mind erzekelo.

**Kovetkeztetes: ez a modul semmilyen kijelzot nem rajzol.** Ez a klima *vegrehajto*
egyseg: erzekelok, ajtomotorok, fuvo, fuiott ules, plusz MS-CAN.

---

## 7. A fuvasi irany utja — MEGTALALVA  **[B]**

### A modul belso allapotarchitekturaja
1. A vezerlologika (`FUN_2E5FA`, 3783 utasitas) szamolja az allapotot.
2. Az allapot egy **10 bajtos, bitmezokbe csomagolt rekordba** kerul a belso
   adat-poolba (`gp-32514` = `0xFEDFC33E`), a pool-iro `FUN_2962C(cim, forras, offset, hossz)`,
   regiodeszkriptor-tabla `0xC02C`-nel.
3. `FUN_38F8C` visszafejti a bitmezoket kulon valtozokba (`gp-29132`-tol).
4. `FUN_38E22(dst)` kimasolja a **12 bajtos allapotstrukturat** — ket forras kozul
   valaszt (`gp-29132` vagy `gp-31840`) a `FUN_2BA34` jelzo alapjan.
5. Mezo-getterek: **`FUN_4AB54` = `struct[0]` = A FUVASI IRANY (mode), 53 hivoval** —
   a modul legtobbet olvasott jele. Tovabba `FUN_4AB9C`=[1], `FUN_4AB78`=[2],
   `FUN_4AC00`=[3], `struct[9]` = fuvofokozat.

### A mode ertekkeszlete es a CAN-ra kepzese
`FUN_4CC42` (a legnagyobb CAN-osszeallito) a `0xFEDFC814` TX-pufferbe bontja szet:

| CAN mezo | RAM | Feltetel a mode (`r29`) ertekere |
|---|---|---|
| **SZELVEDO (defrost)** | `gp-30695` bit3 | mode ∈ {3, 5, 6, 7, 8} |
| **FEJ (panel/face)** | `gp-30695` bit0 | mode ∈ {1, 4, 6, 7} |
| **LAB (floor)** | `gp-30695` bit2 | mode ∈ {2, 4, 5, 7} |
| (allando 1) | `gp-30695` bit1 | mindig |
| mode == 9 | `gp-30696` bit0 | |
| mode == 3 | `gp-30696` bit1 | |
| mode == 10 | `gp-30700` bit6 | |
| rendszer aktiv | `gp-30697` bit3 | mode != 0 |

Ebbol az enum: `0`=nincs, `1`=fej, `2`=lab, `3`=szelvedo(kulon), `4`=fej+lab,
`5`=lab+szelvedo, `6`=fej+szelvedo, `7`=fej+lab+szelvedo, `8`=szelvedo,
`9`/`10`=specialis (max defrost / kulso keres).

### A DONTO megallapitas
**A harom iranybit feltetel nelkul, kizarolag a tenyleges `mode` ertekbol szamolodik —
sehol nincs AUTO-fuggo elnyomas.** Vagyis a modul **AUTO modban is kikuldi a valos
fuvasi iranyt** az MS-CAN-ra.

Ebbol kovetkezik: ha a muszerfalon/SYNC-en AUTO-ban nem latszik a nyil, akkor a
**fogado oldal** (APIM/SYNC vagy IPC) dont ugy, hogy nem rajzolja ki — nem ez a modul
hallgat el. Ezt a firmware-t modositani erre a celra ertelmetlen; a modositast a
kijelzo modulban kell keresni (az APIM-projekt mar el van kezdve).

**Elo ellenorzes (ajanlott elso lepes):** MS-CAN (125 kbit/s) sniff a
`J2534Sniffer`-rel. Kezi modvaltas kozben figyeld, melyik uzenet melyik bajtjanak
0/2/3. bitje valtozik egyutt a modvaltassal — az a `0xFEDFC814` puffer 5. bajtja.
Utana AUTO-ban ellenorizd, hogy ugyanaz a harom bit tovabbra is kovett-e a valos
fuvasi iranyt. Ha igen (ezt varjuk), a kerdes lezarult: az APIM/IPC oldalt kell nezni.

---

## 8. Valtozat-kalibracio kivalasztasa — konfiguraciobol  **[B]**

`FUN_51204` a modul konfiguracios bajtjai alapjan allitja be az **aktiv kalibracios
blokk mutatojat** (`gp-30076`):

| Blokk cime | Nev |
|---|---|
| `0x0E2FA` | `C344GM` (ez az alapertelmezes is) |
| `0x0ECDA` | `C344CM` |
| `0x0F6BA` | `C346` |
| `0x1009A` | `C346NA` |
| `0x10A7A` | `C346FAP` |
| `0x1145A` | `C344NA` |

A dontesi bemenetek: `FUN_4CBE2` (`gp-30825`), `FUN_4CC06` (`gp-30815`),
`FUN_4CC0C` (`gp-30825`/`gp-30819`) — ezek a **data flash / As-Built konfiguraciobol**
jonnek (`0xFE007FE0`, `FUN_51310`). **Ez firmware-modositas nelkul, As-Builttel is
atallithato** — es teljesen mas AUTO-jelleggorbeket kapcsol be.

## 9. A PANEL VISSZAJELZES — teljes lanc megtalalva  **[B]**

> Korabban tevesen azt irtam, hogy a modul semmilyen visszajelzest nem hajt. A hiba
> forrasa a sajat eszkozom volt (`movhi` nem volt kezelve a cimszamitasban), plusz
> az, hogy az LED-ek nem sima portlabakon, hanem **PWM-csatornakon** ulnek. Javitva.
> A panel `F1ET-18C612-DK`, all-in-one egyseg: LCD (csak a ket homerseklet + fuvofokozat)
> **es** gomb-LED-ek, amik a fuvasi iranyt mutatjak.

### A LED-alrendszer
- **`FUN_540AE(led_index, fenyero)`** — a kozponti LED-API, 67 hivoval.
  → `FUN_5410A` → tipustabla `0x11FAE`-nal (csatornankent 1 bajt) → globalis fenyero-
  szazalek (`gp-30801` / `gp-30802`) → `FUN_2B902(csatorna, ertek)` → 23 csatornas
  kimenetkezelo (6 bajtos rekordok `gp-26708`-tol) → PWM hardver.
- **`FUN_540C8`** csatornankent interpolal a `gp-23132` (min) es `gp-23040` (max)
  kalibracios tablak kozott — ez a LED-fenyero kalibracio.
- **Csatornakioszas:**
  - `0..10, 20, 22` — **hatterviligitas**, mind ugyanazt a fenyerot kapja (`FUN_50B2E`)
  - `11..17, 21` — **visszajelzo LED-ek** (`FUN_50674` / `FUN_503B4`)
- Ezenfelul 11 kozvetlen portlab (`FUN_503B4`/`FUN_50674`, diagnosztikai felulbiralas
  `FUN_50D2A`-val az 5 bajtos arnyekbitterkepbol) — ezek a **futott ules 2 x 3 fokozatu
  LED-savjai** es tarsaik.

### A fuvasi irany LED-lanca — VEGIG BIZONYITVA
```
mod-allapotgep (11 fv.)  ->  3 jelzobit  ->  FUN_2E5FA publikal  ->  16 bajtos
FUN_377D8 ... FUN_37B32      gp-32097 fej     0x31424/0x31444/     indikator-struktura
                             gp-32088 lab     0x31464              gp-31888-tol
                             gp-32087 szelv.
   -> FUN_38F4E (masol) -> FUN_50674 -> FUN_540AE(17/16/15, fenyero)
```

**A mod-allapotgep teljes tablazata** (mind a 11 fuggveny dekodolva):

| Fuggveny | mode | fej (`gp-32097`) | lab (`gp-32088`) | szelvedo (`gp-32087`) |
|---|---|---|---|---|
| `FUN_377D8` | 0 | 0 | 0 | 0 |
| `FUN_3797C` | 1 | **1** | 0 | 0 |
| `FUN_37876` | 2 | 0 | **1** | 0 |
| `FUN_37A86` | 3 | 0 | 0 | **1** |
| `FUN_37922` | 4 | **1** | **1** | 0 |
| `FUN_37A2C` | 5 | 0 | **1** | **1** |
| `FUN_379D2` | 6 | **1** | 0 | **1** |
| `FUN_37B32` | 7 | **1** | **1** | **1** |
| `FUN_37ADA` | 8 | 0 | 0 | **1** |
| `FUN_37820` | **9** | **0** | **0** | **0** |
| `FUN_378CE` | 10 | 0 | **1** | 0 |

**Fuggetlen keresztellenorzes:** a CAN-oldali szetbontas (`FUN_4CC42`, 7. szakasz)
pontosan ugyanezt a halmazt adja — fej = {1,4,6,7}, lab = {2,4,5,7},
szelvedo = {3,5,6,7,8}. Ket fuggetlen uton ugyanaz → a hozzarendeles biztos.

### Es itt a keresett ok
A **9-es mode** (`FUN_37820`) az egyetlen olyan allapot, ami **mind a harom
iranyjelzot 0-ra allitja**, miközben a tenyleges ajtoceljelek (`gp-32134/32133/32132`)
mind 9-re allnak, es a CAN-ban is kap egy sajat bitet (`gp-30696` bit0 = „mode == 9").
Ez az **AUTO** allapot: a modul tudja, merre fuj, de a jelzobiteket szandekosan nullazza,
ezert sotet mind a harom LED.

**A modositas helye tehat itt van** — nem a fogado modulban, hanem ebben a firmware-ben.

### Nyitott utolso lancszem
Meg meg kell hatarozni, **melyik valtozo tartja AUTO-ban a tenyleges ajtoallast**
(a `gp-32134/32133/32132` harmas 9-re all, tehat nem az). Amint megvan, a patch
elvi tartalma: `FUN_37820`-ban a harom `st.b r0, -320xx[gp]` helyett a valos iranybol
szarmaztatott ertekek. A hely szuk (a fuggveny 71 bajt), ezert valoszinuleg egy
trambulin kell egy ures flash-teruletre — a checksum-lanc ehhez mar keszen all (5. szakasz).

## 10. Eszközök (`tools/`)

| Fájl | Mit tud |
|---|---|
| `vbf.py` | VBF `unpack` / `pack` / `verify`, mindkét checksummal |
| `fwcrc.py` | belső flash-CRC `verify` / `resign` |
| `v850dis.py` | V850 diszasszembler (a HCM-projektből, erre a képre paraméterezve) |
| `dump.py` | teljes diszasszemblálás → `full.asm` (9,2 MB) + `funcs.json` |
| `sfr.py` | konstans-propagáció → perifériatérkép |
| `scan.py` | hívási statisztika, kódsűrűség |

Kiindulás új menetben: `python tools/dump.py` (újragenerálja a `full.asm`-et),
majd `grep`-elés benne.

---

## 11. Fejlesztesi munkacsomag — allapot (2026-08-21, 2. menet)

Negy funkcio: (1) fuvasi irany AUTO-ban, (2) ulesfutes automatika,
(3) ulesfutes szint-memoria, (4) auto-recirkulacio.
A felhasznalo megerositette: AUTO-ban **mind a harom iranyLED sotet**, a modgomb
**kilep AUTO-bol**, az ulesfutes **mindig kikapcsolva indul**, es **csak vegleges
patchet** flashelunk.

---

### 11.0 BIZONYITVA: mode 9 = AUTO  **[B]**
`FUN_44464` haromszor is kifejezetten erre againzik el:
`0x44A04`, `0x44C3C`, `0x4504E` — mindharom `jarl 0x4AB54; cmp 9, r10`.
Ezenkivul `gp-32091 == 9` vizsgalat van a gombkezelokben (`FUN_360BE`, `FUN_36192`,
`FUN_368FE`, `FUN_369D2`, `FUN_2BA6A`, `FUN_2D6B8`, `FUN_3287C`, `FUN_2E5FA`) —
ez a „AUTO-ban vagyunk?" teszt, ami magyarazza, miert lep ki a modgomb AUTO-bol.

### 11.1 Fuvasi irany AUTO-ban — a kep osszeallt

**A vegrehajtok:** a rajz (55-5 / 55-6) szerint minden ajto **negyfazisu lepteto**
(A/B/C/D + kozos ACTUATOR POWER): `LTEMP` es `RTEMP` keverőajtok, **`PA/FL`
(panel/padlo) es `DEFR` (szelvedo) — ket kulon mod-ajto** —, valamint `RECIRC`.
Pozicio-potmeter nincs (az ADC 7 erzekeloje mind homerseklet vagy napszenzor),
tehat a pozicio szoftveres lepesszamlalo. **[B]**

**A legelosztas-vezerlo: `FUN_3A37A`.** **[B]**
- Bemenete a kozponti igenyertek: `FUN_45264()` = `gp-29040` — a firmware
  legtobbet olvasott jele, **146 hivoval**.
- Ezt **kilenc kalibracios gorben** vezeti at (`FUN_4B3E0`, blokk-offsetek
  `0x2E8, 0x2F6, 0x310, 0x32A, 0x350, 0x36A, 0x378, 0x38A, 0x39C, 0x3AA`).
- Kimenete **harom sebessegkorlatozott ajtopozicio**
  (`FUN_4B29E(allapot, elozo, cel, rata)` = rampa):

  | allapot | eredmeny | cel |
  |---|---|---|
  | `gp-31780` | `gp-31726` | `sp[8] << 2` |
  | `gp-31778` | `gp-31724` | `sp[76]` |
  | `gp-31776` | `gp-31722` | `gp-26377 << 2`, `cal[518]`/`cal[519]` koze vagva |

**A dontő felismeres:** AUTO-ban a modul **nem szamol diszkret fuvasi iranyt**.
A ket mod-ajto folytonosan van pozicionalva az igeny-gorbebol — ezert nincs mit
kiirni, es ezert sotetek a LED-ek. Ez nem hiba, hanem architekturalis kovetkezmeny.

**A patch tehat szarmaztat:** a ket mod-ajto poziciojabol kuszobokkel kell
eloallitani a harom iranybitet — pontosan ugy, ahogy egy mai auto is teszi.

Patch-terv:
1. Uj rutin a szabad flashben (`0x77E00`, 256 bajt).
2. Beolvassa a `PA/FL` es `DEFR` ajto poziciojat a fenti harom kozul.
3. Kuszobozes -> `gp-32097` (fej), `gp-32088` (lab), `gp-32087` (szelvedo).
4. Beakasztas: a `FUN_37820` (mode 9 = AUTO) harom `st.b r0` utasitasa helyere
   egy hivas (`0x37848` / `0x3784C` / `0x37850`).
5. `fwcrc.py resign` + `vbf.py pack`.

**Meg nyitott (egyetlen tetel):** a harom `FUN_3A37A`-kimenet kozul melyik a
`PA/FL` es melyik a `DEFR` ajto. Ez korulhatarolt: a lepteto-meghajto oldalarol
vagy a kalibracios gorbek alakjabol eldontheto.

### 11.2 / 11.3 Ulesfutes  **[B]**
- Szintek: **`gp-28547` (bal) / `gp-28546` (jobb)**; irja `FUN_534DE` @`0x537FA`/`0x537FE`.
- **Ebredeskor kifejezetten nullazza**: `FUN_534DE` @**`0x534FE`** es **`0x53502`**
  (`st.b r0, -28547[gp]` / `st.b r0, -28546[gp]`). Ez a 3-as tetel patch-pontja.
- Tarolas: az NVM (`FUN_29960`) **csak UDS-konfiguraciora** hasznalt
  (`0xFE000020/40/60/80`, a 86 bajtos blokkot a `FUN_256A0` UDS-kezelo tolti).
  A futasideju allapot **elemmel taplalt RAM-ban** el (allando +12 V, C228B-26 / F71),
  ezert nem kell NVM-irast hozzaadni — eleg az ebredeskori nullazast megvaltoztatni.
- Teljesitmeny/LED oldal: `FUN_503B4` (futes), `FUN_53814` (2 x 1-a-3-bol szintjelzo),
  `FUN_5391A`/`FUN_5397C` (NTC aranymeres, ADC 23 ref / 21 / 20).

### 11.4 Auto-recirkulacio
- Nyomvonal: **`FUN_40B5A` @`0x40BF8`** — AUTO-ra (mode 9) es a 2/4 modokra againzo
  logika, eredmenye `gp-28657`. Innen kell tovabbmenni.

---

### Uj altalanos eredmenyek ebben a menetben
- **`FUN_4B3E0`** = univerzalis **kalibracios gorbe-kiertekelo**, 86 hivohellyel.
  Az aktiv valtozat-blokk mutatoja `gp-30076`.
- **`CAL_BLOKK_TERKEP.txt`** — a 0x9E0 bajtos valtozat-kalibracios blokk **teljes
  terkepe**: 602 offset, mindegyikhez a hasznalo modul. Ez a hangolas alaptérkepe.
- **`FUN_44464` = a fuvo (blower) vezerloje**, 0..100 %-ra vagva (`0x451C0`),
  sajat AUTO-againzassal. Ez az AUTO fuvokarakterisztika gazdaja.
- **`FUN_45264`** = `gp-29040`, a kozponti igenyertek, **146 olvasoval**.
- **`FUN_4B29E`** = kimenet-publikalo rampa (sebessegkorlatozo), amit az osszes
  vegrehajto-vezerlo hasznal.
- **`FUN_2962C`/`FUN_29ADA`** = cim-alapu adat-pool (regiodeszkriptorok `0xC02C`),
  ezert a modulok kozti adataramlas nem latszik egyszeru gp-relativ olvasaskent.

---

## 12. A kalibracios gorbek formatuma — DEKODOLVA  **[B]**

`FUN_4B3E0(tabla, x, irany)` toresspontos interpolacio. A tabla formatuma:

```
u16  n                 ; toresspontok szama
n x (u16 x, u16 y)     ; noveko x szerint rendezve, elojeles 16 bit
```
`irany = 0` -> normal (x -> y), `irany = 1` -> **forditott keresés** (y -> x).
Ha `x` az elso toresspont alatt van, az elso `y`-t adja vissza.

Ellenorizve: a `FUN_3A37A` kilenc gorbeje pontosan lancolodik
(`0x2E8 -> 0x2F6 -> 0x310 -> 0x32A -> 0x350 -> 0x36A -> 0x378 -> 0x38A -> 0x39C -> 0x3AA -> 0x3B8`),
minden tabla vege pontosan a kovetkezo kezdete. Ez igazolja a formatumot.

Pelda (C346 blokk, bazis `0x0F6BA`):

| offset | n | toresspontok (x, y) |
|---|---|---|
| `0x378` | 4 | (0,28) (80,38) (160,60) (260,89) |
| `0x38A` | 4 | (-20,356) (0,296) (100,296) (132,356) |
| `0x32A` | 9 | (-120,65) (-112,65) (-100,65) (-16,65) (40,53) (48,47) … |
| `0x350` | 6 | konstans 20 |
| `0x36A` | 3 | konstans 35 |

**Pozicio-skala:** az ajtoparancs bajtban **0…89**, a rampa elott `<< 2`-vel
skalazva **0…356**-ra. A `0x378` gorbe maximuma pontosan 89 — vagyis az
ajtopozicio-gorbek bajt-tartomanyban vannak, a `0x2F6`/`0x310`/`0x38A` gorbek
mar a ×4-es tartomanyban (356 = teljes kiteres).

**Hataroló konstansok** (`FUN_3A37A`, harmadik kimenet):
`cal[518] = 89` (felso vagas), `cal[519] = 20` (also vagas) — vagyis ez az ajto
sosem zar teljesen, 20…89 kozott mozog.

A valtozatok kozti kulonbseg pl. `cal[514]`: C346 = 20, **C346NA = 50**,
C346FAP = 20; es `cal[531]`: C346/FAP = 77, C346NA = 65. Vagyis az eszak-amerikai
kalibracio itt erdemben mas — ez jo kiindulas a hangolashoz.

---

## 13. A legelosztas-vezerlo belso terkepe  **[B]**

> Fontos javitas: a `0x3A37A` **nem** a nagy vezerlo, hanem egy 2 utasitasos getter.
> A nagy fuggveny utana kezdodik (`0x3A380`, a feladatlistaban is igy szerepel).
> A korabbi „FUN_3A37A = 2085 utasitas" a ket fuggveny osszevonasabol adodott.

### Negy publikalt bajt, sajat getterrel
| Getter | Valtozo | Mi ez |
|---|---|---|
| `FUN_3A368` | `gp-28686` | allapot/minoseg fuggo ertek |
| `FUN_3A36E` | `gp-28685` | statusz (3-mal hasonlitgatjak) |
| `FUN_3A374` | `gp-28684` | `cal[537]`/`cal[538]` = 89 — felso hatar |
| **`FUN_3A37A`** | **`gp-28683`** | **egy mod-ajto tenyleges poziciója, bajtban (0…89)** |

`gp-28683` a `gp-31722` rampazott kimenet visszaskalazva (`>>2`), illetve kozvetlenul
`gp-26377` — ugyanaz az ajto celertek/tenyertek parban. Tartomanya `cal[519]=20` …
`cal[518]=89` koze vagva (sosem zar teljesen).
**Ez az ertek CAN-on is kimegy** (`FUN_39838` @`0x39930`, `FUN_396A6`/`FUN_3981A` pakolja).

### Gorbe -> valtozo hozzarendeles a vezerlon belul
| cal offset | eredmeny | bemenet |
|---|---|---|
| `0x2E8` (744) | `sp[170]` | `FUN_4997E()` |
| `0x2F6` (758) | `sp[176]` | **`FUN_45264()` = igenyertek** |
| `0x310` (784) | `sp[178]` | `FUN_45264()` |
| `0x32A` (810) | `sp[180]` | |
| `0x350` (848) | `r25` | |
| `0x36A` (874) | `sp[172]` | `FUN_45264()` |
| `0x378` (888) | `sp[182]` | `FUN_3E630()` |
| `0x38A` (906) | `gp-26384` | `FUN_4AE3E()` |
| `0x39C` (924) | `sp[168]` | |

A `0x378` gorbe **monoton 28 -> 89** a bemenet 0…260 tartomanyaban, ami pontosan
beleesik a harmadik kimenet `20…89`-es vagasaba — ez a klasszikus
panel -> ketszintu -> padlo menetrend alakja. **[E]** (nem bizonyitott, lasd lent)

### Kesz mintak, amiket a patch ujrahasznalhat
`FUN_41646` @`0x42310` **mar most is kuszoboz** ezen az ajtopozicion, hiszterezissel:
`cal[607] = 63` (felso) / `cal[608] = 70` (also) -> `gp-31308` boolean, amivel ket
kalibracios tabla kozul valaszt. Vagyis a „hol jar az ajto" kerdes eldontesere
letezo, kalibralt minta van a firmware-ben — a patch ugyanezt a szerkezetet masolhatja.

### AZ EGYETLEN NYITOTT TETEL
Melyik fizikai ajto a `gp-28683`: a **PANEL/FLOOR** vagy a **DEFROST**?
- Mellette (PANEL/FLOOR): a `0x378` gorbe alakja; `FUN_41646` a poziciobol valaszt
  hőmodellt (a padlo/panel ut termikusan kulonbozik); `FUN_47CDC` a `89 - pozicio`
  mennyiseget hasznalja (= „mennyire panel fele").
- Ellene: nem bizonyitott, a masik ket kimenet meg nincs beazonositva.

Eldontesi lehetosegek koltseg szerint:
1. **CAN-sniff** — `gp-28683` kimegy a buszra; kezi modvaltasnal a valtozasabol
   azonnal latszik, melyik ajto. Nulla kockazat, percek.
2. **UDS PID** — ha ki van vezetve, allo autoban leolvashato.
3. **Statikus** — a `0x3A380`-tol indulo vezerlo teljes atolvasasa (~2000 utasitas).
   Ez a jarhato ut, ha nincs auto — de nagy blokk.

---

## 14. A harom legelosztas-kimenet beazonositva  **[B/E]**

A `0x3A380`-tol indulo vezerlo harom kimenete, a cel-lancokkal:

| | cel-lanc | rampazott | bajt-alak | mi ez |
|---|---|---|---|---|
| **A** | `sp[11] -> sp[21] -> gp-31744 -> sp[8]` | `gp-31726` | **`gp-31727`** (`0x3BD4E`) | **PANEL/FLOOR ajto** [E] |
| **B** | `sp[46] x sp[170] / 100 -> sp[76]` | `gp-31724` | — | C346-ban **inaktiv** [B] |
| **C** | `sp[3] -> sp[2] -> sp[16] -> sp[25] -> gp-26377` | `gp-31722` | **`gp-28683`** (getter `FUN_3A37A`) | **DEFROST ajto** [B] |

### C = szelvedo-ajto — bizonyitas
- Normal uzemben `sp[2] = min(sp[3], sp[172])`, ahol `sp[172]` a `0x36A` gorbe
  eredmenye = **konstans 35**. Vagyis az ajto **max ~35 %-ra** nyit.
- `mode == 8` (szelvedo) eseten viszont `sp[2] = max(sp[3], cal[514])` —
  **also korlat, felso vagas nelkul**, tehat 100 %-ig nyithat.
- `cal[514]`: C346 (EU) = **20**, C346NA (Eszak-Amerika) = **50**. Az NA kalibracio
  nagyobb minimum szelvedo-aramlast ir elo — pontosan az, amit egy szelvedo-ajtotol varunk.
- A vegso ertek `cal[519]=20` … `cal[518]=89` koze vagva: **sosem zar teljesen**
  (allando parasodas-gatlo elszivas).

### B inaktiv C346-on
A B kimenet celertekehez a `0x2E8` gorbe kell, ami a C346 blokkban **vegig 0**
((-80,0) (40,0) (60,0)). Tehat ez a valtozat nem hasznalja — valoszinuleg egy
masik karosszeriavaltozat kiegeszito ajtaja.

### A = panel/padlo — meg nem teljesen zart
Kizarasos alapon A a panel/padlo ajto, es van kesz bajt-alakja (`gp-31727`).
Ami hianyzik: **a polaritas** (magasabb ertek = panel vagy padlo?) es a
kuszobertekek. A jelenlegi nyom: `sp[11] = min(gp-26384>>2, gp-26378)`, ahol
`gp-26384` a `0x38A` gorbe (U-alak: 89 → 74 → 74 → 89), `mode == 1` (fej) eseten
pedig `cal[531] = 77`-re vagva. Ez tovabbi egy korot igenyel.

**Amit ebbol mar most lehet:** a **szelvedo-LED** vezerelheto — `gp-28683 > ~35`
kuszobbel. A fej/lab par a polaritas tisztazasa utan johet.

---

## 15. Ulesfutes-memoria (3. tetel) — a patch-pont pontositva  **[B]**

**Javitas a korabbi allapothoz kepest:** nem eleg az ebredeskori nullazast kivenni.

A tenyleges mechanizmus:
1. `FUN_534DE` (`0x534FE`, `0x53502`) nullazza a szinteket — de ez az **OS-inditasi
   init**, ami csak akkumulator-rakotesnel fut, nem minden gyujtasnal.
2. A **futasideju kapuzas** a bunos: a taszk `0x53616`-tol
   `if !(FUN_2693C()) || FUN_26952() || !FUN_53B36() -> r29 = r28 = 0` (`0x5362E`),
   majd ezt a nullat **vissza is irja a tarolora** `0x537FA` / `0x537FE`.
   - `FUN_2693C()` = `gp-27081 >= 2` (rendszer jar)
   - `FUN_26952()` = `gp-27081 == 3`
   - `FUN_53B36()` = van-e futott ules (konfiguracio)
   - `gp-27081` = **tapallapot / gyujtas**

**A javitas elve:** szet kell valasztani a *kimenetet* a *tarolt szinttol* — a
kapuzott nulla csak a kimenetre (`FUN_53814` LED, `FUN_53A7E`/`FUN_53AC2` futes)
vonatkozzon, a `0x537FA`/`0x537FE` tarolas viszont a kapuzas elotti erteket irja.
Szukseges: 2 tartalek RAM bajt + ~6 utasitas, trambulinnal.

**Megfontolando:** a Ford szandekosan nem jegyzi meg. Ha minden gyujtasra
visszakapcsol, az nyari napon nem kellemes. **Jobb terv (2+3 osszevonva):**
visszaallitas csak akkor, ha a kulso homerseklet egy kuszob alatt van — ez egyben
a 2. tetel (automatikus bekapcsolas hideg induláskor) is. Ehhez a CAN-rol jovo
kulso homerseklet kell, ami a modulban rendelkezesre all.

---

## 16. ELO CAN-MERES — a 7. szakasz nyitott kerdese lezarva (2026-08-24)

Reszletes dokumentum: `C:\UCDS_v3\canbus_re\HVAC_CAN.md`

* A modul TX ID-i a firmware-bol (`0xAAEC`, `ID = LE16 >> 2`):
  **0x73B, 0x6B0, 0x503, 0x2F0, 0x1B8, 0x190, 0x180** — a `FUN_4CC42` altal toltott
  `0xFEDFC814` puffer a **0x190** ID-hez tartozik (MS-CAN). Mind az ot periodikus
  TX ID megtalalhato az MS-CAN logokban.
* A `0xA94C`-tol indulo 32 elemu tabla mind **RX szuro** (tartalmazza a 0x7DF/0x733
  diag kereseket, es egyetlen TX ID-t sem) — a "9 TX + 23 RX" felosztas pontositando.
* `3/11 0x190` dekodolva: B4 = rendszerallapot (bit0 = AUTO), B5 = `gp-30695`
  iranybitmezo, B6/B7 = homerseklet-alapjel 0,5 fok/bit (bal/jobb zona).
* **A valasz a 7. szakasz kerdesere: NEM.** AUTO-ban (`B4` bit0 = 1) a harom iranybit
  **nulla** (`B5` = 0xF2); manualis fej-fuvasban (`B4` bit0 = 0) bit0 = 1 (`B5` = 0x43).
  Ez nem mond ellent a kodnak: AUTO-ban a `mode` maga 9, es a 9 egyik feltetelhalmazban
  sincs benne, ezert mindharom bit 0.
* **Kovetkezmeny a munkacsomagra:** a javitas helye **ez a modul**, nem az APIM/IPC.
  A `FUN_4CC42` `mode == 9` againal kell a harom iranybitet a tenyleges ajtopoziciobol
  szarmaztatni — a 13-14. szakasz mar megadja az ehhez szukseges elemeket.

---

## 17. A 13-14. szakasz KORREKCIÓJA — az „A kimenet" nem ajtó (2026-08-25)  **[B]**

A 14. szakasz nyitott tétele („melyik fizikai ajtó az A kimenet és milyen
polaritással") **rosszul volt föltéve**. A `0x3A380` vezérlő végigolvasása után:

### A három „kimenet" valójában egyetlen lánc három állomása

| lépés | cím | mit csinál |
|---|---|---|
| A rámpázott | `0x3B5A8` / `0x3B5CC` | `gp-31726` |
| → százalék | `0x3B634`, `0x3B66C` | `sp[4]` = `gp-31726 >> 2`, 0…100-ra vágva |
| → korrekció | `0x3B6AA`-`0x3B6E6` | `gp-31743` = `sp[4]` − (`sp[44]`×`sp[45]`/100) |
| B belép | `0x3B7EE` → `0x3B80A` | `gp-31724`-ből vont korrekció, ha `FUN_4AB78()==1` |
| → `sp[3]` | `0x3B856` | |
| → `sp[2]` | `0x3B8A2`…`0x3B93E` | mode 3 / mode 8 / normál ág |
| → `sp[19]` → `sp[16]` → `sp[25]` | `0x3B96A`…`0x3BA70` | `cal[546]`, `cal[527]`, `cal[518]` |
| **kimenet** | `0x3BA88` / `0x3BA96` | **`gp-26377`** = `max(sp[25], cal[519]=20)` |

Vagyis **`gp-31726` (A) és `gp-31724` (B) bemenetei a `gp-26377`/`gp-28683`
számításának, nem önálló ajtóparancsok.** Grep-pel ellenőrizve: `gp-31726`,
`gp-31724`, `gp-31727` egyetlen olvasója sincs a `0x3A380`…`0x3BD6C` tartományon
kívül. A `0x3BD28`-tól induló „publikáló" blokk (`gp-31746/31754/31756/31762/31727`)
**előző-ciklus-pillanatkép**, amit a következő körben a rámpa-ráta kiválasztása
(`0x3B514`, `0x3B53C`, `0x3BBB6`, `0x3B124`, `0x3B7E4`, `0x3A678`) olvas vissza.

**Következmény: a `0x3A380` vezérlőnek EGYETLEN külső kimenete van** —
`gp-26377` → `gp-28683` (getter `FUN_3A37A`, 14 olvasó). A 14. szakasz „A =
PANEL/FLOOR ajtó [E]" sora **törlendő**; a „C = szélvédő-ajtó" viszont áll
(a mode 8 / `cal[514]` NA=50 érvelés változatlan).

**Ami ebből következik a munkacsomagra:** a fej/láb ajtó pozíciója **nem itt**
keletkezik. A `0x4AB54` mode-getter hívásait az egész image-en megszámolva
egyetlen függvény sem képez le mode → diszkrét elosztás-pozíciót. A négy
léptető pozíciókövetője `gp-29104/29102/29100/29098` + állapot
`gp-28672…28669` (négy szimmetrikus homing-állapotgép: `0x3EA94`, `0x3EB92`,
`0x3EC90`, `0x3ED94`), és **egyik sem olvassa `gp-28683`-at** — a célértékeik
forrása még nincs meg. Ez a következő kör feladata.

### Maradék bizonytalanság  **[E]**
A `FUN_2962C`/`FUN_29ADA` cím-alapú adat-pool (régiódeszkriptorok `0xC02C`)
elvileg olvashatná a `gp-317xx` blokkot nyers címmel, gp-relatív hivatkozás
nélkül. Ezt nem zártam ki. Ha valaha ellentmondás adódik, itt kell keresni.

---

## 18. A mode ENUM ÉS A CAN-BITEK TELJES LEKÉPEZÉSE — `FUN_4CC42`  **[B]**

A `0x190` üzenet csomagolója (`0x4CD1E`…`0x4CDDA`), `r29 = FUN_4AB54()` = mode:

| cél | cím (set/clr) | feltétel |
|---|---|---|
| `gp-30697` bit3 | `0x4CD1E` / `0x4CD26` | `mode != 0` |
| `gp-30696` bit0 | `0x4CD32` / `0x4CD3C` | **`mode == 9` → AUTO** |
| **`gp-30695` bit0** | **`0x4CD58` / `0x4CD5E`** | **`mode ∈ {1,4,6,7}` → PANEL (fej)** |
| `gp-30695` bit1 | `0x4CD62` | mindig 1 |
| **`gp-30695` bit2** | **`0x4CD7E` / `0x4CD84`** | **`mode ∈ {2,4,5,7}` → FLOOR (láb)** |
| **`gp-30695` bit3** | **`0x4CDA4` / `0x4CDAA`** | **`mode ∈ {3,5,6,7,8}` → DEFROST** |
| `gp-30696` bit1 | `0x4CDB6` / `0x4CDC0` | `mode == 3` |
| `gp-30700` bit6 | `0x4CDCC` / `0x4CDD6` | `mode == 10` |
| `gp-30697` bit2 | `0x4CDE2`-`0x4CDF2` | `FUN_4AC00()!=0 && !(FUN_4AC00()==6 && FUN_40B54()==0)` |

Ebből a **mode értékkészlete visszafejtve** (a három iránybit kombinációja):

| mode | panel | floor | defrost | jelentés |
|---|---|---|---|---|
| 1 | ✓ | | | fej |
| 2 | | ✓ | | láb |
| 3 | | | ✓ | szélvédő (+ `gp-30696` bit1) |
| 4 | ✓ | ✓ | | fej + láb |
| 5 | | ✓ | ✓ | láb + szélvédő |
| 6 | ✓ | | ✓ | fej + szélvédő |
| 7 | ✓ | ✓ | ✓ | mindhárom |
| 8 | | | ✓ | MAX DEFROST |
| 9 | | | | **AUTO** (`gp-30696` bit0) |
| 10 | | | | `gp-30700` bit6 |

Ez pontosan egyezik a 16. szakasz élő logjával: manuális fej `B5 = 0x43`
(bit0+bit1+bit6), AUTO `B5 = 0xF2` (bit1 + a felső nibble).

### A PATCH PONTOS HELYE
A `mode == 9` ág mindhárom iránybitet nullázza (`clr1` a `0x4CD5E`, `0x4CD84`,
`0x4CDAA` címeken). A javításnak **ezt a három `set1`/`clr1` párt** kell
felülírnia egy hívással, ami `mode == 9` esetén a tényleges ajtópozícióból
származtat. A `gp-30695` **bit3 (szélvédő) már most származtatható**
`gp-28683 > ~35` küszöbbel — ez bizonyított jel. A bit0/bit2 a fej/láb ajtó
célértékének megtalálásáig nem képezhető.

---

## 19. Új eszköz és formátum-kiegészítések

### `tools/cal.py` — változat-kalibrációs blokk olvasó
```
python tools/cal.py curve <offset> [valtozat ...]   # FUN_4B3E0 u16 toresspontok
python tools/cal.py byte  <offset> ...              # bajt cal minden valtozatban
python tools/cal.py word  <offset> ...              # u16 cal
```
- **A blokk bázisa = a változatnév string címe − 1** (`C346` @`0xF6BB` → bázis `0xF6BA`).
- **A kalibráció little-endian** (V850). A 12. szakasz példái helyesek, de ez a
  formátumleírásból hiányzott.

### `FUN_4B2E0` / `FUN_4B360` — a MÁSIK görbe-kiértékelő
A 12. szakasz `FUN_4B3E0`-ja u16 x/y párokat használ. Mellette van egy
**bájtos** változat is:
```
FUN_4B2E0(tabla, x, irany):  u8 n, majd n x (u8 x, u8 y)
FUN_4B360(tabla, x, irany):  u16 n, majd n x (u16 x, u16 y)  -- ugyanaz mint 4B3E0
```
`irany != 0` esetén a pár sorrendje fordított (y,x) — fordított keresés.

Példa (`+2123`, mindhárom vizsgált változatban azonos) — **fúvófokozat → belső
légáram-index**: (1,30) (2,33) (3,39) (4,48) (5,61) (6,72) (7,89).

### Új azonosított getterek
| függvény | változó | jelentés |
|---|---|---|
| `FUN_4AB54` | struct byte 0 | **mode** (lásd 18. szakasz) |
| `FUN_4AB78` | struct byte 2 | 0/1/2 kérés-állapot (0 = ki) |
| `FUN_4AC00` | struct byte 3 | 0/2/4/6 leképezés |
| `FUN_4AE3E` | struct byte 4, ≤10-re vágva | **fúvófokozat** |
| `FUN_4CBE8` | `gp-30822` | **LHD/RHD (kormányoldal)** |
| `FUN_4ADBE`/`4ADDE`, `4ADFE`/`4AE1E` | `gp-28710…28713` | bal/jobb zóna MAX jelzők, LHD/RHD szerint cserélve |
| `FUN_401AE` | `gp-29080` | motorfordulat; a 301-es küszöb = „jár a motor" |
| `FUN_4AF1A` | `gp-29315==3 && gp-29314==8` | MAX DEFROST aktív |
| `FUN_3921A` | `gp-28721` | melyik kérés-struktúrát használja (`gp-29132` vagy `gp-31840`) |

### Javítás: `FUN_19EA8` / `FUN_19E52` NEM DTC
Ezek **szoftver-időzítők**: `FUN_19E52(tick, id)` indít, `FUN_19EA8(id)` lekérdez
(128 = lejárt). A tábla `gp-29912`-től, 2 bájt/időzítő (14 bit határidő + 2 flag).
A `27`, `30`, `31`, `32`, `104`, `118`, `120`, `122` konstansok időzítő-azonosítók.

---

## 20. A VÉGREHAJTÓ-ALRENDSZER TELJESEN FELTÁRVA — a mód-ajtók megvannak (2026-08-25)  **[B]**

### 20.1 Öt léptetőmotor, leíróval

`FUN_26E08`: `gp-27062 = 5` motor. Minden motorhoz **80 bájtos leíró a flashben
`0xBD8C`-től** (`FUN_2831C` másolja a `gp-30336 + 52*i` RAM-struktúrába).

Parancscsatorna: `gp-27012[i]` (u16), író `FUN_2752E(i, ertek)`, olvasó
`FUN_27544(i)`; aktuális pozíció `FUN_27554(i)`. A ciklus `0x2725C`-nél
**1:1 párosít**: `for i in 0..4: FUN_27E6A(&motor[i], cmd[i])`.
A parancs skálája **pozíció × 20** (0…100 % → 0…2000).

| motor | port / bitek | löket (`+8`) | parancs forrása | **azonosítás** |
|---|---|---|---|---|
| 0 | `FF400064` b0-3 | 1625 | `gp-29034` ∈ {49, 80, 100} | **RECIRKULÁCIÓ** — legnagyobb löket, 3 diszkrét állás **[E]** |
| 1 | `FF400064` b4-7 | 1390 | `gp-29044` (`FUN_44458`) / `FUN_49ED0` | **MÓD-AJTÓ #1** **[B]** |
| 2 | `FF400054` b8-11 | 905 | `gp-29112` (`FUN_3BF9A`) | **hőmérséklet-keverőajtó** **[B]** |
| 3 | `FF400054` b4-7 | 905 | `gp-29110` (`FUN_3BFA0`) | **hőmérséklet-keverőajtó** (2 ikerpárja) **[B]** |
| 4 | `FF400064` b8-11 | 810 | `gp-29048` (`FUN_44452`) / `FUN_49F04` | **MÓD-AJTÓ #2** **[B]** |

A **2-es és 3-as motor leírója bájtra azonos** (905/1177/634, `p72=35`, `p76=0`),
és mindkettő ugyanazon a porton szomszédos nibble-en van → ez a **dual-zone
bal/jobb keverőajtó pár**. A másik három leírója mind különböző.

`FUN_3C102`…`0x3DE8A` = **a két keverőajtó vezérlője** (két szimmetrikus fél,
LHD/RHD szerint cserélt MAX-jelzőkkel, közös `0xCF3C` globális görbével, ami a
pozíciót léptetőegységre váltja). Nem a légelosztásé.

### 20.2 A MÓD → AJTÓPOZÍCIÓ TÁBLA — `cal+2320` és `cal+2299`

`0x44BFC`: `sp[36] = FUN_4B2E0(cal+2320, mode)`
`0x44F6C`: `sp[37] = FUN_4B2E0(cal+2299, mode)`
(bájtos töréspontos táblák, x = mode)

| mode | jelentés (18. szakasz) | **ajtó#1** (cal+2320) | **ajtó#2** (cal+2299) |
|---|---|---|---|
| 0 | ki | 60 | 0 |
| 1 | fej | **21** | **40** |
| 2 | láb | **60** | **0** |
| 3 | szélvédő | 0 | 100 |
| 4 | fej+láb | **33** (NA: 45) | **0** |
| 5 | láb+szélvédő | 100 | 65 |
| 6 | fej+szélvédő | 9 | 55 (NA: 65) |
| 7 | fej+láb+szélvédő | 45 | 75 (NA: 60) |
| 8 | MAX defrost | 0 | 100 |
| 10 | — | 60 | 0 |

**mode 9 (AUTO) szándékosan hiányzik a táblából** — külön ág kezeli (lásd lent).
Mindhat változat táblája majdnem azonos; csak `mode 4/6/7` tér el EU vs NA között.

Az ajtó#1 értékkészlete `{0, 9, 21, 33, 45, 60, 100}` — és a `cal+2517` hiszterézises
kvantálótábla pontosan `[0, 9, 21, 33, 45, 52, 60]`. Ez **kereszt-igazolja a táblát**.
(A kvantálót `FUN_49F38` végzi, `FUN_49ED0`/`FUN_49F04`-ből; hogy a folytonos vagy a
detentes út fut, azt `FUN_4AAEC()` = konfigurációfüggő változatkód dönti el.)

### 20.3 Az AUTO ág — `0x44C3C` és `0x4504E`

```
ha mode == 9:
    ajto#1 (gp-31160) = cal.h[358] >> 1        ; = 116>>1 = 58  ALLANDO
        ha MAX-jelzo A: = cal[673] = 60
        ha MAX-jelzo B: = cal[671] = 17
    ajto#2 (gp-31158) = sp[12] = max(sp[11], sp[5])   ; FOLYTONOS, szamitott
        ha MAX-jelzo A: = cal[672] = 0
        ha MAX-jelzo B: = cal[670] = 10
kulonben:
    ajto#1 = tabla1[mode];  ajto#2 = tabla2[mode]
; mindket agra rakerul meg:
ha FUN_4578E()==1 && FUN_45794()>=3: ajto#1 = cal[667]=17,  ajto#2 = cal[660]=10
ha FUN_4578E()==2 && FUN_45794()>=3: ajto#1 = cal[668]=33,  ajto#2 = cal[661]=0
```
Ezután rámpa (`gp-31162`/`gp-31156`), majd `gp-29044 = clip(gp-31162, cal[669]=2 … cal[666]=98)`
és `gp-29048 = clip(gp-31156, cal[663]=5 … cal[662]=95)`.

**Ez a kulcsmegállapítás:** AUTO-ban az **ajtó#1 egy állandó, 58** (a MAX HI/LO
felülírásoktól eltekintve), és csak az **ajtó#2 változik**. A 58 a manuális
tábla `60` = **mode 2 (láb)** értékéhez van legközelebb. Ezért nincs mit
kijelezni: a firmware AUTO-ban nem választ mode-ot, csak ajtópozíciót ad ki,
és a pozíció nagyjából egy állandó „lábfúvás" beállításnak felel meg, amit az
ajtó#2 folytonos mozgása modulál.

### 20.4 EBBŐL KÖVETKEZIK A PATCH — invertálható a tábla

A javításhoz **nem kell új fizikai ismeret**: a firmware saját, manuális
mode → (ajtó#1, ajtó#2) leképezését kell **visszafelé** alkalmazni.

Patch-terv (mode 9 ágban, a `0x4CD5E` / `0x4CD84` / `0x4CDAA` `clr1`-ek helyén):
```
d1 = FUN_44458()      ; gp-29044, ajto#1 tenyleges parancs (0..100)
d2 = FUN_44452()      ; gp-29048, ajto#2 tenyleges parancs (0..100)
m* = argmin over m in {1,2,3,4,5,6,7,8} of |d1 - T1[m]| + |d2 - T2[m]|
gp-30695 bit0 = (m* in {1,4,6,7})
gp-30695 bit2 = (m* in {2,4,5,7})
gp-30695 bit3 = (m* in {3,5,6,7,8})
```
`T1`/`T2` a `cal+2320` / `cal+2299` táblákból olvasható **futásidőben**
(`FUN_4B2E0(cal+2320, m)`), tehát a patch változat-független és
kalibrációból hangolható marad. Kódméret: kb. 40-50 utasítás a szabad
flashben (`0x77E00`), plusz három trambulin-hívás.

**Előrejelzés, ami méréssel ellenőrizhető:** ezzel a származtatással AUTO-ban
alapesetben a **láb** LED gyullad ki (d1 ≈ 58 → mode 2), és ahogy az ajtó#2
nyit, átvált **fej+láb+szélvédő** (mode 7) vagy **láb+szélvédő** (mode 5) felé.
Ha a valóságban AUTO-ban hűtéskor fejre fúj, akkor az ajtó#1/ajtó#2 geometriai
szerepe fordított ahhoz képest, amit itt feltételeztem — de a **nearest-neighbour
származtatás akkor is helyes marad**, mert a firmware saját tábláját használja.

### 20.5 Mellékeredmény: a 17. szakasz „négy léptető" nyoma HIBÁS volt
A `0x3E9A8` / `0x3EAAA` / `0x3EBA8` / `0x3ECA8` állapotgépek **nem végrehajtók,
hanem az ADC-érzékelők hihetőség-ellenőrzői**. A leírótábla `0xE1F0`-tól,
7 × 20 bájt; érték `gp-29002[i]` (`FUN_4FF8E(i)`), státusz `gp-28571[i]`
(`FUN_4FFA8(i)`), nyers ADC `gp-29016[i]`:

| idx | ADC csat. | linearizáló görbe | vágás |
|---|---|---|---|
| 0-3 | 11, 13, 10, 12 | `0xCC9C` | 51…993 |
| 4-5 | 14, 15 | `0xCC7C` | 61…973 |
| 6 | 6 | `0xD0AC` | 61…993 |

A `FUN_4A500/4A534/4A568/4A59C/4A5BC/4A5DC` getterek ezekhez adnak
±400/−200-ra vágott hozzáférést; a `gp-26112` flag nem-nulla értéke a
**UDS kimenetvezérlés / szenzor-felülírás** (`gp-26136…26140`).

---

## 21. NAGY KORREKCIÓ: `gp-28683` a FÚVÓ kitöltési tényezője, nem a szélvédő-ajtó  **[B/E]**

A 14. szakasz „C = szélvedő-ajtó" azonosítása **téves**. A `0x3A380` vezérlő
**a fúvó (blower) szabályozója**, a `gp-28683` (`FUN_3A37A`) pedig a
**fúvó PWM kitöltési tényezője százalékban**.

### Bizonyítékok
1. **A fogyasztó egy PWM-csatorna.** `0x49E7C`: `if FUN_3A36E() >= 3 then
   FUN_52E9E(FUN_3A37A())`. A `FUN_52E9E` 0…100-ra vág, majd
   `FUN_2B902(18, kitoltes)` — PWM-csatorna-beállító. Nincs léptetőmotor-parancs
   a láncban (a `FUN_2752E` egyik hívása sem kapja meg).
2. **A limp-home blokk.** `0x49C4E` és `0x49CC2`: hiba esetén az öt ajtóparancs
   fix értékre megy (0→100, 1→60, 2→0, 3→0, 4→0), **és** `FUN_52E9E(48)` —
   fix 48 %-os fúvó. Ajtópozíciónak a 48 semmit nem jelentene.
3. **A fő bemenete a fúvófokozat-görbe.** `cal+2123`: fokozat 1…7 →
   30, 33, 39, 48, 61, 72, **89**. `FUN_4AB78()==2` (kézi fúvó) esetén ez az érték,
   `==0` (ki) esetén 0, `==1` (AUTO) esetén a számított AUTO-karakterisztika.
4. **A 20…89-es vágás** (`cal[519]`/`cal[518]`) = „bekapcsolva sosem áll le,
   és sosem megy 89 % fölé".
5. **A 35-ös plafon feltételes**: `FUN_4578E() >= cal[535]=2` esetén él —
   ez a **bemelegedési fúvókorlát** (hideg motorral max 35 %), nem ajtóvágás.
6. **A defrost-minimumok** (`0x3B8A2`, `0x3B8DE`): `mode 3` → min `cal[513]=64`,
   `mode 8` → min `cal[514]` = **20 (EU) / 50 (NA)**. Ez fúvó-minimumként
   olvasva pontosan az északamerikai defrost-előírás. A 14. szakasz érvelése
   tehát helyes volt, csak nem ajtónyitásra, hanem **fúvóteljesítményre**.

### Amit ez helyre tesz
- A 17. szakasz megállapítása (egyetlen külső kimenet) **változatlanul áll** —
  csak most már tudjuk, mi az a kimenet.
- A `0x3A380` kilenc kalibrációs görbéje a **fúvó-karakterisztika** hangolása.
- A `FUN_44464` / `gp-28640` a fúvó **fokozata** (0…10), a `gp-28683` a
  **kitöltése** (%). Két külön dolog, mindkettő a fúvóé.
- **A 20.4 patch-terv nem változik** — az a `gp-29044`/`gp-29048` ajtóparancsokra
  épül, nem `gp-28683`-ra. A szélvédő-LED viszont **nem** származtatható
  `gp-28683`-ból (ez a korábbi terv törlendő); a szélvédő-bit az **ajtó#2**-ből jön.

### Kereszt-ellenőrzés élő logon (nyitott)
A `HVAC_CAN.md` szerint a `0x180` `B2..B3` egy 190…380 tartományú, 5-ös lépésközű
érték, ami AUTO megnyomásakor felfut. Ha ez `gp-28683 × 4`, akkor a 20…89-es
tartomány 80…356-ot ad — nagyságrendben stimmel, de a pontos skála még nyitott.

---

## 22. A `mode 3` és `mode 8` szerepe FELCSERÉLVE a 18. szakaszhoz képest  **[E]**

Mindkettő ugyanazt az ajtópárt kéri (ajtó#1 = 0, ajtó#2 = 100), tehát a
különbség nem az ajtókban van:

| | `mode 3` | `mode 8` |
|---|---|---|
| AUTO fúvó-minimum | `cal[513]` = **64 %** | `cal[514]` = 20 (EU) / 50 (NA) |
| külön CAN-jelzőbit | **`gp-30696` bit1** | nincs |
| `gp-31628`/`gp-31619` a keverőajtó-vezérlőben | `= (mode==3)` | — |

A magasabb fúvó-minimum + a saját CAN-jelzőbit alapján **`mode 3` = MAX DEFROST**
és **`mode 8` = normál szélvédő**, nem fordítva. A 18. szakasz táblázatában ezt
így kell olvasni. (A `gp-30695` iránybitek képlete változatlan — mindkét mode a
bit3-at állítja.)

---

## 23. Bemelegedési stratégia — `FUN_4578E` / `FUN_45794`  **[B]**

`gp-28638` (= `FUN_4578E`) egy **háromállapotú indítási/bemelegedési állapotgép**
(`gp-31100` bit0/1/2, `0x45940`–`0x45A98`), ami a központi igényértéket
(`FUN_45264`) a `cal.h[386]` küszöbhöz méri, `cal.h[384]` időzítéssel (timer id 67).
`gp-28637` (= `FUN_45794`) a hozzá tartozó szint/számláló.

Hatásai:
- **Fúvókorlát**: `FUN_4578E() >= cal[535]=2` → a fúvó 35 %-ra vágva (21. szakasz).
- **Ajtófelülírás** (`0x44C7E`, `0x450AC`), ha `FUN_45794() >= 3`:
  - `FUN_4578E()==1` → ajtó#1 = `cal[667]`=17, ajtó#2 = `cal[660]`=10
  - `FUN_4578E()==2` → ajtó#1 = `cal[668]`=33, ajtó#2 = `cal[661]`=0

Ez a klasszikus „hideg indításkor ne fújjon hideget az arcba" logika, és
**felülírja az AUTO ágat is** — a patchnek ezt tiszteletben kell tartania
(a `gp-29044`/`gp-29048` végső értékből dolgozunk, ami már tartalmazza).

---

## 24. A TERMIKUS MODELL — a bemeneti oldal feltárva (2026-08-25)  **[B]**

### 24.1 NAGY KORREKCIÓ: `gp-29040` a KÜLSŐ HŐMÉRSÉKLET, nem „igényérték"

A 11. szakasz `FUN_45264` / `gp-29040` = „a központi igényérték, 146 olvasóval"
megnevezése **téves**. A `FUN_452C2` teljes átolvasása után:

**`gp-29040` = a hitelesített, lassított KÜLSŐ LEVEGŐ-HŐMÉRSÉKLET (OAT).**

A becslő lánc:
```
gp-29288 = CAN-rol kapott kulso homerseklet  (FUN_2117C, gp-30603/30604-bol,
           10 bites mezo; statusz gp-29289 2 bit; timeout timer 179 / 1250 tick)
gp-29088 = a modul SAJAT szenzora, sebesseg-fuggo onmelegedes-korrekcioval
           (FUN_3EFAE: diff = nyers - gp-29038, 0..800-ra vagva, sulyozva a
            0xDAC8 gorbevel, ami a jarmusebesseg fuggvenye: allo helyzetben
            teljes suly, nagy sebessegen 0)
gp-32534 = harmadik forras (mindig ervenyes, FUN_4AEF6 konstans 3)

FUN_452C2:
  ha mindketto ervenyes es (gp-29088 - gp-29288) >= cal.h[368]=100:
        forras=3, gp-31126 = min(gp-32534, gp-29288)      ; a szenzor tul meleg
  kulonben:
        forras=4, gp-31126 = gp-29288
  ; ha valamelyik statusz rossz -> forras 1/2, tartalek agak (cal.h[366]=60)
  gp-31128 = a kivalasztott ertek,  gp-31107 = forras-kod (1..4)
  gp-31120 = FUN_45680: gp-31128 RAMPAZVA, rata = gp-31105
             (cal[682]=2 / [683]=2 / [684]=4 / [685]=3 — no/csokken x ket feltetel)
  => gp-29040 = gp-31120        (a lassitott OAT)
     gp-29038 = gp-31128        (a nyers valasztott OAT)
     gp-28639 = gp-31107        (forras/minoseg, 29 olvaso)
```
Ez magyarázza a 146 olvasót: **minden menetrend a külső hőmérséklettől függ.**

**Egység:** az érzékelő-linearizáló görbék `0,1 °C`-ban adják az eredményt
(pl. `0xCC9C`: ADC 36 → 400 = +40,0 °C; ADC 728 → −20 = −2,0 °C).

### 24.2 Az érzékelők azonosítva

7 ADC-csatorna, leírótábla `0xE1F0` (7 × 20 bájt), linearizáló görbével:

| idx | ADC | görbe | tartomány | szűrt kimenet | státusz | **mi ez** |
|---|---|---|---|---|---|---|
| 0 | 11 | `0xCC9C` | +40,0 … −2,0 °C | `gp-29102` | `gp-28671` | NTC (belső tér / kifúvás) |
| 1 | 13 | `0xCC9C` | ugyanaz | `gp-29098` | `gp-28669` | NTC |
| 2 | 10 | `0xCC9C` | ugyanaz | `gp-29104` | `gp-28672` | NTC |
| 3 | 12 | `0xCC9C` | ugyanaz | `gp-29100` | `gp-28670` | NTC |
| 4 | 14 | `0xCC7C` | 25,0 … 0,0 lineáris | `gp-29108` (`FUN_3E630`) | `gp-28676` | **napszenzor** (bal) **[E]** |
| 5 | 15 | `0xCC7C` | ugyanaz | `gp-29106` (`FUN_3E636`) | | **napszenzor** (jobb) **[E]** |
| 6 | 6 | `0xD0AC` | +20,0 … −6,0 °C | `gp-29088` (`FUN_3EEDE`) | `gp-28668` | **külső hőmérséklet-szenzor** |

A négy azonos NTC (idx 0-3) a **négy azonos görbe** miatt egy csoport: belső tér
és/vagy kifúvási hőmérsékletek, bal/jobb. A pontos szereposztás még nyitott.

### 24.3 Az alapjel (setpoint) útja  **[B]**

```
FUN_4AD32 / FUN_4ACA6   = a kerestruktura 47. / 46. bajtja  (LHD/RHD szerint cserelve)
                          ertekkeszlet 30..60;  < 30 = LO,  >= 61 = HI
                          => 0,5 °C/lepes, 15,0 … 30,0 °C
gp-29018 = FUN_4AD32()   (nyers alapjel, A oldal)
gp-29020 = FUN_4ACA6()   (nyers alapjel, B oldal)
gp-29022 = gorbe(0xD01C, FUN_4AD32()) + gp-30860 + korrekcio
gp-29024 = gorbe(0xD01C, FUN_4ACA6()) + gp-30862 + korrekcio
           ahol korrekcio = gp-30882, ha az OAT-forras minosege >= 3
```
`0xD01C`: (62,42) (64,50) (68,67) (76,86) (100,122) (108,141) (112,158) (118,189)
— a tárcsaérték kétszerese → belső hőmérséklet-skála, **enyhén progresszív**
(a szélek felé nagyobb lépés).

**Ez zárja le a MAX HI / MAX LO jelzők kérdését:** `FUN_4ADBE`/`FUN_4ADDE` = LO
(a tárcsa alsó véghelyzete), `FUN_4ADFE`/`FUN_4AE1E` = HI. Ezért megy a
keverőajtó 0-ra ill. 255-re (21. szakasz, `0x3FE54` / `0x3FE68`).

### 24.4 A keverőajtó-igény képlete — a váz  **[B/E]**

`FUN_3F2xx` (a `0x3FE84`/`0x40050`-nél záruló két szimmetrikus fél) egy
**lineáris, súlyozott összeg**, a klasszikus DEATC-modell:

```
r29  =  ((sp[60] << 2) - sp[78]) >> 4
      +  sp[80] >> 2
      +  sp[28] >> 2
      + ((gp-29022 - (r22 >> 2)) * cal.b[569]=32) >> 2
gp-31444 = r29 >> 2
gp-28663 = gp-31444        ; LO -> 0,  HI -> 255
```
| tag | képlete | jelentés |
|---|---|---|
| `sp[78]` | `(cal[574 v. 577]=10 × 41/64) × min(sp[82], cal[584]=255)` = `6 × …` | veszteség-/terheléstag **[E]** |
| `sp[80]` | `gp-29026 × cal.b[578]=4` | `gp-29026` = egy görbe-eredmény × előjeles tényező (`0x49560`) |
| `sp[28]` | `(gorbe(cal+1156, r24>>6) × r24) >> 6`, ±4080-ra vágva | **napterhelés-tag** (`r24` a két napszenzorból) |
| utolsó | `(alapjel − (alapjel+eltolás)/2) × 32 / 4` | **alapjel-hiba tag** |

A `cal.b[569] = 32` a fő **arányos erősítés**. A többi együttható a `cal[574…584]`
sávban, mind kalibrációból hangolható.

**Ami még nyitott ebben:** `sp[60]`, `sp[82]`, `r22` és `r24` pontos származása
(a `0x3F2D8`–`0x3FCF0` közti ~1500 utasítás), azaz melyik NTC a belső tér és
melyik a kifúvás, és hol lép be a fúvó- ill. recirkuláció-függés.

---

## 25. A KEVERŐAJTÓ-MODELL — a szabályozó egyenlete  **[B]**

Függvény: `0x3F2CE` … `0x4005C` (1203 utasítás, két szimmetrikus fél egy testben).
Kimenetei: `gp-28663` (A oldal, `0x3FE84`) és `gp-28664` (B oldal, `0x40050`),
0…255 skálán, ezek mennek a `FUN_3C102` léptető-vezérlőbe.

### 25.1 A fixpontos százalék-idióma
A kód végig ezt használja: `(pct × 41) >> 6`, majd később `>> 6`.
`41/64 = 0,640625`, és `0,640625/64 = 1/99,9` — vagyis ez egy
**× pct/100 fixpontos szorzás**. Ez a minta öt helyen fordul elő
(`cal[573]`, `cal[574]`, `cal[577]`, `cal[578]`, `cal[580]`), mindenütt
százalék-súlyozást jelent.

### 25.2 Az alapegyenlet — oldalanként

```
OAT   = sp[14]  = FUN_40C38() ? gp-31442 (tartott ertek) : FUN_45264()
f108  = gorbe(cal+1146, OAT)          ; alapszint
f104  = gorbe(cal+1114, OAT)          ; napterheles-sulyt ado gorbe
f106  = gorbe(cal+1132, OAT)          ; alapjel-elteres erositese
nap_B = FUN_47600() = gp-28618        ; napterheles, B oldal
nap_A = FUN_4760C() = gp-28616        ; napterheles, A oldal
Tset_B= FUN_495EC() = gp-29024        ; effektiv alapjel, B
Tset_A= FUN_495F2() = gp-29022        ; effektiv alapjel, A

nap_tag   = clip( nap × f104 × 655 >> 12 , ±4080 )      ; 655/4096 = 1/6,25
set_tag   = clip( f106 × (Tset - cal.h[174]=98) , ±4080 )

sp[30] (B) = (f108 << 2) - nap_tag_B + set_tag_B + (cal[579] << 4)
sp[60] (A) = (f108 << 2) - nap_tag_A + set_tag_A + (cal[579] << 4)
```

**Ez a klasszikus DEATC cél-kifúvási-hőmérséklet egyenlet:**
alapszint(külső hő) − napterhelés×súly(külső hő) + (alapjel−referencia)×erősítés(külső hő) + eltolás.

`cal.h[174] = 98` a **belső hőmérséklet-skála referenciapontja** (a `0xD01C`
görbe kimenetének középtájéka — a 22 °C körüli „semleges" alapjel).

### 25.3 Bal-jobb kiegyenlítés
```
sp[12] = (sp[60] - sp[30]) << 3                   ; a ket oldal kulonbsege
sp[3]  = LHD ? cal[573] : (100 - cal[573])        ; oldalarany %-ban
sp[56] = (sp[30] << 2) - (pct(sp[3]) × sp[12]) >> 7
```
Vagyis a két oldal célértéke **részlegesen összekeveredik** a `cal[573]`
aránnyal — ez a dual-zone „áthallás" modellje (a bal oldali beállítás
befolyásolja a jobb oldali kifúvást is).

### 25.4 Az alapjel-változási tranziens  **[B]**
`0x49368`-tól:
```
sp[4]    = FUN_495FE() × 10 = gp-29018 (nyers tarcsaertek) × 10
gp-30892 = rampa(gp-30904, sp[4], rata = cal[738])      ; lassitott alapjel
r28      = clip(sp[4] - gp-30892, ±60)                  ; a valtozas merteke
gp-29026 = (r28 × K) >> 2,  ahol K = gorbe(cal+1984, OAT) ha r28 <= 0
                                     gorbe(cal+2002, OAT) ha r28 >  0
gp-29028 = ugyanez a masik oldalra (gp-30890 / r29)
gp-28603 = |valtozas| × 2 > cal[737] × 8   -> „nagy alapjelvaltas" jelzo
```
Vagyis a tárcsa elforgatásakor **átmeneti extra lökés** kerül a keverőajtóra,
külön erősítéssel fűtés és hűtés irányba. A modellben:
```
sp[32] = (gp-29028 × cal[580] + gp-29026 × (16 - cal[580])) >> 4   ; L/R keverek
sp[58] = sp[32] × cal[571]                                          ; erosites
```
(`cal[570]/[571]/[572]` közül `FUN_4AF16()` választ — ebben a firmware-ben
`FUN_4AF16` **konstans 1-et ad vissza**, tehát mindig `cal[571]`.)

### 25.5 A hőterhelés-modell („soak") — az indítási becslés  **[B]**
`FUN_427D4` (`0x427D4` … `0x42A2E`), kimenete **`gp-29074`** (`FUN_427A0`):

A modul **kikapcsoláskor elmenti** a `gp-32534 … gp-32514` blokkot (20 bájt,
10 × u16) — a mentés összeállítása `0x4A068`-nál látszik: `gp-29036`,
`FUN_45264()` (OAT), `FUN_3EEDE()` (saját szenzor), stb. Ezért ad
`FUN_4AEF6` **konstans 3-at** (mindig érvényes): ezek a **előző menetciklus
tárolt értékei**.

```
r24 = tarolt_belso (gp-32526) - aktualis_OAT
r25 = tarolt_belso (gp-32526) - sajat_szenzor
arany = clip( (r25 << 12) / r24 , 0 .. 4096 )     ; Q12, 0..1
```
Ez becsli, **mennyire hűlt/melegedett ki az utastér** az utolsó leállítás óta —
klasszikus soak-modell, amivel a modul indításkor tudja a belső hőmérsékletet
belső érzékelő nélkül is.

Végül:
```
gp-29074 = ( gp-26302 × cal[633] + FUN_42D7E() × (16 - cal[633]) ) >> 4
```
— súlyozott keverék a mért és a modellezett belső hőmérséklet között
(`cal[633]/16` a súly), és a súly csak akkor él, ha `FUN_4AEF6() >= 3` és
`FUN_42DA2() >= 4`.

### 25.6 A szabályozási hiba
```
r22       = (gp-29024 + gp-29022) << 1        ; a ket effektiv alapjel osszege ×2
sp[62]    = FUN_427A0() = gp-29074            ; a becsult belso homerseklet
gp-26338  = (r22 << 4) - sp[62]               ; A SZABALYOZASI HIBA
sp[100]   = gorbe(cal+1266, OAT)              ; a hiba OAT-fuggo erositese
sp[76]    = |gp-29028|,  osszevetve cal[581] × 4  -> „nagy elteres" ag
```

### 25.7 Mi maradt ebben a blokkban
`0x3F6B8` … `0x3FCF0` (~600 utasítás): a hibából a végső korrekció
(integrátor/hiszterézis, a „nagy eltérés" ág), és `sp[82]` (a `0x3FCF0`-nál
`cal[584]=255`-re vágott terheléstag) származása. A váz megvan, a
finomhangoló ág nincs átolvasva.

### 25.8 Új azonosítások ebből a menetből
| jel | getter | jelentés |
|---|---|---|
| `gp-28618` / `gp-28616` | `FUN_47600` / `FUN_4760C` | **napterhelés** B / A oldal |
| `gp-29022` / `gp-29024` | `FUN_495F2` / `FUN_495EC` | **effektív alapjel** A / B |
| `gp-29018` / `gp-29020` | `FUN_495FE` / `FUN_495F8` | **nyers tárcsaérték** A / B |
| `gp-29026` / `gp-29028` | `FUN_49340` / `FUN_4933A` | alapjel-változási tranziens A / B |
| `gp-28603` | `FUN_49346` | „nagy alapjelváltás" jelző |
| `gp-29074` | `FUN_427A0` | **becsült belső hőmérséklet** |
| `gp-32514…32534` | `FUN_4AEC8…4AEE4` | **kikapcsoláskor mentett blokk** (soak-modell) |
| `gp-28655` / `gp-28654` | `FUN_40C38` / `FUN_40C3E` | tartás/érvényesség-kapuk a menetrendekhez |
| `cal[569…584]` | | a modell együtthatói (erősítés, súlyok, eltolás) |
| `cal+1114 / 1132 / 1146 / 1266 / 1984 / 2002` | | a modell **OAT-függő görbéi** |

### 25.9 A modell tényleges számai (C346 vs C346NA)

Görbék (C346, x = külső hőmérséklet 0,1 °C-ban):

| görbe | szerep | töréspontok |
|---|---|---|
| `cal+1146` | **alapszint** | (−120, 320) → (180, −280) — lineárisan csökkenő: −12 °C-on +320, +18 °C-on −280 |
| `cal+1132` | **alapjel-erősítés** | konstans **24** |
| `cal+1114` | **napterhelés-súly** | (−20, 0) (0, 3) (80, 3) (160, 5) — 0 °C alatt nincs napkorrekció, melegben erősebb |
| `cal+1266` | hiba-erősítés | (0, 20) (40, 20) (100, 14) (120, 12) |
| `cal+1984` | alapjel-tranziens, hűtés irányba | (−40, 2) (0, 2) (80, −3) (120, −3) |
| `cal+2002` | alapjel-tranziens, fűtés irányba | (−40, −2) (0, −1) (80, −2) (120, 1) |

Együtthatók:

| cal | C346 (EU) | C346NA | szerep |
|---|---|---|---|
| 569 | **32** | **18** | fő arányos erősítés |
| 571 | 4 | 8 | tranziens-erősítés |
| **573** | **50** | **4** | **dual-zone áthallás %** — EU-ban a két oldal erősen keveredik, NA-ban gyakorlatilag független |
| 579 | 127 | 127 | eltolás (×16) |
| 580 | 8 | 12 | L/R tranziens-keverési súly (/16) |
| 584 | 255 | 23 | terheléstag-vágás |
| 633 | 4 | 8 | mért/modellezett belső hő keverési súly (/16) |
| 737 | 255 | 0 | „nagy alapjelváltás" küszöb |
| 738 | 6 | 5 | alapjel-rámpa rátája |
| `h[174]` | 98 | 98 | a belső hőmérséklet-skála referenciapontja |

Konkrét példa (C346, OAT = 0 °C, nap = 0, alapjel 22 °C ≈ 122 belső egység):
```
alapszint = 320 - (320+280)*120/300 = 80   ->  << 2  = 320
nap_tag   = 0
set_tag   = 24 x (122 - 98) = 576
eltolas   = 127 << 4 = 2032
sp[60]    = 320 - 0 + 576 + 2032 = 2928
```

---

## 26. A KÖZPONTI KLÍMASZÁMÍTÁS TELJESEN — `FUN_3F2CE` öt kimenete  **[B]**

A `0x3F2CE` függvény nem csak a keverőajtókat számolja: **öt, azonos szerkezetű,
de külön hangolt kimenetet** ad, amiket az egész modul fogyaszt.

### 26.1 A közös váz
Minden kimenet ugyanazt a három tagot adja össze, csak más súlyokkal:
```
alap    = (celhomerseklet_oldal << 2)  -  atthallas_korrekcio
tranziens = alapjelvaltas_lokes x erosites
hiba    = korlatozott_szabalyozasi_hiba x gorbe(hiba/64)
kimenet = (alap >> 4) + (tranziens >> 2) + (hiba >> 2),  majd >> 2
          0-ra vagva ha LO,  255-re ha HI
```

### 26.2 Az öt kimenet
| változó | getter | áthallás-arány | hiba-görbe | fogyasztó |
|---|---|---|---|---|
| **`gp-28663`** | `FUN_3F296` | `cal[577]` (LHD) / `cal[574]` = **10 %** | `cal+1156` | **A oldali keverőajtó** (`FUN_3C102`) |
| **`gp-28664`** | `FUN_3F290` | ugyanaz | `cal+1156` | **B oldali keverőajtó** |
| **`gp-28665`** | `FUN_3F28A` | `cal[576]` = 50 % (EU) / 10 % (NA) | `cal+1222` + `cal+1244` | `FUN_3C102`, `FUN_444E6` (mód-ajtók, fúvó) |
| **`gp-28667`** | `FUN_3F284` | `cal[573]` (a `sp[56]` keverék) | `cal+1178` / `cal+1200` | **`FUN_3A380` (fúvó)** és `FUN_444E6` |
| `gp-28666` | — | `cal[573]` | `0xCFA8` (konstans 40) | **senki nem olvassa** — halott/diagnosztikai |

`gp-28662` (`FUN_3F29C`) ≠ ebbe a családba: az `= FUN_427A6()` = a belső
hőmérséklet-becslés **státusza**, egy ciklus késleltetéssel publikálva.

**`gp-28667` a „cél-kifúvási hőmérséklet"** — ez az, amit a fúvószabályozó
(`FUN_3A380`, `0x3B010`) és a mód-ajtó/fúvó függvény (`FUN_444E6`, `0x445A4`)
használ. `gp-28665` a mód-ajtók felé megy.

### 26.3 A szabályozási hiba és a túllövés-korlát
```
gp-26338 = gp-26336 = (Tset_A + Tset_B) x 32  -  becsult_belso_ho (gp-29074)
```
Majd oldalanként **anti-overshoot korlátozás**: ha épp nagy alapjelváltás fut
(`|tranziens| > cal[581] x 4`), a hibát `± gorbe(cal+1266, OAT) x 64`-re vágja.
Enélkül a tárcsa elcsavarásakor a szabályozó túllőne.

`cal+1266` (C346): (0, 20) (40, 20) (100, 14) (120, 12) — hidegben nagyobb
megengedett hiba, melegben kisebb.

### 26.4 A hiba-alakító görbék (x = hiba/64, y = erősítés)
| görbe | alak | kihez |
|---|---|---|
| `cal+1156` | (−48,64) (−20,60) (6,56) (12,60) (20,68) — **V-alak** | keverőajtók |
| `cal+1178` | ~52 konstans, 0-nál 56 | `gp-28667` A ág |
| `cal+1200` | (−20,40) (−6,55) (6,56) (12,44) (24,38) — **aszimmetrikus** | `gp-28667` B ág |
| `cal+1222` | 24 / 20 konstans | `gp-28665` |
| `cal+1244` | 52…56 | `gp-28665` oldalanként |
| `0xCFA8` | konstans 40 (globális) | `gp-28666` |

A V-alak a keverőajtón azt jelenti: **nagy eltérésnél erősebb, a közelében
gyengébb** hatás — lágy beállás túllövés nélkül.

### 26.5 Az áthallás-korrekció
```
sp[12]   = (celhomerseklet_A - celhomerseklet_B) << 3
gp-26332 = clip( sp[12] >> 7 , ±cal[584] )
sp[78]   = pct(cal[577] v. cal[574] = 10 %) x gp-26332
```
Ez vonódik le az egyedi keverőajtó célértékéből, és emellé jön még
`(Tset_oldal − Tset_atlag) × cal[569]` — vagyis **a dual-zone szétválás
két úton is érvényesül**: a célhőmérsékletek különbségén és az alapjelek
átlagtól való eltérésén keresztül.

`cal[584]`: EU **255** (nincs korlát), NA **23** — az észak-amerikai
kalibráció szigorúan korlátozza a két oldal áthallását.

### 26.6 Ezzel a 25. szakasz nyitott tételei lezárva
- `sp[82]` = a két oldal célérték-különbsége, `±cal[584]`-re vágva ✔
- `r22` = `(Tset_A + Tset_B) << 1` ✔
- `r24` / `r25` = a korlátozott szabályozási hiba oldalanként ✔
- `sp[60]` / `sp[30]` = a két oldal cél-kifúvási hőmérséklete ✔

---

## 27. AZ AUTO FÚVÓ-KARAKTERISZTIKA  **[B]**

A `FUN_3A380` fúvószabályozó AUTO ága (`0x3AFE2` … `0x3B0AA`):

```
r25      = gorbe(cal+848, OAT)                  ; C346: konstans 20  -> ALSO KORLAT
sp[182]  = gorbe(cal+888, napszenzor)           ; NAP-LOKES
sp[37]   = bajtgorbe(cal+2060, gp-28667)        ; A FO KARAKTERISZTIKA
sp[15]   = napszenzor_ervenyes ? max(sp[182], sp[37]) : sp[37]
sp[23]   = max(sp[15], 20)
gp-31735 = min(sp[10], sp[23])                  ; MAX HI / MAX LO eseten 89 (cal[537]/[538])
gp-28684 = gp-31735   (getter FUN_3A374)
```

### `cal+2060` — az AUTO fúvógörbe (bemenet: `gp-28667` = cél-kifúvási hőmérséklet 0…255)

| C346 | 0→**89** | 17→60 | 33→42 | 60→34 | 80→31 | 107→**30** | 130→33 | 150→37 | 180→40 | 205→52 | 255→**89** |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C346NA | 3→89 | 20→57 | 36→43 | 60→34 | 80→30 | 107→30 | 130→33 | 150→37 | 180→44 | 205→58 | 240→89 |

**U-alak**: teljes fúvás a két szélen (max hűtés és max fűtés), minimum (30 %)
a kényelmes középső tartományban (~107, ami épp a `cal.h[174]=98` semleges
referenciapont közelében van). Ez a modul teljes AUTO fúvó-karakterisztikája,
és **egyetlen kalibrációs táblából hangolható**.

### `cal+888` — napterhelés → fúvó-lökés
(0, 28) (80, 38) (160, 60) (260, 89) — a napszenzor értékével emelkedő
fúvóigény, ami a hőmérséklet-alapú igénnyel **maximummal** kombinálódik.
(A 13. szakasz ezt tévesen a központi igényértékhez kötötte — a bemenet
valójában `FUN_3E630()` = a napszenzor.)

### `cal+2123` — kézi fúvófokozat → kitöltés
fokozat 1…7 → 30, 33, 39, 48, 61, 72, 89 %. (`FUN_4AB78()==2` ág.)
Mód 1 (fej) esetén `cal[531]`-re vágva: EU 77, NA 65, C344NA 64.

### A fúvó-kérés kódolása
`FUN_4AB78()` (= a kérés-struktúra 2. bájtja, forrása a panel `gp-32083`):
- **0** = fúvó KI
- **1** = **AUTO** (a szint-mező ilyenkor 30 = szentinel, `FUN_4AE3E` 10-re vágja)
- **2** = kézi fokozat

A panel oldalán a `FUN_3772E` / `FUN_3775C` rutinok írják: `gp-32083 = 1`,
`gp-32084 = 30`. A fix presetek (`FUN_37652` stb.) `gp-32083 = 2`-t és konkrét
fél-lépésszámot (14, 12, 8, 4, 2 → 7, 6, 4, 2, 1 fokozat) írnak.

### NYITOTT ELLENTMONDÁS — `0x3B462`
```
gp-31744 = min( gp-31735 , sp[7] )
sp[7] = cal[38] = 20                                       ha !FUN_4AF1A()
      = (gorbe(cal+924, OAT<<6) x gp-31735) >> 8            ha FUN_4AF1A()   ; ~0,5-0,6 x
```
`cal[38] = 20` **mind a hat változatban**. Ha `FUN_4AF1A()` hamis, ez a
20 %-ra vágná az AUTO fúvót — ami nyilvánvalóan nem lehet a valóság.
Tehát `FUN_4AF1A()` normál üzemben **igaz** kell legyen; ekkor a végső
kitöltés ≈ 0,5–0,6 × a görbeérték, azaz kb. **20…53 %** AUTO-ban
(kézi módban 30…89 %).

`FUN_4AF1A() = (gp-29315 == 3) && (gp-29314 == 8)`, mindkettő **CAN-ról**
érkezik (`0x20EBE` / `0x20ED2`): egy 2 bites státusz (3 = érvényes, Ford-szabvány)
és egy 5 bites érték. A jel azonosítása még nyitott — a viselkedés alapján
**motorállapot / start-stop** jellegű. Ez a lánc egyetlen olyan pontja, ahol
statikusan nem tudom eldönteni a normál üzemi értéket; **egy CAN-log azonnal
lezárja** (a `0x180` `B2..B3` fúvóérték és a `gp-28683` viszonya).

---

## 28. A RECIRKULÁCIÓ — `FUN_45C92`  **[B]**

A `0x45C92` … `0x46ABC` függvény kimenete **`gp-29034`** (`FUN_45BFE`), ami a
0-ás parancscsatornán a **recirkulációs ajtóhoz** megy (`FUN_2752E(0, x*20)`,
motor 0, 1625 lépéses löket — a legnagyobb). Értékkészlete **{49, 80, 100}**
(49 ≈ friss levegő, 100 ≈ teljes recirkuláció **[E]**).

### 28.1 Első fokozat — kilenc hiszterézises komparátor
Mindegyik ugyanazzal a mintával: `magas = jel > kozep + delta`,
`alacsony = jel < kozep − delta`, reteszelt kimenettel.

| jelző | bemenet | közép / delta |
|---|---|---|
| `gp-31043` | `FUN_49984()` = `gp-28600` | `cal[704]` / `cal[705]` |
| `gp-31040` | külső hőmérséklet | `cal.h[420]` / `cal.h[422]` |
| `gp-31042` | `FUN_4B17E()` | `cal.h[402]` / `cal.h[404]` |
| `gp-31044` | `FUN_4B11A()` | `cal[697]` / `cal[698]` |
| `gp-31046` | `FUN_41640()` | `cal[701]` / `cal[702]` |
| `gp-31045` | `FUN_401AE()` = `gp-29080` | `cal.h[414]` / `cal.h[416]` |
| `gp-31047` | külső hőmérséklet | `cal.h[406]` / `cal.h[256]` |
| `gp-31048` | `FUN_3EEDE()` = saját külső szenzor | `cal.h[410]` / `cal.h[412]` |
| `gp-31041` | `FUN_3E630()` = napszenzor | `cal.h[398]` / `cal.h[400]` |

### 28.2 Második fokozat — jelöltek
Nyolc részszabály, mindegyik egy jelölt pozíciót ad (`49` / `80` / `100`),
saját feltétel- és időzítő-készlettel (timer id 78, 79, 98, 99;
`cal[690…708]`, `cal.h[408]`, `cal.h[418]`, `cal.h[424]`):
`gp-31049`, `gp-31050`, `gp-31051`, `gp-31052`, `gp-31053`, `gp-31054`,
`gp-31055`, `gp-31056`.

Ezek fedik le a klasszikus eseteket: hideg indítás, párásodás-veszély,
napterhelés, sebesség, alagút/szagszenzor-jellegű logika, valamint az
A/C-kompresszor állapota.

### 28.3 Harmadik fokozat — arbitráció (`0x469AC`)
```
r29 = max( gp-31052, gp-31053, gp-31056, gp-31054, gp-31050 )
ha  sp[32]:
      ha  !sp[23] && !sp[24] && FUN_46D80()==0 :  gp-29034 = 80
      kulonben                                 :  gp-29034 = 49
kulonben ha FUN_4AC00()==3 vagy gp-31049 != 0  :  gp-29034 = 100
kulonben ha FUN_4AC00() in {0,4,5,6}:
      ha sp[22] : gp-29034 = FUN_41646()     ; ajtopozicio-fuggo, hiszterezissel
      kulonben  : gp-29034 = r29
kulonben ha mode == 10 : 100
kulonben ha mode == 0  : 100
kulonben ha FUN_4AC00() == 1 : 49
kulonben               : 100
```
`FUN_46AC0` = a „reset" rutin: `gp-31050 = 49` + `gp-31064` bit0 beállítás
— vagyis alapállapotban **friss levegő**.

`FUN_4AC00()` = a kérés-struktúra 3. bájtja (3 bit, `gp-29129`) — a
**levegő-forrás / A-C kérés** a panelről; a `0`, `1`, `3`, `4`, `5`, `6`
értékek külön ágakat kapnak.

---

## 29. A/C KOMPRESSZOR-IGÉNY — `FUN_39DF2`  **[B]**

A `0x39DF2` … `0x3A0A4` egy **állapotgép** (állapotbitek `gp-31808` 3 bit +
`gp-31804` 2 bit, időzítő id 26), kimenete:
```
gp-31800 -> gp-28691  (FUN_39DEC)   ; A/C keres, olvassa a recirkulacio (0x4626A)
gp-31812 -> gp-29118  (FUN_39DE6)   ; << 2 skalazva
gp-28692 (FUN_39D40)                ; a CAN-ra megy (0x39944, a 0x190 csomagoloban)
gp-28693 (FUN_39D3A)                ; az A/C gomb LED-je (a panel 9 helyen olvassa)
```

Tiltó/engedélyező bemenetek (mind **CAN-ról**, motorvezérlőtől):
| getter | változó | jelentés (jellegéből) |
|---|---|---|
| `FUN_4AA14` | `gp-29299` / `gp-29300` | státusz + érték pár |
| `FUN_4A99E` | `gp-29325` / `gp-29326` | státusz + érték pár |
| `FUN_4A98C` | `gp-29312` | bináris tiltás |
| `FUN_4A8BE` | `gp-28830` | bináris tiltás |
| `FUN_4A924` | flash `0xCC08` | konfigurációs kapu |
| `FUN_4A9B6` | flash `0xCB9F` | konfigurációs blokk |

Ezek a klasszikus kompresszor-tiltások: teljes gáz, magas hűtőfolyadék-hőmérséklet,
alacsony/magas hűtőközeg-nyomás, motorindítás.

**`FUN_4A83A` és `FUN_4A83E` konstans 0-t adnak vissza** → `gp-28689` és
`gp-28690` mindig 0: két kikapcsolt (más változatra való) funkció.
Ugyanígy `FUN_4A984`, `FUN_4A988`, `FUN_4AF08` (→ `FUN_4CBEE` = konstans 0)
és `FUN_4AF16` (konstans 1) — a firmware tele van ilyen **változat-kapcsolókkal**,
amiket a fordító konstansra optimalizált. Ezek jelzik, mit tud a hardver
és mit nem ebben a kivitelben.

---

## 30. ÖSSZEFOGLALÓ — hogyan működik a modul, elejétől a végéig

### 30.1 Bemenetek
1. **7 ADC-érzékelő** (`0xE1F0` leírótábla): 4 azonos NTC (kifúvási/belső
   hőmérsékletek, bal/jobb), 2 napszenzor (bal/jobb), 1 külső hőmérséklet.
   Mindegyik: nyers ADC → linearizáló görbe → 0,1 °C → hihetőség-ellenőrző
   állapotgép → szűrt érték + státusz.
2. **CAN**: külső hőmérséklet, motorállapot, sebesség, A/C-tiltások, gyújtás.
3. **Panel** (`gp-32514` adat-pool rekord, 10 bájt, bitmezős): mód (4 bit),
   fúvó-mód (2 bit) + fokozat, két alapjel (6-6 bit, 30…60 = 15…30 °C),
   A/C- és recirkuláció-kérés. Két készlet (helyi + második forrás).
4. **Kikapcsoláskor mentett blokk** (`gp-32534…32514`): az előző menetciklus
   hőmérsékletei a soak-modellhez.

### 30.2 A számítás sorrendje
```
kulso homerseklet becsles (FUN_452C2)        -> gp-29040  [OAT]
belso homerseklet becsles + soak (FUN_427D4) -> gp-29074
alapjel feldolgozas (0x49638 kornyeke)       -> gp-29022 / gp-29024
                                             -> gp-29026 / gp-29028 (tranziens)
KOZPONTI KLIMASZAMITAS (FUN_3F2CE)           -> gp-28663/28664 (keveroajtok)
                                             -> gp-28665 (mod-ajtok fele)
                                             -> gp-28667 (cel-kifuvasi ho, a fuvonak)
fuvo (FUN_3A380)                             -> gp-28683 (PWM kitoltes)
mod-ajtok + fuvofokozat (FUN_444E6)          -> gp-29044 / gp-29048
recirkulacio (FUN_45C92)                     -> gp-29034
A/C (FUN_39DF2)                              -> gp-28691 / gp-28692 / gp-28693
keveroajto-lepteto vezerlo (FUN_3C102)       -> gp-29112 / gp-29110
parancs-pool (FUN_2752E)                     -> gp-27012[0..4]
5 lepteto meghajtas (0xBD8C leirotabla)      -> FF400054 / FF400064 portbitek
PWM (FUN_2B902, 18-as csatorna)              -> fuvo
CAN TX (FUN_4CC42 stb.)                      -> 0x190, 0x180, 0x2F0, 0x1B8, 0x503, 0x6B0, 0x73B
panel LED-ek (FUN_540AE)                     -> gomb-visszajelzes
```

### 30.3 A szabályozás lényege egy mondatban
A modul egy **külső-hőmérséklet-vezérelt előrecsatolt (feed-forward) modellt**
számol — alapszint + napterhelés + alapjel-eltérés, mind az OAT függvényében —,
és erre tesz rá egy **visszacsatolt korrekciót** a becsült belső hőmérséklet
hibájából, túllövés-korláttal. Az eredmény egy „cél-kifúvási hőmérséklet",
amiből **minden más származik**: a keverőajtók pozíciója, a fúvó kitöltése
(U-alakú görbe), a légelosztás és a recirkuláció.

### 30.4 Mi hangolható kalibrációból (flashelés nélkül nem, de patch nélkül igen)
- a teljes AUTO fúvó-karakterisztika (`cal+2060`)
- a napterhelés hatása fúvóra és hőmérsékletre (`cal+888`, `cal+1114`)
- a mód → ajtópozíció táblák (`cal+2320`, `cal+2299`)
- a dual-zone szétválás mértéke (`cal[573]`, `cal[576]`, `cal[584]`)
- a fő erősítés és az összes hiba-alakító görbe
- a recirkuláció összes küszöbe és hiszterézise
- a bemelegedési stratégia küszöbei

### 30.5 Ami még nyitott
| tétel | mi hiányzik |
|---|---|
| `FUN_4AF1A` CAN-jele | melyik jel, és mi az értéke normál üzemben (27. szakasz) |
| ~~a négy NTC szerepe~~ | **MEGOLDVA a 39.3 szakaszban** — mind a négy *kifúvási* hőmérséklet |
| ajtó-geometria | ajtó#1/ajtó#2 fizikai megfeleltetése |
| ~~belső hő modell~~ | **MEGOLDVA a 39. szakaszban** — `gp-29072` a *külső* hő, a belső becslés a `gp-29062` |
| ~~UDS / DTC réteg~~ | **§36 + §40** (a §36 DID-listája javítva a §40-ben) |
| léptető-meghajtó | homing, fázistábla, áramszabályozás (`0x27xxx`) |
| PTC / kiegészítő fűtés | nem találtam nyomát — valószínűleg nincs ebben a változatban |

---

## 31. JAVÍTÁSI LEHETŐSÉGEK KATALÓGUSA

> **A friss, bizonyíték-alapú katalógus a 45. szakaszban van** — az itteni
> lista a megértés korai szakaszában készült. A 45. szakasz megmondja azt is,
> **mihez nem szabad nyúlni**, és tartalmaz egy flashelés nélkül bekapcsolható
> alvó gyári funkciót (45.2).

### 31.1 Alvó funkciók — 2 bájtos kapcsolók  **[B]**
Konstansra optimalizált getterek (`mov N, r10 ; jmp [lp]`). Mindegyik
**egyetlen immediate átírásával** átbillenthető, és ezzel egy szunnyadó
kódág aktiválódik. (Hiányzó hardver esetén DTC-t okozhat — kísérleti terep.)

| függvény | konstans | hol / mit kapuz |
|---|---|---|
| `FUN_4A988` | 0 | A/C állapotgép `0x39E3E`: `< 3 → kihagy`. Egy **nem beépített érzékelő** ága (nyomás/párologtató). `0x40D10`-nél is. |
| `FUN_4A984` | 0 | A/C `0x39F3E` és `0x40D08` — a `cal[600]`-at használó blokk így halott |
| `FUN_4AEE0` | 0 | a **soak-modellben** (`0x4286A`, `0x42872`) két eltolás kinullázva |
| `FUN_4AEF2` | 0 | `0x43E98` — egy publikált érték helyett 0 |
| `FUN_4CBEE` | 0 | `0x3986C`: a `gp-30707` **CAN-státuszbájt 1-es bitje fixen 0** |
| `FUN_4CBF2` | 1 | `0x39888`: a `gp-30707` **2-es bitje fixen törölve** (csak `==2` állítaná) |
| `FUN_4CBF6` | 0 | `0x4DD30` |
| `FUN_4A83A` / `FUN_4A83E` | 0 | `gp-28689` / `gp-28690` mindig 0 az A/C állapotgépben |
| `FUN_4AF16` | 1 | a keverőajtó-modellben mindig `cal[571]`-et választ (`cal[570]`=6, `cal[572]`=0 helyett) |

### 31.2 Kihasználatlan számítási csatorna
`gp-28666` (`0x3F8C8`) **minden ciklusban kiszámolódik, LO/HI-ra vágva,
saját hiba-görbével — és senki nem olvassa.** Egy patch ingyen felhasználhatja
(nincs többletszámítás), pl. a LED-származtatáshoz vagy egy új funkcióhoz.

### 31.3 Léptető-leíró hangolás (flash `0xBD8C`, 5 × 80 bájt)
Löket, rámpaidők, időzítők, áram — pl. `p44 = 960`, `p52 = 400`, `cal[566]`
rámparáta. Zajos vagy lassú ajtómozgás ebből hangolható, kódmódosítás nélkül.

### 31.4 Detentes vs. folytonos mód-ajtó
`FUN_4AAEC()` → `FUN_4CC0C()` konfigurációs kód dönti el, hogy a mód-ajtók a
**folytonos** értéket kapják-e vagy a `cal+2517` (7 fokozat) / `cal+2512`
(4 fokozat) hiszterézises kvantálót. A viselkedés érezhetően más — és a
kapu egyetlen konfigurációs bájt.

### 31.5 Sebességfüggő fúvó-trimm
A jármű sebessége már be van olvasva (`FUN_4AA2C` → `FUN_395E8`) a külső
hőmérséklet-korrekcióhoz. Egy görbés fúvó-korrekció (autópályán kevesebb
fúvó a torlónyomás miatt) így **meglévő bemenetből** megvalósítható.

### 31.6 A harmadik mód-ajtó
A légelosztás „B" kimenete (`cal+0x2E8` görbe) C346-on **végig nulla** —
a szoftver tud háromlapátos elosztást, ez a karosszéria nem. Retrofit
irányba érdekes, egyébként nem.

### 31.7 Szoftveres eszközök — a „modern" út (nulla kockázat, flashelés nélkül)

1. **Kalibráció-szerkesztő** (`tools/calmap.py`): a változat-blokk teljes,
   **névvel és mértékegységgel** ellátott dekódolása (a 12., 20., 25-28.
   szakaszok alapján már ~80 % lefedett), szerkesztés, majd
   `fwcrc.py resign` + `vbf.py pack`. Ez teszi a kalibrációs hangolást
   biztonságossá és visszakövethetővé, „hex-editoros vakrepülés" helyett.

2. **A szabályozó Python-modellje** (`tools/model.py`): a 25-28. szakasz
   egyenletei egy az egyben lekódolva, a valódi kalibrációs táblákból
   táplálva. Ezzel:
   - **ellenőrizhető a megértésünk** — egy CAN-logot visszajátszva a modellnek
     ki kell adnia a logban látott fúvóértéket, ajtópozíciókat és iránybiteket;
   - **kalibrációváltozás flashelés ELŐTT kipróbálható** (model-in-the-loop);
   - a kódpatch-ek (AUTO elosztás, LED) offline validálhatók.

3. **Élő adatpanel UDS-en**: ha a DID-katalógus kiadja a belső jeleket
   (külső hő becslés, belső hő becslés, cél-kifúvási hőmérséklet, fúvó
   kitöltés, ajtópozíciók), egy PC-oldali kijelző a hangolást méréssé
   alakítja. Kockázatmentes, csak olvasás.

4. **Build-lánc** (`tools/build.py`): kalibrációs változás-leírás → aláírt,
   ellenőrzött VBF + diff-jelentés, hogy soha ne menjen ki nem validált fájl.

---

## 32. A SZABÁLYOZÓ PYTHON-MODELLJE — `tools/model.py`  **[B]**

A 24-29. szakasz egyenletei lekódolva, a **valódi kalibrációs táblákból**
táplálva (`tools/calmap.py` = betöltő + töréspontos interpolátor, ami a
`FUN_4B3E0` szemantikáját követi: lineáris interpoláció, széleken vágva).

```
python tools/model.py selftest              # végigsöprés OAT / alapjel / nap szerint
python tools/model.py point --oat 5 --set 22
python tools/model.py blowermap             # az AUTO fúvógörbe
python tools/model.py doors                 # mód -> ajtópozíció + a LED-patch szimulációja
python tools/model.py compare C346 C346NA   # két változat egymás mellett
```

### 32.1 A modell validálja a megértést
Semmit nem hangoltam bele, mégis **tankönyvi DEATC-viselkedést ad**:

| helyzet | cél-kifúvási hő | fúvó |
|---|---|---|
| OAT −20 °C, alapjel 22 °C | 216 (meleg) | 30 % |
| OAT +25 °C, alapjel 22 °C | 66 (hideg) | 20 % |
| OAT +25 °C, alapjel **LO** | 0 (max hűtés) | 53 % |
| OAT +25 °C, alapjel **HI** | 193 (max fűtés) | 53 % |
| OAT +25 °C, napterhelés 0 → 250 | 66 → 53 | 20 % → **51 %** |

A napterhelés hatása különösen meggyőző: hidegebb célérték **és** erősebb fúvó,
pontosan ahogy kell.

### 32.2 A modell LEZÁRTA a 27. szakasz nyitott kérdését  **[E → B]**
`FUN_4AF1A()`-ra a két eset:

| | MAX LO / MAX HI kitöltés | kézi 1. fokozat |
|---|---|---|
| `af1a = hamis` | **20 %** | 30 % |
| `af1a = igaz` | **53 %** | 30 % |

A hamis eset fizikai képtelenség: a MAX A/C kevesebbet fújna, mint az 1. fokozat.
**Tehát `FUN_4AF1A()` normál üzemben IGAZ**, és az AUTO fúvó tartománya
**20…53 %** (kézi módban 30…89 %). Élő logon még megerősítendő, de a
kérdés lényegében eldőlt.

### 32.3 A modell MEGCÁFOLT egy korábbi javaslatot  **[fontos]**
A 31. szakaszhoz adott ötlet — „másoljuk át az NA-értékeket a dual-zone
függetlenítéséhez (`cal[573]`, `cal[576]`, `cal[584]`)" — **HIBÁS**.

A tényleges szétválasztó paraméter a **`cal[569]`**, és ebben az EU-kalibráció
már most **erősebb**, mint az NA:

| valtozat | `cal[569]` | `cal[573]` | `cal[576]` | `cal[584]` | `cal[574]/[577]` |
|---|---|---|---|---|---|
| C346 (EU) | **32** | 50 | 50 | 255 | 10 / 10 |
| C346NA | **18** | 4 | 10 | 23 | 70 / 80 |

Mérés a modellen (bal 20 °C, jobb 24 °C, OAT 10 °C — a két keverőajtó 0…255):

| `cal[569]` | 8 | 18 (NA) | **32 (EU)** | 48 | 64 |
|---|---|---|---|---|---|
| különbség | 48 | 63 | **84** | 108 | 132 |

Az NA-értékek átmásolása tehát **csökkentené** a zónák függetlenségét.
A helyes hangolás: **`cal[569]` emelése** (32 → 48 vagy 64). A `cal[573]`
és `cal[576]` nem a keverőajtókra hat, hanem a **közös** csatornákra
(`gp-28667` fúvó, `gp-28665` mód-ajtók).

### 32.4 A modell RÁVILÁGÍTOTT a LED-patch gyengéjére
A 20.4-es nearest-neighbour származtatás szimulálva, ajtó1 = 58 (AUTO állandó):

| ajtó2 | 0 | 20 | 40 | 55 | 70 | 85 | 100 |
|---|---|---|---|---|---|---|---|
| eredmény | láb | láb | **fej** | mind3 | mind3 | mind3 | mind3 |
| távolság | 2 | 22 | 37 | 33 | 18 | 23 | 38 |

A távolságok nagyok (18…38), és az ajtó2 = 40 pont **fej**-re ugrik, ami
nem monoton. Az AUTO munkapont egyszerűen **nem esik közel a manuális
tábla pontjaihoz** — ezért a nearest-neighbour rosszul kondicionált.

**Következmény a munkacsomagra:** a LED-patch önmagában rossz eredményt adna.
Előbb az **AUTO adaptív légelosztás** patch kell (`0x44C44`, a konstans 58
helyére görbe), és utána a LED — vagy a LED-hez célzott küszöbök, nem
nearest-neighbour. **Ezt a hibát a modell találta meg, flashelés előtt.**

---

## 33. PATCH-TERV: AUTO ADAPTÍV LÉGELOSZTÁS  **[terv, modellben validálva]**

> **⚠ A 47. SZAKASZ EZT A SZAKASZT RÉSZBEN CÁFOLJA.** Az „AUTO-ban beégetett
> 58" állítás túl erős: az 58 csak egy időzített ablakban él, egyébként a
> `gp-31164` számított. **A patch flashelése előtt olvasd el a 47. szakaszt.**

### 33.1 A probléma
`0x44C44`: AUTO-ban `gp-31160 = cal.h[358] >> 1 = 58`, **állandó**, mind a hat
változatban. Emiatt a légelosztás nem alkalmazkodik, és az iránybitek/LED-ek
sem tudnak mit kijelezni.

### 33.2 A megoldás
A konstans helyére **görbe a fűtésigényből**. Bemenet: `gp-28665`
(`FUN_3F28A`) — az az érték, amit a firmware maga küld a mód-ajtók felé.
Üzemi tartománya mérve **0…255**, monoton a fűtésigénnyel.

A görbe töréspontjai a **firmware SAJÁT manuális táblájának** (`cal+2320`)
értékei:

```
(0, 21)  (80, 21)  (110, 33)  (160, 60)  (255, 60)
   fej      fej      fej+lab      lab        lab
```

**Ezért nem lehet fordítva.** Nem feltételezek semmit az ajtó fizikai
geometriájáról: a patch pontosan azokat a pozíciókat állítja be, amiket a
modul a mode 1 / mode 4 / mode 2 gombnyomásra maga is beállít. Az ajtó-
geometria nyitott kérdése ezt a patchet **nem érinti**.

### 33.3 Modellben mért eredmény (`python tools/model.py patch`)

| OAT | `gp-28665` | ajtó1 ma | ajtó1 új | LED ma | LED új |
|---|---|---|---|---|---|
| +35…+20 °C | 66 | 58 | **21** | -L- | **F--** (fej) |
| +15 °C | 81 | 58 | 21 | -L- | F-- |
| +10 °C | 106 | 58 | **31** | -L- | **FL-** (fej+láb) |
| +5 °C | 131 | 58 | 44 | -L- | FL- |
| 0 °C | 156 | 58 | **57** | -L- | **-L-** (láb) |
| −10 °C | 206 | 58 | 60 | -L- | -L- |

Az alapjelre is reagál: +25 °C-on 18 °C alapjellel **fej**, 26 °C-tal **fej+láb**.

### 33.4 A LED-származtatás (a 20.4 nearest-neighbour HELYETT)
A modell megmutatta, hogy a nearest-neighbour rosszul kondicionált (32.4).
Helyette **küszöbök**, a manuális tábla szomszédos értékeinek felezőpontjain:
```
fej      = ajto1 <= 46          ; (33+60)/2
lab      = ajto1 >= 27          ; (21+33)/2
szelvedo = ajto2 >= 48          ; a mode 1 ajto2 = 40 meg NEM, a mode 6 = 55 mar igen
```
A fej és a láb tartomány **szándékosan átfed** 27…46 között: ez a kétszintű
(fej+láb) fúvás, ahol mindkét LED világít.

### 33.5 Byte-szintű megvalósíthatóság — ELLENŐRIZVE
```
0x44C44   E4 0F 45 86   ld.hu -31164[gp], r1     (4 bajt)
0x44C48   64 0F 48 86   st.h  r1, -31160[gp]     (4 bajt)
```
Helyette:
```
0x44C44   jarl 0x77E00, lp                       (4 bajt)
0x44C48   64 57 48 86   st.h  r10, -31160[gp]    (4 bajt)   <- csak a regiszter-mezo valtozik
```
**Pontosan 8 bájt, helyben elfér — nem kell trambulin.**
(`st.h r1` = `0x0F64`; a reg2-mezot 1-rol 10-re allitva `0x5764` = `64 57`.)

Az új rutin a szabad flashben (`0x77E00`-tol, végig `FF`, ellenőrizve):
```
0x77E00   80 07 21 00   prepare 0, 0x0010        ; masolva FUN_4B0EA-bol
0x77E04   jarl 0x3F28A, lp                       ; r10 = gp-28665
0x77E08   mov r10, r7
0x77E0A   mov 0x00077E40, r6                     ; a gorbe cime (minta: 26 06 xx xx 00 00)
0x77E10   mov 0, r8
0x77E12   jarl 0x4B3E0, lp                       ; toresspontos interpolacio
0x77E16   40 06 3F 00   dispose 0, 0x001F, [lp]  ; masolva FUN_4B0EA-bol
0x77E40   05 00 | 0000 1500 | 5000 1500 | 6E00 2100 | A000 3C00 | FF00 3C00
```
Ugrástávolságok ellenőrizve, mind a 22 bites `jarl` határon belül:
`+209340`, `−232314`, `−182834`.

### 33.6 Ami még kell a flasheléshez
1. `tools/patch_autodist.py` — összerakja és `--verify` móddal
   **visszadisassemblálja** az eredményt (a HCM `patch_led_cornering.py`
   mintájára).
2. `fwcrc.py resign` (belső CRC16) + `vbf.py pack` (VBF CRC-k).
3. **Célzott CAN-log** a `HVAC_CAN.md` 5. szakasza szerint — nem a patch
   helyességéhez, hanem a `0x190` `B5` iránybitek előtte/utána
   összehasonlításához.

### 33.7 A patch MEGÉPÍTVE és ELLENŐRIZVE (2026-08-25)

Eszköz: **`tools/patch_autodist.py`** (`build` / `verify` / `revert`).

```
python tools/patch_autodist.py build  F1ET-18D619-AM_00008000.bin patched.bin
python tools/patch_autodist.py verify patched.bin
python tools/fwcrc.py resign patched.bin
python tools/vbf.py pack F1ET-18D619-AM.VBF patched.bin F1ET-18D619-AM_AUTODIST.vbf
```

Beépített védelmek: ellenőrzi az eredeti 8 bájtot (patchelt fájlra nem fut le),
ellenőrzi, hogy a céltartomány üres (`FF`), hogy a rutin nem lóg bele a táblába,
és hogy a patch a belső CRC hatókörén belül marad.

**A `verify` visszadisassemblálja a saját kimenetét** (`v850dis`-szel):
```
44C44  83ffbc31     jarl     0x77E00, lp
44C48  64574886     st.h     r10, -31160[gp]
77E00  80072100     prepare  0, 0x0010
77E04  bcff8674     jarl     0x3F28A, lp
77E08  0a38         mov      r10, r7
77E0A  2606407e0700 mov      0x00077E40, r6
77E10  0042         mov      0, r8
77E12  bdffce35     jarl     0x4B3E0, lp
77E16  40063f00     dispose  0, 0x001F, [lp]
77E40  n = 5   (0,21) (80,21) (110,33) (160,60) (255,60)
EREDMENY: OK
```

**Teljes képi diff: 52 bájt** változott a 458 752-ből (hook 5, rutin 26,
tábla 22 — plusz a belső CRC 2 bájtja). Semmi más.

Checksum-lánc:
```
eredeti:            tarolt=D8DF szamolt=D8DF OK
patchelt (resign elott): tarolt=D8DF szamolt=1016 ELTER   <- helyesen jelez
patchelt (resign utan):  tarolt=1016 szamolt=1016 OK
VBF:  file_checksum F416B6C6 OK,  blokk-CRC B9A6 OK
```

**A `B9A6` blokk-CRC NEM veletlen, hanem INVARIANS** (kezdetben veletlen
egybeesesnek neztem -- tevesen). A belso flash-CRC (`0x77FF4`) es a VBF
blokk-CRC **ugyanazt a polinomot** hasznalja (`0x1021`).  Mivel a belso CRC a
sajat uzenete VEGERE van fuzve, a teljes kepre szamolt CRC egy allando
maradekba fut -- fuggetlenul attol, mit valtoztattunk.

Ellenorizve: `resign` NELKUL a blokk-CRC **`8123`**, `resign` UTAN mindig
**`B9A6`**, barmilyen modositasnal.

**Ez egy ingyen kapott biztonsagi ellenorzes:**
> ha a VBF blokk-CRC-je nem `B9A6`, akkor elmaradt a `fwcrc.py resign`.

### 33.8 A feladatsorrend kérdése LEZÁRVA
Aggály volt, hogy a `FUN_444E6` a `gp-28665`-öt esetleg egy ciklussal
korábbi értékként látja. **Nem probléma, mert a `FUN_444E6` MÁR MOST is
olvassa ugyanezeket az értékeket** ugyanabból a forrásból:
```
0x445A4, 0x445C8  ->  FUN_3F284  (gp-28667)
0x44AB0, 0x44DF2  ->  FUN_3F28A  (gp-28665)
```
A patch tehát **nem vezet be új adatfüggőséget** — pontosan azt az értéket
olvassa, amit a függvény négy másik helyen már használ.

(A `0x9EAC` / `0xA0A4` táblák monoton növekvő címsorrendben állnak, tehát
link-sorrendű belépési pont-listák, nem végrehajtási ütemterv — abból a
sorrend nem olvasható ki. Ez a kérdés így tárgytalan.)

### 33.9 ÁLLAPOT
`F1ET-18D619-AM_AUTODIST.vbf` **elkészült és ellenőrzött, de NINCS FLASHELVE.**
Flashelés előtt ajánlott egy „előtte" CAN-log (`HVAC_CAN.md` 5. szakasz),
hogy az „utána" összehasonlítható legyen.

---

## 34. KALIBRÁCIÓ-MÓDOSÍTÓ — `tools/calpatch.py`  **[kész]**

Recept-vezérelt kalibrációs szerkesztő, **modell-alapú előzetes kiértékeléssel**:
minden változtatás „szárazon" lefuttatható, és a `model.py` megmutatja, mit
csinál a viselkedéssel — flashelés előtt.

```
python tools/calpatch.py list
python tools/calpatch.py show  dualzone
python tools/calpatch.py show  dualzone --value 64
python tools/calpatch.py apply dualzone <in.bin> <out.bin> --variant eu
python tools/calpatch.py diff  <patched.bin> <orig.bin>
```

Biztonsági ellenőrzések: minden tétel megadja a **várt jelenlegi értéket**, és
eltérésnél leáll (már módosított fájl vagy más firmware-verzió); az értékek
recept-szintű tartományhoz vannak kötve.

### 34.1 Receptek

| név | mit | gyári | javasolt | tartomány |
|---|---|---|---|---|
| `dualzone` | `cal[569]` — a két zóna szétválasztása | 32 | **48** | 8…100 |
| `autoblower_quiet` | `cal+2060` közepe — AUTO fúvó csendesítése | 30/31/33 | 27 | 22…40 |
| `maxdefrost_quiet` | `cal[513]` — MAX defrost fúvó-minimum | 64 | 55 | 40…64 |

Az utóbbi kettő **nincs alkalmazva** — a `maxdefrost_quiet` biztonsági
funkciót érint (szélvédő-párátlanítás), az `autoblower_quiet` pedig ízlés
kérdése, amit mérés nélkül nem érdemes eltalálni.

### 34.2 `dualzone` — miért ez a legbiztonságosabb elsőnek

A `cal[569]` a `(alapjel_oldal − alapjel_átlag)` tagot szorozza. Ebből
következik egy erős tulajdonság, a modellben ellenőrizve:

| helyzet | előtte A/B | utána A/B | különbség |
|---|---|---|---|
| **mindkettő 22 °C** | 106 / 106 | **106 / 106** | 0 → 0 |
| bal 20 / jobb 24 °C | 67 / 151 | 55 / 163 | 84 → 108 |
| bal 18 / jobb 26 °C | 17 / 210 | 0 / 238 | 193 → 238 |
| bal 18 / jobb 26 (hidegben) | 92 / 255 | 65 / 255 | 163 → 190 |

**Azonos alapjelnél pontosan nulla a hatás** — ha a két oldal ugyanoda van
állítva, a modul bitre ugyanúgy viselkedik, mint eddig. És a közös csatornák
sem változnak: cél-kifúvási hő 187 → 187, mód-ajtók 187 → 187.

### 34.3 Az elkészült fájl
```
C346     cal[569]  32 -> 48
C346FAP  cal[569]  32 -> 48        (mindket europai valtozat -- auto nelkul
                                     nem tudjuk leolvasni, melyik az aktiv)
diff: 2 bajt (+ a belso CRC 2 bajtja)
belso CRC: D8DF -> 593B (resign)
VBF: file_checksum OK, blokk-CRC B9A6 (a 33.7 szerinti invarians -> a resign megtortent)
```
**`F1ET-18D619-AM_DUALZONE.vbf` — kész, ellenőrzött, NINCS FLASHELVE.**

---

## 35. A `gp` REGISZTER, A TELJES CAN-TÉRKÉP, ÉS A 27. SZAKASZ ELLENTMONDÁSÁNAK LEZÁRÁSA  **[B]**

### 35.1 `gp = 0xFEE04000`
Az indítókódban (`0x122C4`): `mov 0xFEE04000, gp`. Ezzel **minden `gp-N`
változó abszolút RAM-címre váltható**: `cím = 0xFEE04000 − N`.

Ellenőrzés a 16. szakasz **független élő mérése** ellen:

| változó | cím | a 0x190 üzenetben |
|---|---|---|
| `gp-30700` | `0xFEDFC814` | B0 — a puffer kezdete |
| `gp-30697` | `0xFEDFC817` | B3 |
| `gp-30696` | `0xFEDFC818` | **B4** — AUTO bit ✔ |
| `gp-30695` | `0xFEDFC819` | **B5** — iránybitek ✔ |

Pontosan egyezik. (Egyéb: `ep = 0xFEDFE698`, `tp = 0x0001A1C8`, `sp = 0xFEDFFFCC`.)

### 35.2 A CAN-táblák szerkezete
```
0xA94C : 32 x u16  RX szurotabla    (ID = LE16 >> 2), csokkeno sorrendben
0xA98C : 32 x u16  PERMUTACIO       (szuro-pozicio -> logikai uzenetindex)
0xAA8C :  7 x u32  TX pufferek
0xAAEC :  7 x u16  TX ID-k
0xAAFC : 30 x u32  RX pufferek      (meret a kovetkezo mutatobol: 4 vagy 8 bajt)
```
A TX oldal a 16. szakasz élő mérésével igazolva (`0xFEDFC814` ↔ `0x190`).

### 35.3 A teljes RX-térkép

| ID | puffer | méret | | ID | puffer | méret |
|---|---|---|---|---|---|---|
| `0x6B2` | `0xFEDFC824` | 8 | | `0x230` | `0xFEDFC880` | 8 |
| `0x415` | `0xFEDFC82C` | 8 | | `0x225` | `0xFEDFC888` | 4 |
| `0x405` | `0xFEDFC834` | 8 | | `0x220` | `0xFEDFC88C` | 4 |
| `0x400` | `0xFEDFC83C` | 8 | | `0x217` | `0xFEDFC890` | 4 |
| `0x360` | `0xFEDFC844` | 8 | | `0x215` | `0xFEDFC894` | 8 |
| `0x330` | `0xFEDFC84C` | 8 | | `0x1E0` | `0xFEDFC89C` | 8 |
| `0x310` | `0xFEDFC854` | 4 | | `0x1A8` | `0xFEDFC8A4` | 8 |
| `0x300` | `0xFEDFC858` | 8 | | `0x160` | `0xFEDFC8AC` | 8 |
| `0x2D0` | `0xFEDFC860` | 8 | | `0x130` | `0xFEDFC8B4` | 8 |
| `0x2B0` | `0xFEDFC868` | 8 | | `0x110` | `0xFEDFC8BC` | 8 |
| **`0x2A0`** | **`0xFEDFC870`** | 8 | | `0x108` | `0xFEDFC8C4` | 8 |
| `0x241` | `0xFEDFC878` | 8 | | `0x090` | `0xFEDFC8CC` | 4 |
| | | | | `0x083` | `0xFEDFC8D0` | 8 |
| | | | | **`0x080`** | **`0xFEDFC8D8`** | 8 |
| | | | | `0x060` | `0xFEDFC8E0` | 4 |
| | | | | `0x040` | `0xFEDFC8E4` | 8 |
| | | | | `0x03A` | `0xFEDFC8EC` | 8 |
| | | | | `0x020` | `0xFEDFC8F4` | 8 |

(`0x7DF` és `0x733` a két diagnosztikai ID, nincs adatpufferük.)

**Két kulcsjel azonosítva:**
- **Külső hőmérséklet** = `0x2A0` **B4 bit1:0 + B5** (10 bites), státusz `B4 bit4:3`
- **`FUN_4AF1A`** = `0x080` **B1 bit1:0 == 3** és **B5 bit4:0 == 8**

### 35.4 Mit mond a log a `0x080`-ról
A `Can_bus_logger_2308261736` menetlogban, **MS-CAN (3/11)**, 5153 keret:

| B1[1:0] | B5[4:0] | keret | arány |
|---|---|---|---|
| 3 | **7** | 5098 | **98,9 %** |
| 3 | 3 | 44 | 0,9 % |
| 3 | 6 | 11 | 0,2 % |

A státusz végig érvényes (3), de az érték **7, soha nem 8** →
**`FUN_4AF1A()` normál üzemben HAMIS.**

### 35.5 AZ ELLENTMONDÁS OKA — `addi` vs `cmp` carry-szemantika  **[módszertani]**

A 27. szakasz nyitott ellentmondása egy **dekódolási csapdából** eredt:

```
cmp  a, b        ->  CY = 1  ha  b <  a     (kolcsonvetel)
addi -a, b, r0   ->  CY = 1  ha  b >= a     (atvitel az osszeadobol)
```
A kettő **ellentétes**, pedig a disassembler mindkettő után ugyanazt a
`bl` / `bnl` nevet írja ki. A `0x3B448`-nál:
```
0x3B444  jarl 0x401AE        ; r10 = motorfordulat
0x3B448  addi -301, r10, r0
0x3B44C  bl   0x3B47A        ; CY==1  ->  RPM >= 301  ->  gp-31744 = gp-31735
```
Vagyis **járó motornál a teljes AUTO fúvóigény megy át**, és a 20 %-os
korlát csak **álló motornál** (gyújtás rá, indítás előtt, start-stop) él —
akkumulátorvédelem. Ez pontosan értelmes.

Ugyanez a javítás a 21. szakaszra: a `cal[527]` korlát (`0x3BA10`) is
**álló motornál** él, nem járónál.

**Az `addi …, r0` + `bl`/`bnl` minta 204 helyen fordul elő a firmware-ben.**
Az elemzésben érintett összes helyet átnéztem; a többi következtetés `cmp`-re
épült, azokat nem érinti. (Az alapjel 30…60-as tartomány-ellenőrzése,
`0x4ACC6`, szintén ezt a mintát használja — újraszámolva a 24.3 szakasz
megállapítása változatlanul áll.)

### 35.6 A fúvólánc LOGGAL IGAZOLVA
`FUN_396A6` és `FUN_3981A` a `gp-28683`-at **×5-tel** teszi a buszra
(`mulhi 5`). A logban a `3/11 0x180` `B2:B3` mezőben 5147 kereten:

**mind a 25 előforduló érték pontosan 5 többszöröse**, ami
`gp-28683` = **0 és 38…61** értékeket ad — a `cal[519]=20 … cal[518]=89`
vágáson belül, a `cal+2060` AUTO-görbe kimeneti tartományában, menet közben
folyamatosan változva (0 = fúvó ki).

Ezzel a fúvólánc **statikusan és élő adaton is zárt**.

---

## 36. AZ UDS-RÉTEG — DID- ÉS DTC-TÁBLA  **[B]**

> **⚠ FIGYELEM — ez a szakasz a DID-táblát ROSSZ offsettől olvassa.**
> A helyes tábla `0xB2CC`, 48 bejegyzés, `+0` a DID és `+2` a hossz.
> Az itt közölt DID → jelentés párosítás **egy bejegyzéssel el van csúszva**.
> **A javított térkép a 40. szakaszban van** — ezt használd.

Eszköz: **`tools/uds.py`** (`dids` / `dtcs` / `sensors` / `all`).

### 36.1 DID-tábla — `0xB2D0`, 51 × 16 bájt
```
+0  u32  hozzaferesi / session flagek
+4  u32  flagek 2
+8  u32  a kezelo fuggveny cime
+12 u16  DID      +14 u16  adathossz bajtban
```
**Igazolás:** a 37. bejegyzés `DID 0xF18C`, hossz 16, kezelő `0x254BE` — a
kezelő 24 bájtot másol a `0xBCBC` flash-címről, ahol a
**`F1ET-18D619-AM`** karakterlánc áll. Ez a modul cikkszáma.

Kiemelt DID-ek: `F110` / `F111` / `F113` (cikkszámok), `F188` (szoftververzió),
`F18C` (sorozatszám), `F106` (254 bájt), **`FD0A` (88 bájt — az As-Built
konfigurációs blokk, amit a 11.2 szakasz `FUN_256A0`-ként azonosított)**,
`DE00`/`DE01`/`DE02`, `FD00`–`FD0C`, valamint a `98xx` / `99xx` / `9Bxx`
tartomány Ford-specifikus élő adatai.

### 36.2 DTC-tábla — `0xBC34`, 30 × 4 bájt
```
+0  u8   FTB (failure type byte)
+1  u16  DTC-kod, LITTLE ENDIAN, ISO 14229 2 bajtos alak
+3  u8   0
```
Az index **1-től 30-ig** (`FUN_247FA`: érvényes ha `1 <= i <= 30`), a
státuszbájtok a `gp-27368` tömbben.

| idx | DTC | idx | DTC | idx | DTC |
|---|---|---|---|---|---|
| 1 | C1B14 | 11 | B10B4 | 21 | U2101 |
| 2 | B102E | 12 | B10B5 | **22** | **U3000-41** |
| 3 | B1030 | 13 | B10B6 | 23 | U3003-16 |
| 4 | B1032 | 14 | B10BB | 24 | U3003-17 |
| 5 | B105A | 15 | B125B | 25 | B10B8 |
| 6 | B1081 | 16 | B1A61 | 26 | B10B9 |
| 7 | B1082 | 17 | B1A63 | 27 | U0140 |
| 8 | B1083 | 18 | B1A64 | 28 | U0155 |
| 9 | B1086 | 19 | B1A69 | 29 | U0166 |
| 10 | B10B3 | 20 | U2100 | 30 | U0422 |

**Kereszt-igazolás:** a 22-es index = **`U3000-41`** = „Control Module General
Checksum Failure", és a 21 `FUN_24B08` hívóhely közül épp a `0x542B4`
állítja — ami a `FUN_54218` **belső flash-CRC háttérfeladatban** van (5. szakasz).
Vagyis a patch utáni kötelező `fwcrc.py resign` elmulasztása pontosan
**U3000-41** hibakódot ad. A korábbi „22-es DTC" megnevezés ezzel névre szólóvá vált.

A 21 hívóhely csoportosan is értelmes: `U0140`/`U0155`/`U0166`/`U0422` egyetlen
összefüggő blokkban (`0x51C4A`…`0x51E0A`) = CAN-időtúllépés-figyelő;
`U3003-16/17` a `0x26B54`/`0x26B5E`-nél = tápfeszültség-figyelő;
`B1030`/`B1032` az `0x536AA`/`0x53784`-nél = ülésfűtés.

### 36.3 AZ ÉRZÉKELŐK VÉGLEG AZONOSÍTVA
Az ADC-leírótábla (`0xE1F0`) +16/+17 bájtja a **DTC-index**. Ezzel a 30.5
szakasz „a négy NTC szerepe" nyitott tétele lezárul:

| idx | ADC | görbe | DTC | jelentés |
|---|---|---|---|---|
| 0 | 11 | `0xCC9C` | **B10B5** | hőmérséklet-érzékelő 3 |
| 1 | 13 | `0xCC9C` | **B10B3** | hőmérséklet-érzékelő 1 |
| 2 | 10 | `0xCC9C` | **B10B6** | hőmérséklet-érzékelő 4 |
| 3 | 12 | `0xCC9C` | **B10B4** | hőmérséklet-érzékelő 2 |
| 4 | 14 | `0xCC7C` | **B1A64** | **napszenzor** |
| 5 | 15 | `0xCC7C` | **B1A63** | **napszenzor** (másik oldal) |
| 6 | 6 | `0xD0AC` | **B1A61** | **külső hőmérséklet-érzékelő** |

Ez **független megerősítése** a 24.2 szakasz következtetéseinek, amiket ott
pusztán a linearizáló görbék alakjából vezettem le (a napszenzorok lineáris
0…250 karakterisztikája, a külső hőmérséklet külön NTC-görbéje).

### 36.4 Mire jó ez
- A `dids` kimenet a **PC-oldali élő adatpanel** alapja (31.7/3. pont): minden
  DID-hez megvan a hossz és a kezelő, tehát tudjuk, mit kérdezhetünk le.
- A `dtcs` kimenet fordítja a modul hibakódjait — flashelés után az
  **U3000-41** hiánya igazolja, hogy a `resign` sikerült.

---

## 37. ÉLŐ ADATPANEL — `tools/livedata.py`  **[kész]**

A DID-kezelők egyenkénti átolvasásával kiderült, **melyik DID melyik belső
jelet adja vissza, és milyen skálázással**. Az eszköz transzport-független:
kiírja a kiküldendő UDS-kérést, és dekódolja a választ — bármilyen eszközzel
használható, ami tud `22 xx xx`-et küldeni (UCDS, FORScan, saját J2534-kliens).

Diagnosztikai címzés: **kérés `0x733`, válasz `0x73B`** (a 35.3 RX-térképből).

### 37.1 A bizonyított skálázású DID-ek

| DID | jelentés | skálázás (a kezelőből) |
|---|---|---|
| **`0x9927`** | **külső hőmérséklet** | `°C = bájt × 0,2 − 16` (`FUN_24FEC`: `byte = OAT/2 + 80`) |
| **`0x9B01`** | **recirkulációs ajtó** | a bájt közvetlenül **%** |
| **`0x9B02`** | **mód-ajtó #1** | % |
| **`0x9B03`** | **keverőajtó A** | % |
| **`0x9B04`** | **keverőajtó B** | % |
| **`0x9850`** | **mód-ajtó #2** | % |
| **`0x981A`** | **fúvó kitöltés** | `% = bájt × 100 / 255` |
| `0xF18C` | cikkszám | `F1ET-18D619-AM` |
| `0xFD0A` | As-Built konfigurációs blokk | 88 bájt |

Mind az öt léptető ugyanazt a `(lépés + 10) / 20` konverziót használja
(`FUN_250F2`, `0x25122`, `0x25152`, `0x25182`, `0x24F88` — mind ellenőrizve),
vagyis **a válaszbájt közvetlenül a pozíció százalékban**.

**Ez a legfontosabb gyakorlati eredmény: mind az öt ajtó pozíciója élőben
olvasható UDS-en, CAN-sniffelés nélkül.**

Megjegyzés: a DID-tábla `hossz` mezője a **puffer mérete**; a tényleges
válaszhosszt a kezelő állítja be (`st.h n, 12[rX]`).

### 37.2 Amit ez lezár — pontos mérési terv autóhoz

**A) Az ajtó-geometria (a 30.5 utolsó „méréssel zárható" tétele)**
Álló járműben, gyújtás rá, a klímát kezelve, minden lépésben leolvasva a
`0x9B02` és `0x9850` DID-et:

| gomb | várt `0x9B02` | várt `0x9850` |
|---|---|---|
| fej | 21 | 40 |
| fej + láb | 33 | 0 |
| láb | 60 | 0 |
| szélvédő | 0 | 100 |
| MAX defrost | 0 | 100 |
| **AUTO** | **58 (állandó)** | változó |

Ha ez így jön ki, a `cal+2320` / `cal+2299` tábla **közvetlenül igazolt**,
és az „AUTO-ban állandó 58" megállapítás is. Amelyik ajtónál a fúvás
érezhetően arc↔láb között vált, az az ajtó#1.

**B) A 33. patch ellenőrzése**
Flashelés után AUTO-ban a `0x9B02` már **nem 58**, hanem követi a fűtésigényt
(melegben ~21, átmenetben ~33, hidegben ~60).

**C) A fúvólánc**
`0x981A` összevetve a `0x180` `B2:B3`/5 értékkel — a kettőnek egyeznie kell.

### 37.3 Használat
```
python tools/livedata.py list        # mit tudunk lekerdezni
python tools/livedata.py requests    # a kikuldendo UDS-keresek
python tools/livedata.py decode 9927 A0
python tools/livedata.py panel valaszok.txt
python tools/livedata.py demo        # offline proba a modellbol
```

---

## 38. A LÉPTETŐ-MEGHAJTÓ BELSEJE  **[B]**

### 38.1 Körbeforgó ütemezés — egyszerre EGY motor
`FUN_27050` a `gp-27059` index szerint **ciklusonként csak egy motort** léptet
(`FUN_28394` + `FUN_28382`), majd léptet egyet az indexen. Öt motornál ez
ötödannyi egyidejű áramfelvétel — klasszikus megoldás.

### 38.2 A parancs skálája
```
FUN_27E6A(motor, parancs):
    loket  = FUN_27DD8(motor)              ; a TANULT loket lepesben
    lepes  = parancs * loket / 2000
    FUN_27E24(motor, lepes)
```
Vagyis a **parancs 0…2000 = 0…100 %**, és a firmware skálázza az adott motor
saját lépésszámára. A visszaolvasás (`FUN_27E9A`) ennek a pontos inverze:
`(2000 * pozicio + loket/2) / loket` — ezért ad a `FUN_27554` közvetlenül
százalékot ×20-ban, és ezért lett a 37.1 DID-skálázás egyszerű %.

`FUN_27E24` **holtsávot** alkalmaz: csak akkor mozdul, ha
`|uj − jelenlegi| > desc[+32]`. A `desc[+32]` mind az öt motornál ugyanarra a
`0xCBE0` címre mutat, ahol **5** áll — vagyis **±5 lépés holtsáv**,
ami a felesleges oda-vissza mozgást (és a zajt) szünteti meg.

### 38.3 Löket-tanulás és határok
`FUN_28394(struct, desc)`:
```
ha  struct[10] > *desc[+12]  vagy  struct[10] < *desc[+16]:
        struct[10] = *desc[+8]        ; vissza a nevleges loketre
        struct[40] bit7 = 1           ; hiba jelzese
```
Tehát **`struct+10` a betanult tényleges löket**, amit a modul homing során
mér, és amit a leíró alsó/felső korlátja keretez:

| motor | névleges | alsó | felső | holtsáv |
|---|---|---|---|---|
| 0 | 1625 | 1462 | 2143 | 5 |
| 1 | 1390 | 973 | 1807 | 5 |
| 2 | 905 | 634 | 1177 | 5 |
| 3 | 905 | 634 | 1177 | 5 |
| 4 | 810 | 567 | 1053 | 5 |

### 38.4 MINDEN LÉPTETŐHÖZ TARTOZIK EGY HIBAKÓD  **[B]**
`FUN_279B8` a hibás motor DTC-jét a leíró **+38** bájtjából veszi
(`ld.bu 38[r6]` → `FUN_24B08`). A 36.2 táblával összevetve:

| motor | port / bitek | löket | DTC-index | **DTC** |
|---|---|---|---|---|
| 0 | `FF400064` b0-3 | 1625 | 8 | **B1083** |
| 1 | `FF400064` b4-7 | 1390 | 9 | **B1086** |
| 2 | `FF400054` b8-11 | 905 | 6 | **B1081** |
| 3 | `FF400054` b4-7 | 905 | 7 | **B1082** |
| 4 | `FF400064` b8-11 | 810 | 15 | **B125B** |

**A 2-es és 3-as motor — a bájtra azonos ikerpár — szomszédos kódot kap
(`B1081` / `B1082`).** Ez önmagában, külső ismeret nélkül is megerősíti, hogy
ez a két hőmérséklet-keverőajtó (20.1 szakasz).

### 38.5 Amit a Ford-féle kódjelentések valószínűsítenek  **[E]**
A fenti hozzárendelés **[B]** (kódból bizonyított). A hibakódok *szövege*
viszont külső ismeret, itt nem ellenőrizhető. Ha a szokásos Ford-jelentések
állnak (`B1083` = levegő-beszívó / recirkulációs ajtó, `B1086` =
panel/padló ajtó, `B125B` = szélvédő-ajtó), akkor:

- **0-s motor = recirkuláció** — ez eddig csak [E] volt (20.1), most egy
  második, független jel is erre mutat;
- **1-es motor (mód-ajtó #1) = a PANEL/PADLÓ ajtó** — ez pontosan az a
  feltevés, amire a 33. patch görbéje épül (fej 21 → fej+láb 33 → láb 60);
- **4-es motor (mód-ajtó #2) = a szélvédő-ajtó** — összhangban azzal, hogy a
  `cal+2299` táblában szélvédő módban 100, panel/láb módban 0.

**Ez nem bizonyíték, de három egymástól független nyomvonal ugyanoda mutat:**
a mode → pozíció táblák alakja (20.2), a léptetők löketei és ikerpárja (20.1),
és most a hibakód-hozzárendelés. A 37.2 szakasz UDS-mérése ezt véglegesen
eldönti.

---

## 39. A BELSŐ HŐMÉRSÉKLET-MODELL — a `0x42B8E`…`0x43766` blokk  **[B]**

Ez a 30.5 szakasz utolsó statikus nyitott tétele. A blokk **három külön
alrendszerből** áll, és a végén **egy kétcsomópontos fizikai utastér-modellt**
futtat. Menet közben két korábbi feltevés is javult (39.1, 39.3).

### 39.0 A közös építőelem: `FUN_4B29E` — az exponenciális szűrő  **[B]**

**32 hívója van a firmware-ben**, érdemes egyszer rendesen leírni.

```
FUN_4B29E(r6 = &maradek(u16),  r7 = elozo,  r8 = bemenet,  r9 = N)
  -> FUN_4B248 elojel-eltolt (+-0x8000) valtozatban
```
`FUN_4B248` (a `0x4B26A / 0x4B278 / 0x4B286 / 0x4B292` helyeken a v850dis
`.hword`-öt ír; a nyers bájtokból dekódolva ezek **`shl`/`shr reg1,reg2,reg3`**
regiszteres léptetések):

```
ha N == 16 :  return bemenet                       ; atkotes, nincs szures
N = min(N, 15)
maszk = (1 << N) - 1
ha maradek > maszk : maradek = 0                   ; ellenorzo nullazas
t       = bemenet + elozo * (2^N - 1) + maradek
maradek = t & maszk
return    t >> N
```
Vagyis **`ki = elozo + (be - elozo) / 2^N`**, a törtrész átvitelével — így
**nincs holtsáv és nincs maradó eltérés**, még 1-es lépésű jelnél sem.
Az időállandó `2^N` mintavételi periódus. **`N = 16` = szűrés nélkül.**

> Ez a rutin adja az egész firmware összes simítását (hőmérsékletek,
> sebesség, napszenzor, fúvó, ajtópozíciók). Ahol `N` kalibrációból jön,
> ott a reakcióidő **flashelés nélkül nem, de patch nélkül igen** hangolható.

### 39.1 KORREKCIÓ: `gp-29072` **nem** a belső hőmérséklet — a KÜLSŐ  **[B]**

A `FUN_42B8E` (18 hívó) a `0x42BBE` ciklikus feladat kimenete:

```
FUN_42C68  ; forrasvalasztas
  ha FUN_4A724() >= 3 :  gp-26283 = 3 ;  gp-26288 = FUN_4A6F0()
  kulonben            :  gp-26283 = 2 ;  gp-26288 = cal.h[280] = 88
FUN_42BF2  ; szuro-meghajto,  52-es idozito,  periodus cal.h[282] = 750
  gp-26284 = (gp-26283 >= 3)          ; ervenyes-jelzo
  gp-26286 = gp-26288 << 6            ; Q6-ba emelve
  ... FUN_42CA6 ...
  gp-26292 = gp-31282   (A szuro)     gp-26296 = gp-31284   (B szuro)
0x42BBE  ; publikalas
  gp-29070 = gp-26292 >> 6   (FUN_42B94)   ; gyorsan szurt,  0,1 C
  gp-29072 = gp-26296        (FUN_42B8E)   ; lassan szurt,   Q6 (0,1 C x 64)
  gp-29068 = gp-26288        (FUN_42B9A)   ; nyers bemenet,  0,1 C
  gp-28642 = gp-26283        (FUN_42BA0)   ; statusz
```

**A bemenet a 6-os ADC = a modul saját külső hőmérséklet-érzékelője**
(`FUN_4A6F0` → `FUN_4FF8E(6)`, vagy `gp-26112 != 0` esetén a
**UDS-felülírás** `gp-26134`), **+40,0 / −20,0 °C-ra vágva**.

`FUN_42CA6` — **két szűrő ugyanarra a bemenetre, más időállandóval**:

| szűrő | kimenet | `N` forrása | C346 érték | τ (750-es periódusban) |
|---|---|---|---|---|
| A | `gp-29070` | ha `FUN_49984()` (sebesség) `< cal[640]=1` → `cal[637]` | **8** | 256 periódus |
| A | | különben ha `FUN_49ABC()` → `cal[639]` | **1** | 2 periódus |
| A | | különben `cal[636]` | **3** | 8 periódus |
| B | `gp-29072` | ha `FUN_40C3E() >= 1` → `cal[638]` | **12** | **4096 periódus** |
| B | | különben ugyanaz, mint A | | |

Vagyis **álló járműnél lassú, menet közben gyors** — pontosan a
külső-hőmérséklet-mérés klasszikus problémája (a motortér felmelegíti az
érzékelőt, amíg nincs átáramlás).

**A bizonyíték, hogy ez a külső hő:** a 18 hívó mind `>> 6`-tal 0,1 °C-ra
alakítja, és **határként** használja (`0x42904`: `FUN_42B8E() + cal[631]<<6`,
`0x42920`: `FUN_42B8E() − cal[632]<<6`), illetve a soak-modell referenciája.
A `gp-29072` tehát a **stabilizált külső hőmérséklet**, nem a belső.

> **A belső hőmérséklet becslése a `gp-29062` / `FUN_42D7E`** — lásd 39.4-től.

### 39.2 Az áramlás-becslő — `0x42E34`  **[B]**

Ez adja a modellnek a **tömegáramot**, kimenetei `gp-29050…29056`:

```
0x43766 (105-os idozito, periodus cal.h[284]=125):
   gp-31234 = szuro( FUN_3A37A() << 2 , N = cal[643] = 4 )   ; fuvo kitoltes x4
0x42E80:
   sp[2] = gorbe(0xCD00, gp-31234)         ; (0,0) (80,134) (340,556)
   r27   = (gp-31234 >= 60) ? (sp[2] * 38) >> 2 : 0          ; fuvo >= 15 %
   r25   = (sebesseg_kmh * cal.h[326]=625) >> 6              ; = v * 9,77
   r19   = (r25 * gorbe(0xCC14, recirk_%)) >> 10             ; (0,0)(48,100)(100,0)
   r29   = (r19 * 41943) >> 16  +  r27                       ; = torlolegaram*0,64 + fuvo
   gp-29050 = r29 >> 2                                       ; TELJES TOMEGARAM / 4
```
A `0xCC14` görbe csúcsa **48-nál** van — a 28. szakaszból ismert
**friss levegő = 49** pozíció. Vagyis a torlólevegő pontosan akkor jut be,
amikor a beszívó ajtó friss állásban van. **Ez független megerősítése a
recirkulációs ajtó `{49, 80, 100}` értelmezésének.**

Ezután a `r29` szétosztása a három kifúvás között, az ajtópozíciókból:

| getter | motor | görbe | mit ad |
|---|---|---|---|
| `FUN_4AFDE` | 1 (mód-ajtó #1) | `0xCF64` | 0 % → 0, 21-35 % → 100, 60 %-tól 0 |
| `FUN_4AFA2` | 1 (mód-ajtó #1) | `0xCF84` | 21 %-ig 0, 60 % → 100, 100 % → 30 |
| `FUN_4B044` | 4 (mód-ajtó #2) | — | nyers pozíció % |
| `FUN_4B068` | 0 (recirkuláció) | — | nyers pozíció % |

*(a pozíció mindenütt `(FUN_27544(motor) + 10) / 20` = 0…100 %)*

```
r24 = max(FUN_4AFA2(), 10)                     ; PADLO resz
r26 = FUN_4B044() << 6                         ; SZELVEDO resz
r28 = (FUN_4AFDE() + r24) << 6 + r26           ; osszes
r23 = max(r28, 64)   ;   NORM = 0x100000 / r23 ; normalizalo
gp-29056 = (FUN_4B044() * NORM * r29) >> 14 >> 2   ; SZELVEDO-aramlas
gp-29054 = (FUN_4AFDE() * NORM * r29) >> 14 >> 2   ; PANEL-aramlas
gp-29052 = (r24         * NORM * r29) >> 14 >> 2   ; PADLO-aramlas
```

**A `0xCF64` és a `0xCF84` egymás tükörképe a mód-ajtó #1 pozíciójában** —
ez negyedik, független bizonyíték arra, hogy az **1-es motor a panel↔padló
ajtó** (vö. 20.1, 20.2, 38.5).

### 39.3 MEGOLDVA: melyik NTC micsoda  **[B]**

A 30.5 nyitott tétele („a négy NTC szerepe"). A modell a négy **nyers**
NTC-értéket **párban, a hozzá tartozó kifúvás áramlásával szorozva** használja
(`0x430EE` és `0x4313A`) — ez egyértelműen párosítja őket:

| pár | nyers | szűrt | ADC | a modellben mivel szorzódik | **mi ez** |
|---|---|---|---|---|---|
| 1 | `gp-29094` | `gp-29102` | **11** | `gp-29052 + gp-29056` = padló + szélvédő | **padló/szélvédő kifúvási hő** (bal) |
| 1 | `gp-29090` | `gp-29098` | **13** | ugyanaz | **padló/szélvédő kifúvási hő** (jobb) |
| 2 | `gp-29096` | `gp-29104` | **10** | `gp-29054` = panel | **panel kifúvási hő** (bal) |
| 2 | `gp-29092` | `gp-29100` | **12** | ugyanaz | **panel kifúvási hő** (jobb) |

A modell mindkét párnál az **átlagot** használja (`(a+b)/2`), ami dual-zone
kivitelnél a bal/jobb átlag. **Ez a négy azonos NTC szerepe: nem belső tér-,
hanem kifúvási hőmérséklet-érzékelők, kifúvásonként egy párral.**
A belső hőmérsékletnek **nincs saját érzékelője** — azt a 39.4 modell számolja.

### 39.4 A KÉTCSOMÓPONTOS UTASTÉR-MODELL — `0x42FA2`  **[B]**

**53-as időzítő, periódus `cal.h[288] = 1250`.** Kapu: `gp-31199 >= 4`
(a `FUN_42DA2()` státusz az előző ciklusból).

Két 32 bites állapotváltozó, mindkettő **Q22 formátumban, 0,1 °C egységben**
(`X >> 17` = `T × 32`, `X >> 22` = `T` 0,1 °C-ban):

| állapot | jelentés |
|---|---|
| `gp-31260` = **X1** | az **utastér tömegének** hőmérséklete (kárpit, ülés, üveg) |
| `gp-31256` = **X2** | az **utastér levegőjének** hőmérséklete |

#### A tömeg-csomópont (egy tag)
```
X1 += ( (T2-T1)*64 * cal.h[320]/65536  +  (T2-T1)*64 * 8/125 ) << 10
    ;  cal.h[320] = 2310  ->  egyutthato 0,03525 + 0,06400 = 0,09925
```
→ a tömeg a levegőt követi, **τ ≈ 806 ciklus ≈ 17 perc**.

#### A levegő-csomópont — hét energiamérleg-tag
Mindegyik `r29`-be gyűlik, majd **`X2_uj = X2 + 2 × Σtag`**
(a kód `r29>>1 + X2>>2` alakban számol, és a végén `<<2`-vel skáláz vissza).

| # | tag | képlet (0,1 °C egységben) | kal. | C346 együttható |
|---|---|---|---|---|
| 1 | padló+szélvédő befújás | `(32*(Tp - T2)) * ((gp29052+gp29056)*4 * k) >> 14 << 15` | `cal.h[322]` | 3668 → **0,06110** |
| 2 | panel befújás | `(32*(Tv - T2)) * (gp29054 * k) >> 14 << 14` | `cal.h[316]` | 3668 → **0,48871** |
| 3 | karosszéria-veszteség | `(32*(OAT - T2)) * k * (8192 + v*14,96) >> 14 << 12` | `cal.h[308]`, `cal.h[330]` | 3238 → **0,06541**; 15231 |
| 4 | saját szenzor felé | `(32*(Tkulso_sz - T2)) * k << 8` | `cal.h[312]` | 7154 → **0,11044** |
| 5 | tömeg-csere | `(32*(T1 - T2)) * k << 13` | `cal.h[310]` | 3639 → **0,06353** |
| 6 | **napterhelés** | `(nap * 1568/512 + nap * 77/47) << 8` | `cal.h[332]` | 1568 → **4,7008** |
| 7 | **nyitott ajtók** | `((9472 - T2*64) * k) * (n<<11) >> 14 << 11` | `cal.h[324]` | 3002 → **0,04581** |

*`Tp` = a padló/szélvédő NTC-pár átlaga, `Tv` = a panel NTC-pár átlaga,
`v` = szűrt sebesség km/h, `nap` = `FUN_475FA()` = `max(bal, jobb napszenzor)`
0…255, `n` = `FUN_4AA54()` = hány CAN-ról jövő 2 bites zár-állapot `== 1`
(7 db: ajtók, motorháztető, csomagtér) → **nyitott nyílások száma** **[E]**.*

**Két tag ki van kapcsolva ebben a változatban:** `cal.h[318] = 0` (a
`sebesseg <= 2` melletti extra tag) és `cal.h[328] = 0`.

#### A tagok nagyságrendje (a `tools/cabin.py` szimulációjából)
| hatás | eredmény |
|---|---|
| 3. tag önmagában (karosszéria), álló jármű | τ ≈ 10,4 perc |
| 4. tag önmagában (saját szenzor felé) | τ ≈ 48 perc |
| **3. + 4. együtt — a tényleges külső horgony, álló** | **τ = 499 s ≈ 8,3 perc** |
| ugyanez 100 km/h-nál | τ = 435 s ≈ 7,2 perc |
| levegő ↔ tömeg | τ = 158 s ≈ 2,6 perc (levegő oldalról), 17 perc (tömeg oldalról) |
| teljes napsütés (255) állandósult állapotban | **+5,5 °C** (nap = 128: +2,5 °C) |

*(a τ-k `cal.h[288] = 1250`-et ms-nak véve; ha az időalap más, minden érték
arányosan skálázódik — a modell szerkezete nem)*

Ez egy **hihető, valódi fizikai utastér-modell**: gyors levegő-csomópont,
lassú tömeg-csomópont, sebességfüggő karosszéria-veszteség, napterhelés.

### 39.5 A becsült belső hőmérséklet előállítása — `gp-31180`

A nyers `X2` nem közvetlenül a kimenet. A `0x433AC` **összekeveri a
kifúvási hőmérséklettel**, az áramlás arányában:

```
w   = (((gp-29052>>4) + (gp-29056>>4)) << 7) * cal.h[314] >> 8   ; cal.h[314] = 115
gp-31180 = ( T2*(16384-w)/16384  +  Tp*w/16384 ) * 4  +  gorbe(cal+1552, OAT) * 64
```
`cal+1552` = `(-40,2) (-12,3) (60,2) (160,-12)` — kis, OAT-függő eltolás
(−12 °C-on +0,3 °C, +16 °C-on −1,2 °C).

**`gp-31180` egysége: 0,1 °C × 64 (Q6).**

### 39.6 A korlátozás — a modell nem szaladhat el

```
sp28 = gp-29072 + 12,0 C            ; cal.b[655] = 12  (elojeles)
sp32 = gp-29072 - napkorrekcio/4
uj_X2 = max( min( modell , sp28 ) , sp32 )
```
ahol a **napkorrekció** (`gp-26250`) külön ág:
```
gp-31188 = szuro( FUN_3E630() << 6 , N = cal[646] = 10 )    ; 84-es idozito, cal.h[298]=250
sp60 = gorbe(cal+1620, gp-31188>>6)   ; (0,0)(80,120)(200,320)(220,400)
sp58 = gorbe(cal+1598, OAT)           ; (-60,32)(-20,36)(0,28)(20,23)(100,16)  [%]
gp-26250 = (sp58 * sp60) / 100        ; 0,1 C
```
A tömeg-csomópont is kap alsó korlátot: `X1 >= clip(OAT, ±20 C) − 24 C`
(`cal+1588` konstans 240).

**Vagyis a becsült belső hőmérséklet mindig a stabilizált külső hőmérséklet
+12 °C-os sávjában marad, alul a napterheléssel csökkentett külső hőnél.**
Ez a modell szökésének biztonsági fékje.

### 39.7 A kimeneti szűrő és a publikált értékek

`FUN_437C0` (**80-as időzítő, periódus `cal.h[300] = 125`**) — **aszimmetrikus**:
```
N = (elozo > mostani) ? cal[647] : cal[648]      ; C346:  4  /  1
gp-31264 = szuro( gp-26264 >> 16 , N )
```
→ **hűlésre lassú (16 periódus), melegedésre gyors (2 periódus).**

A ciklus végén:

| változó | getter | egység | jelentés |
|---|---|---|---|
| `gp-29066` | `FUN_42D72` | 0,1 °C | **`T1` — az utastér tömegének hőmérséklete** |
| `gp-29064` | `FUN_42D78` | 0,1 °C | **`T2` — az utastér levegőjének hőmérséklete** |
| **`gp-29062`** | **`FUN_42D7E`** | **Q6** | **a szűrt, korlátozott BECSÜLT BELSŐ HŐMÉRSÉKLET** |
| `gp-29060` | `FUN_42D84` | 0,1 °C | `gp-26244 >> 6` (a `0x43958` / `0x43E64` ág) |
| `gp-29058` | `FUN_42D8A` | 0,1 °C | `gp-26242 >> 6`, a modell **tartalék** értéke |
| `gp-28641` | `FUN_42DA2` | — | a modell státusza (`>= 4` = fut) |

Ha a modell nem érvényes (`gp-31210 < 3`), a kód mindenütt a
`FUN_42D8A()`-ra (`gp-29058`) esik vissza — ezért nem tud a rendszer
„üres" belső hőmérséklettel elindulni.

### 39.8 Hogyan kapcsolódik a 25.5 soak-modellhez

A 25.5 képlete most már teljesen kitölthető:
```
gp-29074 = ( gp-26302 * cal[633] + FUN_42D7E() * (16 - cal[633]) ) >> 4
         =   mert cal[633] = 4:
           0,25 * gp-26302  +  0,75 * gp-29062
```
Vagyis a szabályozás **75 %-ban a 39.4 fizikai modellre**, 25 %-ban a
soak-becslésre támaszkodik. A `gp-29074` az, ami a 25.6 szabályozási hibába
megy (`gp-26338 = (Tset_A + Tset_B) × 32 − gp-29074`), és a Q6 egység
mindkét oldalon egyezik — a képlet zárt.

### 39.9 Mi hangolható ebből kalibrációból

| cal | mit állít | C346 |
|---|---|---|
| `cal.h[288]` | a modell lépésköze | 1250 |
| `cal.h[308]` / `cal.h[330]` | karosszéria-veszteség + sebességfüggése | 3238 / 15231 |
| `cal.h[310]` / `cal.h[320]` | levegő ↔ tömeg csatolás mindkét irányban | 3639 / 2310 |
| `cal.h[312]` | mennyire horgonyoz a saját külső szenzorhoz | 7154 |
| `cal.h[316]` / `cal.h[322]` | a befújás hatáserőssége (panel / padló) | 3668 / 3668 |
| `cal.h[314]` | mennyire keveredik a kifúvási hő a becslésbe | 115 |
| `cal.h[324]` | a nyitott ajtó hatása | 3002 |
| `cal.h[326]` | torlólevegő km/h-nként | 625 |
| **`cal.h[332]`** | **a napterhelés súlya** | **1568** |
| `cal.b[647]` / `cal.b[648]` | hűlési / melegedési reakcióidő | 4 / 1 |
| `cal.b[655]` | a felső korlát a külső hő felett (°C) | 12 |
| `cal+1552` | OAT-függő eltolás a becslésen | 4 pont |
| `cal+1598` / `cal+1620` | a napkorrekció görbéi | 5 / 4 pont |
| `cal[636…640]`, `cal[643]`, `cal[646]` | az összes szűrő-időállandó | |

**Ha valaki a modul „túl lassan veszi észre, hogy meleg lett" panaszát akarja
javítani**, a `cal.b[647]` (hűlési szűrő, most 4 = 16 periódus a 125-ös
periódusnál) és a `cal.h[314]` (a kifúvási hő súlya) a két fogantyú — de
**mérés nélkül nem érdemes** (vö. 9. figyelmeztetés).

### 39.10 A modell futtatható — `tools/cabin.py`  **[kész]**

A 39.4-39.7 egyenletek egy-az-egyben, a valódi kalibrációs tábláktól táplálva:

```
python tools/cabin.py coeffs                     # a kiolvasott egyutthatok
python tools/cabin.py selftest                   # 9 onellenorzo teszt
python tools/cabin.py soak --oat 300 --sun 255   # allo auto felmelegedese
python tools/cabin.py step --oat -50 --start -50 --duct 500 --flow 600
python tools/cabin.py compare C346 C346NA C344GM
```

A `selftest` a szerkezet zártságát ellenőrzi (mind a 9 rendben):
egyensúly (minden 20 °C → marad 20 °C), a szűrő maradó eltérés nélküli
beállása, a felső korlát, az aszimmetrikus kimeneti szűrő iránya.

A `step` egyben **láthatóvá teszi a 39.6 korlátot**: −5 °C-os külsőnél,
50 °C-os kifúvással a modellezett belső hőmérséklet **pontosan +7,0 °C-on
megáll** (= külső + `cal.b[655]` = −5 + 12), bármeddig fűtünk. Vagyis a
szabályozó soha nem „hiszi el", hogy 12 °C-nál jobban felmelegítette az
utasteret a külsőhöz képest.

#### Változat-eltérések (`compare`)
Ez a blokk **majdnem teljesen változat-független** — 16 mezőből 13 azonos:

| mező | C346 | C346NA | C344GM | mit jelent |
|---|---|---|---|---|
| `cal.h[314]` `w_duct` | 115 | 115 | **134** | a C344GM jobban támaszkodik a kifúvási hőre |
| `cal.h[318]` `k_lowspd` | 0 | 0 | **262** | a `sebesseg <= 2` tag **a C344GM-en ÉL** |
| `cal.b[647]` `n_cool` | 4 | **1** | **2** | a hűlési szűrő: C346 16, C344GM 4, C346NA 2 periódus |

**A `cal.h[318]` a legérdekesebb:** az a tag, amit a C346 kikapcsolva hagy,
a C344GM-en aktív, és a saját külső szenzor felé húzza a becslést álló
járműnél. Ez egy kész, tesztelt kódág — bekapcsolása **egy 2 bájtos
kalibráció-módosítás** (vö. 31.1 alvó funkciók).

### 39.11 A TARTALÉK-ÁG — `0x43958` / `0x43E64`  **[B]**

Ez volt a §39 utolsó nyitott tétele, és **fontosabbnak bizonyult, mint
„tartalék"**: ez az **indítási** becslés, és **ez engedélyezi a 39.4 fizikai
modellt**.

#### A kapcsolat, ami mindent összeköt

```
FUN_43E64  ->  gp-31200  ->  gp-26216  ->  gp-28641  (FUN_42DA2)
                                              |
                                              v
                          a 39.4 modell kapuja:  gp-31199 >= 4
```
A `0x42FA2` kétcsomópontos modell **csak akkor fut**, ha ez az ág
`gp-31200 >= 4`-et jelent. **Vagyis nem a fizikai modell az elsődleges és ez a
tartalék, hanem fordítva: ez indul először, és amikor eléri a legmagasabb
megbízhatósági fokot, adja át a vezetést a fizikai modellnek.**

#### `FUN_43958` — melyik módszer áll rendelkezésre

Négy megbízhatósági kódot állít elő a jelforrások státuszaiból:

| kód | képlet | jelentés |
|---|---|---|
| `gp-31204` | 4 ha (OAT ok **és** mentett blokk ok **és** `FUN_4AA40()` ok); 3 ha helyette a saját szenzor ok; 2 részleges; **1 semmi** | a fő módszer szintje |
| `gp-31202` | 4 ha (ADC 11 **és** ADC 10 ok **és** külső-szűrő ok); 3 ha csak a két NTC; 2 ha csak a külső-szűrő; 1 semmi | a **kifúvási** módszer szintje |
| `gp-31205` | 3 ha (saját szenzor **és** OAT **és** mentett blokk) ok, különben 1 | a `FUN_43862` ellenőrző kapuja |
| `gp-31203` | 3 ha `FUN_4AA40()` ok, különben 1 | a `FUN_438FA` ellenőrző kapuja |

A használt státuszok: `FUN_45270` = `gp-28639` (OAT), `FUN_3EEEA` = `gp-28668`
(6-os ADC), `FUN_3E912` / `FUN_3E90C` = `gp-28671` / `gp-28672` (11-es és
10-es ADC), `FUN_42BA0` = `gp-28642` (a 39.1 külső-szűrő),
`FUN_4AEF6` = **konstans 3** (a kikapcsoláskor mentett blokk mindig érvényes).

#### `FUN_43E64` — a becslés

Bemenetek a **kikapcsoláskor mentett blokkból** (`gp-32514…32534`, §25.5):
```
gp-26236 <- FUN_4AED4      gp-26230 <- FUN_4AECE      gp-26234 <- FUN_4AEDA
gp-26228 <- FUN_4AEF2      gp-26232 <- FUN_4AEC8      gp-26218 <- FUN_475FA (nap)
```
és a **napterhelési soak-tag**:
```
sp2 = gorbe(cal+1570, OAT)        ; (20,8) (60,20) (80,20) (160,8)
sp1 = gorbe(cal+2262, nap)  [u8]  ; (0,0) (30,50) (60,100)
r26 = (sp1 * sp2) / 100           ; 0 .. 20  =  0 .. +2,0 C
```
Vagyis a napon állt autó indításkor **legfeljebb +2,0 °C-ot** kap rá,
és a súly a külső hőmérséklettől függ (6 °C alatt és 16 °C fölött kisebb).

Az állapotgép a `gp-31268` 0…5. bitjein és a `gp-31213` jelzőn fut, és két
kimenetet állít elő, mindkettő **0,1 °C-ban**:

| kimenet | getter (a `<<6`/`>>6` átskálázás után) |
|---|---|
| `gp-31236` → `gp-26242` → **`gp-29058`** | `FUN_42D8A` |
| `gp-31238` → `gp-26244` → **`gp-29060`** | `FUN_42D84` |

A központi művelet minden ágban ugyanaz az **ambiens felé húzó keverés**:
```
uj = regi * (16 - k) / 16  +  kulso_lassu * k / 16
```
ahol `kulso_lassu` = `FUN_42B8E() >> 6` (a 39.1 szűrt külső hő), és `k`:

| kal. | C346 | `k/16` | hol |
|---|---|---|---|
| `cal.b[657]` | **12** | 0,75 | a fő ág (`gp-31202 ∈ {2,4}`) |
| `cal.b[644]` | 6 | 0,375 | két további ág |
| `cal.b[645]` | 16 | **1,00** | = azonnal az ambiensre ugrik |
| `cal.b[649]` | 11 | 0,69 | a záró korrekció |
| `cal.b[641]` | 4 | 0,25 | a leglassabb ág |

A keverés csak akkor él, ha a tárolt érték **több mint 4,0 °C-kal** a szűrt
külső hő fölött van, **vagy** alatta (`0x440A8`) — vagyis ha a tárolt érték
már nem hihető.

#### Az alapértelmezés — `FUN_443E4`
Ha semmilyen módszer nem érvényes:
```
gp-31236 = gp-31238 = cal.h[290] = 104     ; = 10,4 C
gp-31200 = 2                               ; a legalacsonyabb megbizhatosag
54-es idozito inditasa, periodus cal.h[304] = 6
```
> **Ez az a szám, amit a modul „nem tudom" helyett használ: 10,4 °C.**
> Amíg `gp-31200 == 2`, a 39.4 fizikai modell **nem fut** (a kapu `>= 4`).

### 39.12 Ami ebből még nyitott


| tétel | mi hiányzik |
|---|---|
| ~~`0x43958` / `0x43E64`~~ | **lezárva, §39.11** — ez az indítási becslés, és ez kapuzza a 39.4 modellt |
| `FUN_43862` / `FUN_438FA` | két hihetőség-ellenőrző (`cal.h[292]=48`, `cal.h[294]=80`, `cal.h[302]=220`, `cal.h[334]=2700`) |
| `FUN_4AA54` bemenetei | hét 2 bites CAN-mező a `gp-30488/30489` bájtokból — hogy pontosan melyik zár, az **[E]** |
| a `9472` konstans a 7. tagban | 14,8 °C-os fix vonatkoztatási pont; miért nem az OAT |
| ~~időzítő-egység~~ | **lezárva, §44.3c** — 1 tick = 1 ms, a lassú alap 128 ms |

---

## 40. NAGY KORREKCIÓ: A DID-TÁBLA EL VOLT CSÚSZVA — ÉS A `0x2F` IO-CONTROL  **[B]**

### 40.1 A hiba

A 36. szakasz a DID-táblát `0xB2D0`-tól, 51 bejegyzéssel, `+12`-nél a DID-del
olvasta. A **helyes** tábla:

```
0xB2CC, 48 bejegyzes x 16 bajt:
    +0   u16  DID          (novekvo sorrendben)
    +2   u16  adathossz bajtban
    +4   u32  hozzaferesi / session flagek   (0x2F vagy 0x3F)
    +8   u32  flagek 2                       (mindenutt 0x0F)
    +12  u32  a kezelo fuggveny cime
```

**A bizonyíték a kódból:** `FUN_1CFA8` **bináris keresés** a táblán,
`lo = 0`, `hi = 47` (`movea 47, r0, r18`), az elem szélessége `<< 4` = 16 bájt,
a bázis `mov 0x0000B2CC`, és a kulcs a `sld.hu 0[ep]` — azaz a **`+0` a DID**.
A `FUN_1CF18` a hosszt a `sld.hu 2[ep]`-ből veszi.

**A hiba következménye:** a régi olvasás minden DID-et a **szomszédja
kezelőjéhez** párosított (a `+12`-nél lévő „DID" valójában a következő
bejegyzés `+0`-ja, a `+8`-nál lévő „kezelő" viszont a sajátja). Ezért:

| régi állítás (36-37. szakasz) | valójában |
|---|---|
| `0x9927` = külső hő, `°C = bájt × 0,2 − 16` | **`0x9924`** — a `/2 + 80` skálázás az övé |
| `0x981A` = fúvó kitöltés, `% = bájt × 100/255` | **`0x9805`** — a `× 255/100` az övé |
| `0x9B02` = mód-ajtó #1 | **`0x9B01`** |
| `0x9850` = mód-ajtó #2 | **`0x9834`** |
| `0x9B01` = recirkulációs ajtó | **`0x9B00`** |
| `0x9B03` / `0x9B04` = keverőajtó A / B | **`0x9B02` / `0x9B03`** |

**A szabály egyszerű: minden DID-et egy bejegyzéssel lejjebb kell tolni.**
A §37.2 mérési terve ezzel a régi listával **nem működött volna** — rossz
DID-eket kérdezett volna le.

### 40.2 A javított DID-térkép  **[B]**

Mind a skálázás, mind a jelentés a kezelő-függvényből:

| DID | h | forrás | jelentés | dekódolás |
|---|---|---|---|---|
| `0x9805` | 1 | `gp-23235` | **fúvó kitöltés** | `% = b × 100/255` |
| `0x9834` | 1 | `FUN_27554(4)` | **mód-ajtó #2 (szélvédő)** | `%` közvetlenül |
| `0x9924` | 1 | `FUN_45264` = `gp-29040` | **külső hő (egyesített OAT)** | `°C = (b − 80) × 0,2` |
| `0x9927` | 1 | `FUN_42B9A` = `gp-29068` | **saját külső szenzor, nyers** (§39.1) | `°C = (b − 40) × 0,4` |
| `0x9B00` | 1 | `FUN_27554(0)` | **recirkulációs ajtó** | `%` |
| `0x9B01` | 1 | `FUN_27554(1)` | **mód-ajtó #1 (panel/padló)** | `%` |
| `0x9B02` | 1 | `FUN_27554(2)` | **keverőajtó A** | `%` |
| `0x9B03` | 1 | `FUN_27554(3)` | **keverőajtó B** | `%` |
| `0x9B04` | 1 | `FUN_3E8FA` = `gp-29094` (ADC 11) | **kifúvási hő — padló/szélvédő A** | `°C = (b − 40) × 0,4` |
| `0x9B05` | 1 | `FUN_3E8F4` = `gp-29096` (ADC 10) | **kifúvási hő — panel A** | ugyanaz |
| `0x9B06` | 1 | `FUN_3E906` = `gp-29090` (ADC 13) | **kifúvási hő — padló/szélvédő B** | ugyanaz |
| `0x9B07` | 1 | `FUN_3E900` = `gp-29092` (ADC 12) | **kifúvási hő — panel B** | ugyanaz |
| `0x9961` / `0x9962` | 1 | `gp-28613` / `gp-28612` | napterhelés-származékok **[E]** | nyers |
| `0x9969` | 1 | `FUN_26C64` ← `gp-27076` | tápfeszültség-jellegű **[E]** | nyers |
| `0x9850` | 2 | `gp-23294` | u16 állapot **[E]** | nyers |
| `0x981A` | 4 | `FUN_4BCA6` | 4 bájtos blokk **[E]** | nyers |

**Két fontos következmény:**

1. `FUN_27554(i)` a léptető **tényleges** (visszajelzett) pozícióját adja
   (a `gp-30336`-tól induló, motoronként 52 bájtos leíróból, `FUN_27E9A`),
   szemben a `FUN_27544(i)` = `gp-27012[i]` **parancsolt** értékkel.
   A DID-ek a **tényleges** pozíciót adják — vagyis a mérés a valódi
   ajtóállást mutatja, nem a szabályozó szándékát.
2. **Mind a négy NTC kiolvasható** (`0x9B04`…`0x9B07`), méghozzá úgy, hogy
   a §39.3 párosítása **váltakozva** helyezi el őket:
   `(9B04, 9B06)` = padló/szélvédő, `(9B05, 9B07)` = panel.
   Ez a párosítás **egy 30 másodperces méréssel cáfolható vagy igazolható**
   — és véletlen egyezés gyakorlatilag kizárt.

### 40.3 A `0x2F` IO-control engedélyezett listája  **[B]**

`0xB281`-től **24 × 3 bájt**: `DID_hi, DID_lo, alfunkció`
(a DID **big endian**, azaz drót-sorrendben).

A leíró `0x0ADD4`-nél: `0F 33 2F 04 04 18 21 00` — ez a `0xAD9C`-től induló
szolgáltatás-tábla **7. bejegyzése**, és a **tábla-index** azonosítja a
szolgáltatást (7 = `0x2F`), nem a `2F` bájt (az a **címzési maszk**, §42.4):
- a `0x33` alsó nibble-je = **3** = a kulcs hossza bájtban,
- `0x18` = **24** (halmozott rekord-index; a következő bejegyzésé 48 → 24 db),
- `0x21` = a készlet kezdete a `0xB260` bájt-pool-ban (`0xB260 + 0x21 = 0xB281`).

> **`10 03` NÉLKÜL EGYIK SEM MŰKÖDIK** — az IO-tábla `+12` maszkja
> mindenütt `0x27` = csak extended session. Lásd **§42**.

A keresést a `FUN_1C496` generikus fehérlista-illesztő végzi.

**A 12 vezérelhető DID**, mindegyik `00` (returnControlToECU) és
`03` (shortTermAdjustment) alfunkcióval:

| DID | mi | h |
|---|---|---|
| `0x9805` | **fúvó kitöltés** | 1 |
| `0x9834` | **mód-ajtó #2 (szélvédő)** | 1 |
| `0x9B00` | **recirkulációs ajtó** | 1 |
| `0x9B01` | **mód-ajtó #1 (panel/padló)** | 1 |
| `0x9B02` | **keverőajtó A** | 1 |
| `0x9B03` | **keverőajtó B** | 1 |
| `0x4056` / `0x4057` | konfiguráció **[E]** | 1 |
| `0x9969` | **[E]** | 1 |
| `0xFD0C` | 5 bájtos blokk **[E]** | 5 |
| `0xFD04` / `0xFD06` | **a `0x22` táblában NINCS benne** → csak írható **[E]** | ? |

**Mind az öt léptető és a fúvó vezérelhető.** A `0xFD04` / `0xFD06`
ismeretlen — mérés előtt nem érdemes piszkálni.

### 40.4 A `0x2F` VÉGREHAJTÁSI ÁGA — a vezérlő bájt bizonyítva  **[B]**

A 24 elemű fehérlista mellett van egy **24 elemű kezelő-tábla `0xB004`-nél**,
20 bájtos rekordokkal:
```
+0   u32  a kezelo fuggveny cime
+4   u32  0
+8   u32  0x0F
+12  u32  session-maszk   (mindenutt 0x27, kiveve az FD0C/03: 0x3F)
+16  u32  6
```
**A két tábla indexről indexre egyezik** — a `0xB281` *i*-edik
(DID, alfunkció) párjához a `0xB004` *i*-edik kezelője tartozik. Ez zárja le
a megfeleltetést:

| # | DID | alf | kezelő | # | DID | alf | kezelő |
|---|---|---|---|---|---|---|---|
| 0 | `4056` | 00 | `0x25CF4` | 12 | `9B01` | 00 | `0x2619A` |
| 1 | `4056` | 03 | `0x25D3A` | 13 | **`9B01`** | **03** | **`0x261F8`** |
| 2 | `4057` | 00 | `0x25DF2` | 14 | `9B02` | 00 | `0x26258` |
| 3 | `4057` | 03 | `0x25E38` | 15 | `9B02` | 03 | `0x262B6` |
| 4 | `9805` | 00 | `0x25EF0` | 16 | `9B03` | 00 | `0x26316` |
| 5 | **`9805`** | **03** | **`0x25F38`** | 17 | `9B03` | 03 | `0x26374` |
| 6 | `9834` | 00 | `0x25F9C` | 18 | `FD04` | 00 | `0x263D4` |
| 7 | `9834` | 03 | `0x25FFA` | 19 | `FD04` | 03 | `0x26428` |
| 8 | `9969` | 00 | `0x2605A` | 20 | `FD06` | 00 | `0x26492` |
| 9 | `9969` | 03 | `0x26088` | 21 | **`FD06`** | **03** | **`0x264D8`** |
| 10 | `9B00` | 00 | `0x260DC` | 22 | `FD0C` | 00 | `0x2577A` |
| 11 | `9B00` | 03 | `0x2613A` | 23 | `FD0C` | 03 | `0x257E4` |

#### A kezelő-kontextus
Minden kezelő ugyanazt az `r6` struktúrát kapja (a `0x22` olvasókkal közös):
```
0[ctx]   ptr   a KERES adatbajtjaira (a vezerlo allapot)
4[ctx]   u16   a keres adathossza
8[ctx]   ptr   a VALASZ pufferre
12[ctx]  u16   a valasz hossza  (ezt allitja be a kezelo)
```
Hibajelzés: `FUN_1C408(nrc)`. A használt kódok: **19 = `0x13`**
(incorrectMessageLengthOrInvalidFormat), **49 = `0x31`** (requestOutOfRange).

#### Az ajtók — `0x9B00`…`0x9B03`, `0x9834`, alfunkció `03`
A `0x261F8` (mód-ajtó #1) egy az egyben:
```
ha  hossz != 1        -> NRC 0x13
ha  req[0] > 255      -> NRC 0x31        (u8-nal soha)
r = FUN_276DE(1, req[0])
ha  r == -1           -> NRC 0x31        <-- IDE ESIK A > 100
resp[0] = req[0] ;  valaszhossz = 1
```
és a `FUN_276DE(motor, pct)`:
```
ha  pct >= 101              -> return -1       ; TARTOMANY-ELLENORZES
ha  motor >= gp-27062 (=5)  -> return -1
FUN_27E6A(&leiro[motor], pct * 20)
return (FUN_27554(motor) + 10) / 20            ; a TENYLEGES pozicio
```
`FUN_27E6A(leiro, parancs)` → `cél_lépés = parancs × löket / 2000`, tehát
a `pct × 20` skála pontosan a 4. szakasz `0…2000 = 0…100 %` parancsa.

> **A vezérlő bájt az ajtóknál SZÁZALÉK, 0…100.** Ez már **[B]**, nem [E].
> 100 fölött a modul `0x31 requestOutOfRange`-dzsel utasítja vissza.
> A válasz visszatükrözi a parancsolt bájtot (nem a tényleges pozíciót).

#### A fúvó — `0x9805`
```
03:  ha hossz != 1 -> NRC 0x13
     FUN_52E9E( req[0] * 100 / 255 )        ; a fuvo kitoltese %-ban
     resp[0] = req[0]
00:  FUN_52E9E(0)                           ; FUVO KI
     resp[0] = 0
```
> **A fúvónál a bájt 0…255**, `% = b × 100/255` — pontosan a `0x22` olvasó
> oldal skálája. A `00` alfunkció **kikapcsolja a fúvót**, nem visszaadja.

#### A `00` alfunkció az ajtóknál nem az, aminek látszik
`0x2619A` (`9B01/00`):
```
pos = (FUN_27554(1) + 10) / 20       ; a TENYLEGES pozicio
FUN_276DE(1, pos)                    ; ODA parancsolja, ahol epp all
resp[0] = 0
```
Vagyis a „returnControlToECU" **befagyasztja az ajtót a pillanatnyi
helyére**; a szabályozó a következő ciklusban veszi vissza (lásd 40.7).

#### `0xFD04` — nem végrehajtó, hanem egy 15 bájtos blokk
```
00:  a flash alapertelmezes visszatoltese  (0xBD05, 15 bajt) -> gp-30840
03:  hossz PONTOSAN 15;  req -> gp-30840,  majd visszaolvasva a valaszba
```
#### `0xFD06` — léptető-karbantartás
```
00:  FUN_27804()  -- MIND AZ OT lepteto ujra-referalasa (homing)
03:  hossz PONTOSAN 2:  req[0] = motor index, req[1] = parameter
     FUN_2772E(motor, param, &kimenet)  ->  gp-27058 = 1
```
A `gp-27058` a **kézi léptető-vezérlés** jelzője, amit a meghajtó ciklikus
függvénye (`0x2713A`, `0x271BE`) olvas, és amitől eltér a normál úttól.
**Ez invazívabb, mint a pozíció-parancs — mérésnél nem kell.**

### 40.5 A JAVÍTOTT MÉRÉSI TERV (a §37.2 helyett)

Álló jármű, gyújtás be, motor le, UDS-eszköz, kérés `0x733` → válasz `0x73B`.
A teljes, másolható keretlistát a `python tools/livedata.py plan` írja ki.

**A) Passzív — a panel gombjaival, csak `0x22`**

| gomb (mode) | `0x9B01` (mód-ajtó #1) | `0x9834` (mód-ajtó #2) |
|---|---|---|
| fej (1) | 21 | 40 |
| fej + láb (4) | 33 | 0 |
| láb (2) | 60 | 0 |
| láb + szélvédő (5) | 100 | 65 |
| fej + szélvédő (6) | 9 | 55 |
| mind3 (7) | 45 | 75 |
| szélvédő (8) | 0 | 100 |
| MAX defrost (3) | 0 | 100 |
| **AUTO (9)** | **58 (állandó!)** | számított |

*(a `cal+2320` / `cal+2299` tábla C346-os értékei — a `livedata.py plan`
ugyanezt a `model.py`-ból olvassa ki, hogy ne tudjon elcsúszni)*

Ez igazolja a `cal+2320` / `cal+2299` táblát és az „AUTO-ban beégetett 58"
megállapítást — vagyis azt, amire a 33. patch épül.

**B) Aktív — `0x2F`, ez dönti el a geometriát**

```
fuvo kozepre        05 2F 98 05 03 80
mod-ajto #1 -> 21   05 2F 9B 01 03 15    -> honnan fuj?   (varhatoan ARC)
mod-ajto #1 -> 60   05 2F 9B 01 03 3C    -> honnan fuj?   (varhatoan LAB)
mod-ajto #2 -> 100  05 2F 98 34 03 64    -> honnan fuj?   (varhatoan SZELVEDO)
recirk      -> 100  05 2F 9B 00 03 64    -> hallhato-e a beszivo valtas?
visszaadas          04 2F 9B 01 00   (es igy tovabb mindegyikre)
```
Ez **közvetlen, fizikai bizonyíték** — nem következtetés három egybevágó
nyomvonalból (20.1, 20.2, 38.5), hanem „ezt az ajtót mozgatom, onnan fúj".

**C) A §39.3 NTC-párosítás ellenőrzése — 30 másodperc, csak `0x22`**

Keverőajtók melegre (`9B02`/`9B03` → 100), fúvó középre, majd a mód-ajtó
váltogatása panel ↔ padló között, és `9B04`, `9B05`, `9B06`, `9B07` olvasása.

**A modell jóslata:** a `(9B04, 9B06)` és a `(9B05, 9B07)` pár **külön mozog** —
amelyik kifúváson megy a levegő, az a pár követi a keverőajtót, a másik ott
ragad. Ha mind a négy együtt mozog, a §39.3 párosítás téves.

### 40.6 Tart-e a parancs? — a ciklikus szabályozó  **[B/E]**

A kimeneti fokozat `0x49C1A` **ütemezett** (a `0x0A510`-nél lévő
`(maszk, függvény)` táblában, maszk `0x7B`), és minden ciklusban:

```
allapot = FUN_19608()          ; gp-28410, a tap-/uzemallapot
kapu    = FUN_24B54()          ; gp-27179 == 1

ha allapot == 1 es kapu == 0 :  FUN_49D06()   ; NORMAL SZABALYOZAS -> gp-27012
kulonben ha kapu == 0        :  -- SEMMI --   ; nem nyul a leptetokhoz
kulonben                     :  fix szervizpoziciok
```
A léptető-meghajtó ezután **minden ciklusban** átmásolja
`gp-27012[i] → leíró[i]` (`0x27266`), néhány kapu mellett
(`gp-27061`, `gp-27056`, `FUN_26C04() ∈ {1,2}`, `FUN_19608() != 8`).

**Következmény:** normál üzemállapotban (`FUN_19608() == 1`) a szabályozó
újraszámol és felülírja a diag-parancsot — **a `0x2F` egyetlen kiadása
valószínűleg egy cikluson belül elveszik.**

A `gp-27179` kapu **egy külön szolgáltatásból** állítható (`0x26684` kezelő,
3 bájtos kérés a `0xB5D8`-tól induló 8 elemű rutin-táblában: `req[0]==0` →
bekapcsol, `req[0]==1` → kikapcsol + visszaállítás). Bekapcsolva viszont a
kimeneti fokozat **fix szervizpozíciókat** ír (recirk 100, ajtó#1 60, a többi
0, fúvó 48) — tehát ez sem a diag-pozíció tartása.

> **Gyakorlati következtetés a méréshez: a `0x2F` parancsot ismételni kell**
> (kb. 100 ms-onként), TesterPresent mellett, és `0x22`-vel visszaolvasva
> ellenőrizni, hogy megfogott-e. Ez a professzionális teszterek szokásos
> viselkedése, és **működik függetlenül attól, hogy melyik kapu a helyes.**
> Ha az ismételt parancs mellett az olvasott pozíció beáll, a mérés érvényes.

**Ami itt nyitva maradt:** melyik állapot/kapu-kombináció az, amiben a modul
ténylegesen átadja az ajtókat a diagnosztikának. A `FUN_19608()` értékkészlete
(`1`, `8`, bitmezős) és a `0x26684` rutin azonosítója nincs meghatározva.

### 40.7 Amit a `0x2F`-ből nem néztem át

| tétel | mi hiányzik |
|---|---|
| ~~a `0x2F` végrehajtási ág~~ | **lezárva, §40.4** — a vezérlő bájt `%` (ajtók), `0…255` (fúvó) |
| ~~`0xFD04` / `0xFD06`~~ | **lezárva, §40.4** — 15 bájtos blokk, ill. léptető-karbantartás |
| a parancs tartóssága | melyik állapot/kapu adja át az ajtókat a diagnosztikának — §40.6 |
| `FUN_19608()` értékkészlete | `gp-28410`, bitmezős, `1` és `8` látszik a kódból |
| ~~session / security~~ | **lezárva, §42** — a `0x2F` extended session-t igényel, security nem kell |
| a `0x26684` rutin azonosítója | a `0xB5D8` rutin-tábla 8 bejegyzésének kulcslistája nincs meg |
| ~~`0x0AD9C`…`0x0AE14`~~ | **lezárva, §42.4** — 8 bájtos rekordok, halmozott mezőkkel |
| `0x54780`…`0x54B20` | a `gp-229xx` önteszt-állapotgép (fix szekvencia, nem a `0x2F`) |

---

## 41. EGYBEN-ÉPÍTŐ ÉS ÚJ RECEPT — `tools/buildfw.py`  **[kész]**

### 41.1 A probléma, amit megold

Eddig egy flashelhető fájl előállítása négy eszköz kézi összefűzése volt:
`vbf.py unpack` → `patch_autodist.py build` → `calpatch.py apply` →
`fwcrc.py resign` → `vbf.py pack` → `vbf.py verify`. Minden lépésnél
el lehetett rontani valamit, és **a `resign` elfelejtése U3000-41 hibakódot
okoz**.

A `buildfw.py` ezt egy paranccsá vonja össze, tetszőleges
modosítás-kombinációval:

```
python tools/buildfw.py list
python tools/buildfw.py build autodist dualzone -o F1ET-18D619-AM_COMBO.vbf
python tools/buildfw.py build dualzone --value 64 -o dz64.vbf
python tools/buildfw.py verify F1ET-18D619-AM_COMBO.vbf --mods autodist
```

Az `autodist` a `patch_autodist.py` kód-patch-e; minden más név a
`calpatch.py` receptjeiből jön, tehát **új recept automatikusan
kombinálhatóvá válik**.

### 41.2 Amit garantál

| ellenőrzés | mikor |
|---|---|
| a forrás VBF blokk-CRC-je stimmel | kicsomagoláskor |
| a kód-patch előtt az eredeti 8 bájt a helyén van | `patch_autodist` |
| a célterület (`0x77E00`, `0x77E40`) üres, és a CRC hatókörén belül van | `patch_autodist` |
| minden kalibrációs tétel jelenlegi értéke a várt | `calpatch.Editor` |
| a `--value` tartományon belül | építéskor |
| a belső flash-CRC újraalá van írva | **automatikus, nem felejthető el** |
| **a blokk-CRC `B9A6`** (a 2.5 invariáns) | különben a script **hibával leáll** |
| a VBF `file_checksum` és blokk-CRC visszaolvasva is stimmel | a végén |
| a beakasztás, a rutin és a görbe visszadisszasszemblálva | `autodist` esetén |

**Az eredeti `F1ET-18D619-AM.VBF`-hez sosem nyúl** — csak olvassa.

### 41.3 Visszamenőleges igazolás

A `buildfw.py` a két korábbi, kézzel készült fájlt **bitre azonosan**
állítja elő:

```
F1ET-18D619-AM_AUTODIST.vbf    uj=e3beda7aba27f8ae  regi=e3beda7aba27f8ae  AZONOS
F1ET-18D619-AM_DUALZONE.vbf    uj=f608185e0894c24f  regi=f608185e0894c24f  AZONOS
```
Ez egyszerre igazolja az új eszközt és azt, hogy a régi fájlok helyesek.

### 41.4 Az összevont fájl — `F1ET-18D619-AM_COMBO.vbf`

`autodist` + `dualzone` egy fájlban, **54 bájt eltérés** az eredetitől:

| terület | mi |
|---|---|
| `0x0F8F3` | `cal[569]` a **C346** blokkban: 32 → 48 |
| `0x10CB3` | `cal[569]` a **C346FAP** blokkban: 32 → 48 |
| `0x44C44` | a beakasztás: `jarl 0x77E00` + `st.h r10` |
| `0x77E00` | az új rutin (26 bájt) |
| `0x77E40` | a törésponti görbe (22 bájt) |
| `0x77FF4` | a belső flash-CRC: `D8DF` → `91F2` |

Blokk-CRC `B9A6`, minden ellenőrzés OK. **Nincs flashelve.**

### 41.5 Új recept: `lowspeed_anchor` — és miért NEM ajánlom

A §39.10 `compare` találata alapján készült recept a `cal.h[318]`
alvó modell-tag bekapcsolására (C346: 0, C344GM: 262).

```
python tools/calpatch.py show lowspeed_anchor --variant C346
```

A `cabin.py`-ból számolt előzetes kiértékelés (állandósult állapot, 4 óra,
fúvó ki, nap 0):

| helyzet | előtte | utána | eltérés |
|---|---|---|---|
| álló, saját szenzor +5 °C | 25,4 °C | 25,9 °C | **+0,5 °C** |
| álló, saját szenzor −5 °C | 25,0 °C | 25,0 °C | 0 (az alsó korlát fog) |
| álló, szenzor = OAT | 25,0 °C | 25,0 °C | 0 |
| 50 km/h, szenzor +5 °C | 25,4 °C | 25,4 °C | 0 (a tag kikapcsol) |

**A javaslatom: ne kapcsold be.** Három ok:

1. **A hatása kicsi** — 5 °C-os szenzor-eltérésnél kb. +0,5 °C, azaz a
   különbség tizede. Az effektív időállandója ~83 perc, a meglévő
   4. tag (48 perc) mellett alig módosít.
2. **Rossz irányba húz.** A tag *álló járműben* aktív — pontosan akkor,
   amikor a modul saját külső szenzora a legkevésbé megbízható, mert a
   motortérből átmelegszik. A becslést tehát a hibás érték felé viszi.
3. **Menet közben kikapcsol** (`sebesség > 2 km/h`), tehát épp akkor nem
   hat, amikor a szenzor jó lenne.

A recept azért került be, hogy **dokumentálva és kiértékelve** legyen — nem
azért, hogy alkalmazd. Ha valaha mérés mutatja, hogy a becsült belső
hőmérséklet álló járműben túl lassan követ, akkor van kész eszköz rá.

### 41.6 A flashelési sorrend

```
python tools/buildfw.py build autodist dualzone -o UJ.vbf     # epit + ellenoriz
python tools/buildfw.py verify UJ.vbf --mods autodist          # fuggetlen ujraellenorzes
```
A `buildfw.py` a §9 mindhárom figyelmeztetését automatikusan kezeli
(`resign`, `B9A6`, az eredeti fájl érintetlensége). **A felhasználó
kikötése továbbra is él: csak végleges patchet flashelünk**, és a
véglegességhez az ajtó-geometria mérése (§40.5) kell.

---

## 42. A UDS SESSION- ÉS SECURITY-RÉTEG — és a teljes szolgáltatás-térkép  **[B]**

> **A legfontosabb gyakorlati eredmény ebből a szakaszból:**
> **a `0x2F` IO-control CSAK EXTENDED SESSION-ben működik** (`10 03`),
> a `0x22` olvasás viszont default sessionben is. **SecurityAccess nem kell.**
> A §40.5 mérés default sessionben `0x7E` hibával elhalt volna.

### 42.1 A jogosultság-bájt szerkezete  **[B]**

`FUN_1C250(&flags)` — minden DID- és IO-bejegyzés jogosultság-ellenőrzője:

```
f = flags_bajt              ; DID-tabla +4  /  IO-tabla +12
c = gp-28280                ; a JELENLEGI allapot, ugyanilyen alaku

ha ((f >> 3) & 7)  &  ((c >> 3) & 7)  == 0  ->  NRC 0x7E
ha ( f       & 7)  &  ( c       & 7)  == 0  ->  NRC 0x33
kulonben OK
```

Vagyis egyetlen bájt, **két 3 bites egy-forró maszkkal**:

| bitek | mi |
|---|---|
| 5…3 | az **engedélyezett session-ök** maszkja |
| 2…0 | az **engedélyezett security-szintek** maszkja |

NRC `0x7E` = subFunctionNotSupportedInActiveSession,
NRC `0x33` = securityAccessDenied.

### 42.2 A session-bitek  **[B]**

A `0x10` kezelő (`0x1C286`) a `0xAE14` alfunkció-táblán át a `0xAC90`
átmenet-táblához nyúl (`[0]` = honnan engedélyezett, `[4]` = az új állapot):

| `10 xx` | k | engedélyezett honnan | **új session-bit** |
|---|---|---|---|
| `10 01` default | 0 | bármelyik (7) | **1** |
| `10 02` programming | 1 | bármelyik (7) | **2** |
| **`10 03` extended** | 2 | default vagy extended (5) | **4** |

A security ugyanezen a táblán: `k=4` 1→2, `k=5` 2→4 (két `0x27` szint).
Bekapcsoláskor és timeoutkor `FUN_1C1AC` állítja vissza:
**session = 1, security = 1.**

### 42.3 A tényleges maszkok — mi mihez kell

| hol | flags | session | security | jelentés |
|---|---|---|---|---|
| DID-tábla `+4` (a legtöbb) | `0x2F` | 5 = default + extended | 7 | **`0x22` megy default-ban** |
| DID-tábla `+4` (néhány) | `0x3F` | 7 = mind | 7 | |
| `0xF17C` | `0x17` | 2 = csak programming | 7 | flash-hez való |
| **IO-tábla `+12` (mind a 24-ből 23)** | **`0x27`** | **4 = CSAK EXTENDED** | 7 | **`10 03` kötelező** |
| `FD0C/03` | `0x3F` | 7 = mind | 7 | egyetlen kivétel |

**A security-maszk mindenütt 7**, az alapállapot pedig 1 → `7 & 1 ≠ 0`,
tehát **SecurityAccess sehol nem szükséges** ezekhez a DID-ekhez.

### 42.4 A teljes szolgáltatás-térkép  **[B]**

`FUN_1C542(SID)` egy `0xAD55`-től induló bájttáblán át képezi a SID-et
leíró-indexre (`SID >= 0x86` → nem támogatott; `SID & 0x80` → `SID − 0x40`).
A leírók `0xAD9C`-től, **8 bájtos rekordokkal**; a `[5]` és a `[6:8]` mező
**halmozott** (az *i*-edik szolgáltatás készlete a `[5]_i … [5]_{i+1}`
rekord a `0xB260` bájt-pool `[6:8]_i … [6:8]_{i+1}` szeletében),
a kulcs szélessége `[1] & 0xF`.

```
python tools/uds.py services
```

| SID | szolgáltatás | kulcs | db | engedélyezett alfunkciók / kulcsok |
|---|---|---|---|---|
| `0x10` | DiagnosticSessionControl | 1 | 3 | `01` `02` `03` |
| `0x11` | ECUReset | 1 | 3 | `01` `04` `05` |
| `0x14` | ClearDiagnosticInformation | 3 | 1 | `FFFFFF` |
| `0x19` | ReadDTCInformation | 1 | 4 | `01` `02` `06` `0A` |
| `0x22` | ReadDataByIdentifier | — | — | külön tábla: `0xB2CC`, 48 DID (§40.2) |
| `0x27` | SecurityAccess | 1 | 4 | `01` `02` `03` `04` (két seed/key pár) |
| **`0x2E`** | **WriteDataByIdentifier** | 2 | 8 | `DE00 DE01 F111 F113 F18C FD01 FD0A FD0B` |
| `0x2F` | InputOutputControlByIdentifier | 3 | 24 | a §40.3 fehérlista |
| `0x31` | RoutineControl | — | — | külön tábla: `0xB5D8`, 8 rutin |
| `0x34` | RequestDownload | — | — | flashelés |
| `0x36` | TransferData | — | — | flashelés |
| `0x37` | RequestTransferExit | — | — | flashelés |
| `0x3E` | TesterPresent | 1 | 1 | `00` |
| `0x85` | ControlDTCSetting | 1 | 2 | `01` / `02` |

**Új mellékeredmény:** a `0x2E` WriteDataByIdentifier nyolc DID-je most már
ismert — köztük a `FD0A` (As-Built konfigurációs blokk) és az `F18C`.
Ezek a **konfigurációs** írás csatornái, nem a végrehajtóké.

### 42.5 Az így kiegészült mérési előkészület

```
02 10 03            ; extendedDiagnosticSession   -> valasz: 50 03 ...
02 3E 80            ; TesterPresent, kb. 2 mp-enkent VEGIG
... a 40.5/B parancsok ...
02 10 01            ; vissza default sessionbe a meres vegen
```
A session timeoutja után a modul magától default-ra áll
(`FUN_2306E` → `FUN_1C1DA(1)`), és ezzel a `0x2F` felülírások is
megszűnnek — **ez egyben biztonsági háló**: ha a kapcsolat megszakad,
a modul néhány másodperc múlva visszaveszi a vezérlést.

### 42.6 Amit ez a szakasz javít a korábbiakban

| korábbi állítás | hol | helyesen |
|---|---|---|
| „a leíróban a `2F` = a szolgáltatás azonosítója" | §40.3 | a `+2` bájt **címzési maszk**; a szolgáltatást a **tábla-index** azonosítja (a `0x2F` a 7. bejegyzés) |
| „session / security: a maszk jelentése nyitott" | §40.7 | **§42.1-42.3** |
| „a `0x0AD9C` rekordszerkezete [E]" | §40.7 | **8 bájt, halmozott mezőkkel** — §42.4 |

### 42.7 Ami még nyitott

| tétel | mi hiányzik |
|---|---|
| a `0xB5D8` rutin-tábla 8 bejegyzésének **azonosítói** | a `0x31` kulcsai külön táblában vannak, nem a pool-ban |
| a `0x26684` rutin (a `gp-27179` szervizpozíció-kapcsoló) | melyik rutin-azonosító alá tartozik — §40.6 |
| a `0x27` SecurityAccess seed/key algoritmusa | nem néztem át; **a mérésekhez nem kell** |
| a `0x2E` nyolc DID-jének írás-szemantikája | konfigurációs blokkok, nem végrehajtók |

---

## 43. A NEM-FELEJTŐ TÁR — a `0x29xxx` / `0x58xxx` alrendszer  **[B]**

> **Korrekció.** A korábbi felmérésben ezt a blokkot „panel / kijelző külső
> busza, a klímához nem tartozik" néven soroltam be. **Tévedés volt.**
> Ez az **adat-flash (EEPROM-emuláció)** rétege — és **közvetlenül a §39
> modell működéséhez tartozik**, mert ez menti át a gyújtáson a modell
> állapotát.

### 43.1 Hogyan találtam meg

A léptető-meghajtó ciklikus függvénye (`0x27282`) ezt csinálja:
```
ha gp-29248 != 0 :                      ; "piszkos" jelzo
     ha FUN_299C8(&gp-32464) sikerult :  gp-29248 = 0
```
klasszikus *write-back*. Az `FUN_299C8` a `0x29xxx` szolgáltatás-rétegbe megy,
onnan a `0x58xxx` transzportba, ami a `0xFF434xxx` perifériát hajtja.
A `0x4A068` kikapcsolási rutin ugyanennek a rétegnek a másik belépési pontját
(`FUN_2962C`) használja.

### 43.2 A réteg felépítése  **[B]**

| szint | mi |
|---|---|
| `FUN_2962C(dst, src, ?, n)` | **blokk írása** a RAM-tükörbe, cím- és hossz-ellenőrzéssel (40 hívó) |
| `FUN_299C8(ptr)` | **commit** — a blokk kiírása a tárba |
| `FUN_29ADA(ptr)` | RAM-cím → blokk-index, lineáris kereséssel a `0xC028` táblán |
| `FUN_58BCA(kérés)` | **9 parancsú diszpécser** (`kérés[10]` = 0…8) a transzport felé |
| `FUN_59316/59304/5930A` | nyers 16/8 bites regiszter-írás és -olvasás |

A periféria **[E]**, de a használati minta egyértelmű:
```
FUN_59794(x):                                  ; parancs-kiadas
    write16(0xFF434604, 0xAA00 | x)
    do { r = read16(0xFF434604) } while ((r & 0xFF) != (x & 0xFF))   ; echo-poll
    write16(0xFF434808, 0) ; write16(0xFF43480C, 0)

FUN_5994A(offset, hossz):                      ; blokk-olvasas ECC-ellenorzessel
    write8(0xFF436008, 1)                      ; hibajelzo torlese
    base = *(0xFEDFE6D0)                       ; a tar ablakanak baziscime
    for (a = base+offset; a < base+offset+hossz; a += 2)  read16(a)
    ha (read8(0xFF436004) & 1) : HIBA          ; ECC-hiba
```
`0xAA00` / `0xCC00` / `0xCC01` parancs-magic + visszaolvasásos kézfogás,
külön ECC-hibastátusz — ez **adat-flash szekvenszer**, nem soros EEPROM
és nem a panel busza. A `0xFF434xxx` és `0xFF436xxx` blokkokat a firmware
**kizárólag** innen éri el.

### 43.3 A teljes blokk-térkép — 38 blokk, 310 bájt  **[B]**

```
0xBF84  u32 -> 0xBF90            a (id, hossz) tabla mutatoja
0xBF8C  u16 db = 38,  u16 = 10
0xBF90  38 x (u16 blokk_id, u16 hossz)
0xC028  38 x 8 bajt:  +0 a blokk RAM-kezdocime,  +4 a statusz-bajt cime
```

```
python tools/nvm.py map      # a teljes terkep
python tools/nvm.py layout   # a RAM-tukor cimrendje
python tools/nvm.py hvac     # csak a klimahoz tartozo
```

A RAM-tükör **összefüggő**: `0xFEDFC01D … 0xFEDFC14E` (plusz egy különálló
16 bájtos blokk `0xFEDFC797`-nél), a 38 státuszbájt pedig
`0xFEDFCFA8 … 0xFEDFCFCD` — szintén összefüggő.

| id | hossz | RAM | mi ez |
|---|---|---|---|
| **4** | **60** | `gp-32739` | **DTC-státusz tömb** — 30 × 2 bájt, a `0xBC34` DTC-táblához **[B]** |
| **15** | **30** | `gp-32464` | **léptető-blokk** — 5 motor × 6 bájt **[B]** |
| **16** | **20** | `gp-32534` | **KIKAPCSOLÁSI BLOKK** — a §25.5 / §39.11 soak-adata **[B]** |
| 9 | 16 | `gp-30825` | a `0x4Cxxx` modultól (CAN / A-C környéke) **[E]** |
| 26 | 16 | `gp-32550` | a tárkezelő saját könyvelése **[E]** |
| 21…25 | 5 × 10 | `gp-32474…32514` | öt azonos blokk **[E]** |
| 10…14 | 5 × 8 | `gp-32558…32590` | öt azonos blokk **[E]** |
| 27…38 | 12 × 2 | `gp-32594…32624` | kis számlálók / jelzők **[E]** |

A `4`-es blokk **bizonyítása**: a `0x24166` ciklus 0…29-ig (`addi -30`) lépked
a `gp-32739`-en 2 bájtos lépésközzel, és bejegyzésenként hívja a
`FUN_2962C(&bejegyzés, 0xBC2C, 0, 2)`-t. 30 × 2 = 60 ✓, és a DTC-tábla
(`0xBC34`) is pontosan 30 bejegyzés.

### 43.4 Mit ment át a gyújtáson — és miért számít  **[B]**

A `0x4A068` kikapcsolási rutin a **16-os blokkba** ezt teszi:

| forrás | mi |
|---|---|
| `FUN_42D78()` = `gp-29064` | **`T_levego`** — a §39.4 modell levegő-csomópontja |
| `FUN_42D72()` = `gp-29066` | **`T_tomeg`** — a tömeg-csomópont |
| `FUN_42B94()` = `gp-29070` | a szűrt külső hőmérséklet |
| CAN-bájtok, OAT | a §39.11 becslés többi bemenete |

**Ez zárja be a §39 körét.** Most már látszik, miért ad a `FUN_4AEF6`
konstans 3-at („a mentett blokk mindig érvényes"): mert a modul minden
kikapcsoláskor kiírja, és a tár megőrzi. A §39.11 indítási becslés ebből
dolgozik, és amikor eléri a 4-es szintet, átadja a vezetést a §39.4
fizikai modellnek.

**Gyakorlati következmények:**

- **Modulcsere vagy NVM-törlés után** a §39.11 az alapértelmezésre esik
  (`cal.h[290]` = **10,4 °C**), és amíg a státusz `< 4`, **a §39.4 modell
  nem fut**. A klíma ilyenkor a soak-becslés nélkül, „vakon" indul —
  néhány perc, mire beáll.
- **A léptetők tanult pozíciói is itt vannak** (15-ös blokk). Törlés után a
  modul újra-referál — pontosan ezt csinálja a §40.4-ben azonosított
  `0xFD06/00` IO-control parancs (`FUN_27804`, mind az öt motor).
- **A DTC-k és öregedési számlálóik** a 4-es blokkban — ezért maradnak meg
  akkumulátor-lecsatolás után is.

### 43.5 Amit ez javít a korábbiakban

| korábbi állítás | helyesen |
|---|---|
| „`0x58000–0x5BFFF` = panel/kijelző külső busza, a klímához nem tartozik" | **adat-flash réteg**, és a §39 modell állapotát menti — §43 |
| „a `0xFF434xxx` valószínűleg a kijelző" | **adat-flash szekvenszer** + ECC-státusz **[E]** |

### 43.6 Ami itt még nyitott

| tétel | mi hiányzik |
|---|---|
| a periféria pontos neve | `0xFF434xxx` / `0xFF436xxx`, adatlap nélkül **[E]** |
| a `FUN_58BCA` 9 parancsa | 0…8, csak a 3-as (írás) van végigkövetve |
| a 21…25 és 10…14 blokkcsoportok | öt-öt azonos méretű blokk; a tartalmuk nem azonosított |
| kopáskezelés / redundancia | van-e blokk-váltogatás, és hány írást bír |
| a `0x54000–0x57FFF` panel/HMI réteg | ez marad az egyetlen nagy, fel nem tárt alkalmazás-közeli blokk |

---

## 44. AZ UTOLSÓ NAGY BLOKK — `0x53F00…0x57FFF`  **[B/E]**

Ez volt a felmérésben (43. szakasz utáni állapot) az egyetlen megmaradt,
alkalmazás-közeli fel nem tárt terület. Kiderült, hogy **nem egy dolog,
hanem négy külön alrendszer**, és a „panel/HMI" címke csak az elsőre igaz.

| tartomány | mi |
|---|---|
| `0x53F00…0x541A0` | **megvilágítás-PWM meghajtó** (44.1) |
| `0x541A2…0x54720` | a `gp-229xx` állapotgép inicializálása + a belső flash-CRC (`FUN_542C8`, `0x11FC6` tábla) |
| `0x54728…0x55450` | **a `gp-229xx` állapotgép** (44.3) |
| `0x55468…0x55550` | **libc**: `memcmp`, `memset`, `memcpy` |
| `0x55540…0x57FFF` | a §43 adat-flash **transzportja** (`0xFEDFE6D4`, `0x59xxx`) |

### 44.1 A megvilágítás-PWM meghajtó — `FUN_540AE`  **[B]**

67 hívó, és most már teljesen olvasható:

```
FUN_540AE(csatorna, ertek)  ->  FUN_5410A:

ha ertek == 0 :  kitoltes = 0
kulonben:
    lo = *gp-23132[csatorna]                  ; u16 also hatar
    hi = *gp-23040[csatorna]                  ; u16 felso hatar
    v  = lo + (ertek - 1) * (hi - lo) / 1022  ; 1..1023 -> [lo, hi]
    tipus = tabla_0x11FAE[csatorna]           ; 0, 1 vagy 2
    d = (tipus == 1) ? gp-30802 : gp-30801    ; a GLOBALIS fenyero, 0..100 %
    kitoltes = max(1, v * d / 100)
ha kitoltes > 255 : kitoltes = 0xFFFF         ; telites
FUN_2B902(csatorna, kitoltes)                 ; <<< a PWM-periferia
```

**A kimenet ugyanaz a `FUN_2B902` PWM-driver, amin a fúvó megy** (18-as
csatorna, §39.2 / `FUN_52E9E`). Egy periféria, megosztott csatornatérrel.

#### A globális fényerő
```
FUN_54074:
   gp-23220 = FUN_26C56()                 ; a nyers dimmer-jel (gp-27072)
   gp-30802 = gorbe(0xD068, gp-23220)     ; B csoport
   gp-30801 = gorbe(0xD078, gp-23220)     ; A csoport
```
| görbe | töréspontok | jelleg |
|---|---|---|
| `0xD068` (B) | (85,255) (105,155) (130,100) (160,72) (190,30) | **erősen csökkenő** |
| `0xD078` (A) | (85,100) (105,100) (130,100) (160,100) (190,50) | 190-ig lapos, utána fele |

Vagyis a **B csoport követi a műszerfal-tompítást**, az **A csoport nem** —
csak a legsötétebb fokozatnál feleződik. Klasszikus szétválasztás:
*háttérvilágítás* (tompítható) kontra *állapot-LED* (mindig látható).

#### A csatornatérkép  **[B]**

A felső határok a `0x11FA4…0x11FAC` konstansokból, 0xFFFF-hez viszonyítva:

| csatorna | csoport | felső határ | |
|---|---|---|---|
| 0 | A | `0x5555` = 21845 | **33 %** |
| 1, 2, 7, 8, 9, 10, 20 | A / B | `0x1999` = 6553 | **10 %** |
| 3, 4, 5, 6 | B | `0xB332` = 45874 | **70 %** |
| 11…17, 21 | B | `0xBFFF` = 49151 | **75 %** |
| 22 | B | `0x9999` = 39321 | **60 %** |
| **18, 19** | — | **lo = hi = 0** | **kizárva** |
| 23, 24, 25 | A | `0x1999` | 10 % |

**A 18-as csatorna szándékosan ki van zárva** (`lo = hi = 0`, `0x54046`) —
mert az a **fúvó**. A megvilágítás-driver soha nem nyúlhat hozzá.
Ez független megerősítése a §39.2 fúvó-azonosításának.

### 44.2 A libc  **[B]**

| függvény | mi |
|---|---|
| `FUN_554F2(dst, src, n)` | `memcpy`, szó-optimalizált, illesztés-ellenőrzéssel |
| `FUN_5548A(dst, c, n)` | `memset`, a bájtot 32 bitre szórva |
| `FUN_55468(a, b, n)` | `memcmp` |

Ezek magyarázzák a régió magas hívás-számát (28 + 25 + 5 xref), és ezért
látszott „HMI-nek" a xref-súlyozott lefedettségben.

### 44.3 A `gp-229xx` állapotgép — utólagos szárítás  **[B a mechanizmus, E a cél]**

Ez a régió magja. **Ami a kódból bizonyított:**

```
FUN_545CE   : inicializalas fix konstansokkal
              gp-22911 = 45   -> mod-ajto #1 celpozicio (%)
              gp-22912 = 49   -> recirkulacios ajto (%)  == FRISS LEVEGO (28. szakasz)
              gp-22918 = 89, gp-22919 = 117, gp-22910 = 7200 (idozito)
              gp-22932 = 0    -> allapot

0x547BA     : a leptetok parancsolasa
              FUN_2752E(1, gp-22911 * 20)     ; mod-ajto #1 -> 45 %
              FUN_2752E(0, gp-22912 * 20)     ; recirk -> 49 % (friss)
              FUN_52E9E(gp-22918)             ; A FUVO BEKAPCSOLASA
              idozitok 208 / 209 inditasa

FUN_54BF2   : futasi kapu -- csak akkor mehet, ha
              FUN_26986() == 0  es  FUN_52218() == 0  es  FUN_4DDB8() == 0
              (az utolso a MAX defrost jelzoje, 0x4DD42)

FUN_54B64   : "kell-e nekem a fuvo?" -- a fuvo-vezerlo (0x52ED0) kerdezi
              ha (NVM-konfig bit) es gp-22932 in {4,5,6,7} : return 1
```

Az állapotgép ezen kívül **NVM-blokkokat ír** (`FUN_2962C` a `gp-32604`,
`gp-32606`, `gp-32608`, `gp-32610`, `gp-32612`, `gp-32614`, `gp-32616`
címekre) — ezek a §43 térkép **2 bájtos blokkjai (id 27…38)**. Ezzel a
§43.6 egyik nyitott tétele lezárul: **a kis NVM-blokkok ehhez az
állapotgéphez tartoznak** (számlálók, utolsó lefutás állapota).

**Ami [E]:** a *célja*. A profil viszont egyértelmű — friss levegőre állít,
a mód-ajtót középre viszi, bekapcsolja a fúvót, MAX defrost alatt tiltott,
NVM-ből engedélyezhető, és számlálókat vezet. Ez az **utólagos szárítás
(after-run / párologtató-szárítás)** klasszikus mintája.


#### 44.3b A mechanizmus részletesen — és egy KORREKCIÓ  **[B]**

> **Korrekció:** a §44.4 / §45.2 azt írta, hogy a `gp-32548` **bit0 vagy bit1
> bármelyike** engedélyezi *ugyanazt* a funkciót. **Nem.** A ciklikus feladat
> (`0x546E8`) így néz ki:
> ```
> ha FUN_29EDE() == 1 :   FUN_55070() ; FUN_54728()    ; << A gep, allapot = gp-22932
> ha FUN_29EEE() == 1 :   FUN_550A2() ; FUN_54946() ; FUN_55224()
>                                                      ; << B gep, allapot = gp-22931
> kulonben:               gp-29485 = 0 ; gp-22936 = 0
> ```
> **Két külön, szerkezetileg AZONOS rutin**, külön állapotváltozóval, külön
> időzítőkkel (207/208/209 vs 210/211/…) és külön NVM-számlálóval. A `bit0`
> az A-t, a `bit1` a B-t kapcsolja.

**A két rutin konstansai gyakorlatilag azonosak** (`FUN_545CE` / `FUN_5463C`):

| | A gép | B gép |
|---|---|---|
| mód-ajtó #1 célpozíció | 45 % | 45 % |
| recirkulációs ajtó | **49 % (friss levegő)** | 49 % |
| fúvó, 1. fázis | 89 | 89 |
| fúvó, 2. fázis | 39 | 39 |
| fő időkorlát | 7200 | 7200 |
| eltérés | `gp-22922 = 74`, `gp-22916 = 1` | `gp-22904 = **77**`, `gp-22898 = **3**` |

Mindössze **két konstans** különbözik — vagyis ugyanannak a rutinnak két
paraméterezése (rövid/hosszú, vagy két eltérő kiváltó feltétel).

**Az A gép kilenc állapota** (`0x54728`, ugrótábla `gp-22932` szerint):

| áll. | mi történik | tovább |
|---|---|---|
| 0 | alvó | a kiváltó (lent) → 1 |
| 1 | 207-es időzítő indítása (`gp-22913` = 4) | → 2 |
| 2 | várakozás a 207-esre | → 3 |
| 3 | `FUN_54C3A()` dönt | ≠0 → **4**, 0 → 8 (kihagyás) |
| 4 | **a jelenlegi pozíciók mentése** (`gp-22929`, `gp-22930`), majd mód-ajtó #1 → 45 %, recirk → 49 %, **fúvó → 89**, 208/209 időzítő | → 5 |
| 5 | fut; 209 lejár → parancsok ismétlése; 208 lejár vagy `FUN_4B08C()` → 7 | → 7 |
| 6 | második fázis, **fúvó → 39** (halkabb) | → 7 |
| 7 | **helyreállítás**: ajtók vissza a mentett pozícióba, **fúvó KI**, `gp-32600` NVM-blokk = 0 | → 8 |
| 8 | takarítás (`FUN_1D930`), állapot = 0 | → 0 |

**A kiváltó** (`FUN_54EC4`, minden ciklusban fut):
```
gp-29310 == 0        ; egy CAN-jel EL (nem jart le a 146-os timeout)
gp-29326 == 0        ; ugyanaz a jel
gp-29311 in {0, 1}   ; egy 3 bites CAN-mezo a gp-30502 bajtbol
gp-22932 == 0  es  gp-22931 == 0    ; egyik gep sem fut
+ FUN_552FA() / a gp-22936 szamlalo feltetele
-> gp-22932 = 1
```

**Hogyan kapja meg a fúvót:** a fúvó-vezérlő (`0x52ED0`) minden ciklusban
megkérdezi a `FUN_54B64()`-et:
```
ha (bit0 vagy bit1)  es  gp-22932 in {4,5,6,7}  vagy  gp-22931 != 0 :
     return 1     -> a kert fuvo-kitoltes atmegy
kulonben  return 0 -> a fuvo 0-ra kenyszeritve
```
Ez a kulcs: **a rutin ezen a kapun keresztül tudja járatni a fúvót akkor is,
amikor a rendszer egyébként „ki van kapcsolva".**

**A megszakítási kapu** (`FUN_54BF2`, a `FUN_54F54`/`FUN_54F7C` hívja):
```
csak akkor mehet, ha  FUN_26986() == 0  es  FUN_52218() == 0  es
                      FUN_4DDB8() == 0        ; << MAX defrost jelzo
```
Ha bármelyik feltétel megbillen, a gép **8-as állapotba ugrik** (megszakítás),
és a 7-es állapot már visszaállította az ajtókat.


#### 44.3c AZ IDŐZÍTÉS KALIBRÁLVA — és amit ez a cél-értelmezésről mond  **[B]**

A §39.12 utolsó nyitott tétele („a `0x19E52` ms-egyenértéke nincs igazolva")
ezzel lezárul.

**A két időalap** (`FUN_191E8`, `0x19208`):
```
gp-29916 += 1                              ; GYORS szamlalo, minden tick
ha (gp-29916 & 0x7F) == 0 :  gp-29914 += 1 ; LASSU: minden 128. tick
```
A `FUN_19E52(periodus, id)` a `periodus` **bit15-jével** választ a kettő
között (`0x19E6E`).

**A tick hossza:** a firmware összes közvetlen időzítő-periódusa kerek
ezredmásodperc — 50, 100, 125, 250, 500, 750, 1250, 2500 (a `1250` egyedül
110 helyen, a CAN-timeoutokban). Ez csak akkor áll össze, ha
**1 tick = 1 ms**, tehát a **lassú alap = 128 ms**.

**Az A rutin tényleges időzítése:**

| időzítő | periódus | alap | idő |
|---|---|---|---|
| 207 (1→2 állapot) | `gp-22913` = 4 | lassú | **0,5 s** indulási késleltetés |
| **208 (a ciklus hossza)** | `gp-22919` = 117 | lassú | **≈ 15,0 s** |
| 209 (parancs-ismétlés) | 62 | gyors | 62 ms |

> **A teljes ciklus ~15 másodperc**, fúvó **89 %**-on.
>
> **Ez érdemben gyengíti a „párologtató-szárítás" értelmezést.** A Ford saját
> kézi eljárása (§46.4) **25 perc** fúvatást ír elő; 15 másodperc alatt semmi
> nem szárad ki. A rutin inkább egy **rövid, nagy légáramú öblítés** — a cél
> ismét **[E]**, és most már *kevésbé* valószínű, hogy szárítás.

#### 44.3d A futási feltételek — mind CAN-ról jönnek  **[B a szerkezet, E a jelentés]**

A 3. állapot `FUN_54C3A()`-ja **kilenc feltételt** vizsgál, és mind
teljesülnie kell:

```
FUN_54BF2() != 0                      ; a futasi kapu (MAX defrost stb.)
FUN_550D4() != 0
FUN_54E6C()  >  gp-22920/22921 (10/15) ; = (gp-29253 - 40),  80-ra vagva
FUN_54E4A()  >  gp-22910 (7200)        ; = f(gp-29252), negyzetes
FUN_54EA0()  >  gp-22922 (74)          ; = gp-28788, ha < 101
FUN_54DF2()  <  gp-32614   [NVM]       ; futas-szamlalo korlat
FUN_55150()  <  3
gp-32616 [NVM] == 0                    ; "mar futott ebben a ciklusban"
FUN_54C1C()  == 0   es   gp-30798 == 0
```

A `gp-29253`, `gp-29252` és `gp-28788` **mind CAN-ról érkezik**
(a `0x21A36`…`0x21AF6` kicsomagolók, 7 bites mezők a `gp-30577` és
`gp-30510` bájtokból).

**A `gp-28788 > 74` (és `< 101`) feltétel a legbeszédesebb:** egy 0…100
tartományra vágott érték, aminek **74 fölött** kell lennie. Ez a profil egy
**relatív páratartalom** jele — és 74 % fölötti páránál indítani egy
nagy légáramú öblítést értelmes lenne. **De a CAN-üzenetet nem azonosítottam,
tehát ez [E].**

A `gp-32614` / `gp-32616` NVM-blokkok (a §43 27-es/28-as blokkja) **korlátozzák,
milyen gyakran futhat** — a 7-es állapot nullázza őket a végén.

### 44.4 Új: a `26`-os NVM-blokk a konfigurációs rekord  **[B]**

`FUN_29DF0` egy 3 bájtos beérkező rekordot vet össze a
`gp-32550 / gp-32549 / gp-32548` hármassal, és eltérésnél állapotgépet indít
a frissítésére. Ezek a §43 **26-os blokkjának** (16 bájt) első három bájtja.

| bájt | hol használják |
|---|---|
| `gp-32549` | az **A/C állapotgép** (`0x39762`), értékek 1 és 2 — üzemmód-választó |
| `gp-32548` | bitenként, `FUN_29EDE` / `FUN_29EEE` — **a 44.3 funkció engedélyezése** |
| `gp-32550` | a rekord első bájtja |

Vagyis a 26-os blokk a **kereskedői / vevői konfiguráció**: ez kapcsolja be
az utólagos szárítást, és ez állítja az A/C egyik üzemmódját. Nem
kalibráció (nem a `cal` blokkban van), hanem **NVM-ben tárolt, írható
beállítás** — elvileg a `0x2E` WriteDataByIdentifier vagy a `0x2F` `FD04`
úton elérhető (§42.4).

### 44.5 Amit ez javít a korábbiakban

| korábbi állítás | helyesen |
|---|---|
| „`0x54000–0x57FFF` = panel/HMI réteg" | **négy alrendszer**: megvilágítás-PWM, `gp-229xx` állapotgép, libc, adat-flash transzport — §44 |
| §43.6: „a 27…38 kis NVM-blokkok nem azonosítottak" | **a `gp-229xx` állapotgéphez tartoznak** — §44.3 |

### 44.6 Ami itt még nyitott

| tétel | mi hiányzik |
|---|---|
| a `gp-229xx` állapotgép **célja** | **§48**: nem kikapcsolás utáni, hanem **menet közbeni** rutin; a `0x300` bit6 jelentése [E] |
| a 26-os blokk írási útja | melyik DID / rutin írja a konfigurációs rekordot |
| a 26 csatorna fizikai megfeleltetése | melyik LED melyik gomb — csak méréssel vagy panel-szétszedéssel |
| `FUN_26986` / `FUN_52218` | a 44.3 kapu másik két feltétele |

---

## 45. MIT LEHET TÉNYLEGESEN FEJLESZTENI — bizonyíték-alapú katalógus  **[B]**

A §31 katalógus a megértés korai szakaszában készült. A §39-44 után ez a
szakasz **méréssel vagy változat-összevetéssel alátámasztott** listát ad,
és megmondja, **mihez NEM szabad nyúlni**.

### 45.1 A legfontosabb felismerés: hol szabad hangolni

Végigvetettem mind a hat változat kalibrációját az általunk **értett**
paramétereken (a `tools/calmap.py`-jal):

| paraméter-csoport | eltér a hat változat között? |
|---|---|
| **a fizikai modell magja** — `cal.h[308] 310 312 316 320 322 324 326 330 332`, a lépésköz `288`, a kimeneti periódus `300`, az alapértelmezés `290` | **NEM. Mind a hatban bitre azonos.** |
| **szűrők és súlyok** — `314 318 633 636 643 646 647 655 657` | igen |
| **dual-zone / keverés** — `569 571 573 580 584` | igen |

> **A Ford ugyanazt a fizikát használja minden karosszériához, és csak a
> reakcióidőket és a súlyozást hangolja piaconként.** Ez pontosan megmondja,
> hol van mozgástér: **a fizikai modell magjához nem szabad nyúlni** (az nem
> ízlés kérdése, hanem az utastér hőtana), a szűrőkhöz és súlyokhoz igen.

És minden eltérő érték **gyárilag validált alternatíva** — nem tippelés:

| cal | mit állít | C346 | a többi változat |
|---|---|---|---|
| `b[633]` | modell / soak súly | **4** (75 % modell) | C344GM/CM **6**, C346NA/C344NA **8** (50/50) |
| `b[647]` | a becslés hűlési szűrője | **4** (2,0 s) | C344* **2** (0,5 s), C346NA **1** (0,25 s) |
| `b[646]` | napszenzor-szűrő | **10** (4,3 perc!) | C346NA **4** (4 s), C344NA **3** (2 s) |
| `b[643]` | fúvó-szűrő | **4** | C344* **1** |
| `b[636]` | külső-hő szűrő álló járműnél | **3** | C346NA **4**, C344NA **1** |
| `h[314]` | kifúvási hő súlya a becslésben | **115** | C344GM/CM **134** |
| `h[318]` | alvó alacsony-sebességű tag | **0** | C344GM/CM **262** |
| `b[655]` | felső korlát a külső hő felett | **12 °C** | C344NA **4 °C** |
| `b[657]` | ambiens-keverés | **12** | C344NA **2** |

### 45.2 ÚJ: egy kikapcsolt gyári funkció — flashelés NÉLKÜL  **[B]**

Ez a §44 legértékesebb hozadéka, és a katalógus élére kívánkozik.

A §44.3 `gp-229xx` állapotgép **kész, gyárilag megírt funkció**: friss
levegőre állít (recirk 49 %), a mód-ajtót 45 %-ra viszi, **bekapcsolja a
fúvót**, MAX defrost alatt tiltott, számlálókat vezet NVM-ben. A profil az
**utólagos szárítás** (párologtató-szárítás / after-run) — **[E]** a cél,
**[B]** a mechanizmus.

**Ebben a modulban ki van kapcsolva**, és a kapcsoló nem a kalibrációban van,
hanem az **NVM 26-os blokkjában** (§44.4):

```
gp-32548  bit0 (FUN_29EDE)  ->  az A rutin EL  (FUN_54728, gp-22932)
gp-32548  bit1 (FUN_29EEE)  ->  a B rutin EL  (FUN_54946, gp-22931)
```
**Két külön, azonos felépítésű rutin** — a részletes lefutás a §44.3b-ben.

És ez a bájt a **`0xFD0A` As-Built blokk 3. bájtja**, amit a `0x2E`
WriteDataByIdentifier ír (`FUN_258FA` → `FUN_29DF0`, kezelő-tábla `0x0AF00`).

| művelet | mi kell hozzá | kockázat |
|---|---|---|
| **olvasás** `22 FD 0A` | **default session, semmi más** | **nulla** |
| írás `2E FD 0A …` | `10 02` programming session **+ SecurityAccess szint 2** | As-Built programozás |

A `0xFD0A` írás-flagje `0x12` = session-maszk 2, **security-maszk 2** — az
alapszint 1, tehát `2 & 1 = 0` → `NRC 0x33`. **SecurityAccess kell.**

> **De nem nekünk kell megfejteni.** Ez a szokásos Ford As-Built programozás,
> amit a **FORScan és az UCDS már tud**. Vagyis a funkció bekapcsolásához
> **nem kell flashelni, és nem kell a seed/key algoritmus** — elég egy
> As-Built szerkesztő.

```
python tools/livedata.py asbuilt              # a keret + a magyarazat
python tools/livedata.py asbuilt <88 bajt>    # a kiolvasott blokk dekodolasa
```

**Az első lépés kockázatmentes:** olvasd ki a `22 FD 0A`-t, és nézd meg a
3. bájtot. Ha `0x00`, a funkció alszik. Írd le a teljes 88 bájtot, mielőtt
bármit módosítasz.

A `gp-32549` (a rekord 2. bájtja) ugyanezen az úton az **A/C állapotgép egyik
üzemmódját** állítja (`0x39762`, értékek 1 és 2) — szintén érdekes terep.

### 45.3 A katalógus — érték / kockázat / készültség szerint

#### A) Kész, ellenőrizve, csak a mérés hiányzik

| # | mi | nyereség | állapot |
|---|---|---|---|
| 1 | **AUTO adaptív légelosztás** (§33) | **a legnagyobb funkcionális nyereség** — ma AUTO-ban a mód-ajtó beégetett 58 %, nem alkalmazkodik | `COMBO.vbf`, 54 bájt, `B9A6` OK |
| 2 | **Dual-zone szétválasztás** (§34) | a jobb oldal kevésbé követi a balt | ugyanabban a fájlban |

**Blokkoló:** az ajtó-geometria mérése (§40.5). Enélkül az 1-es patch görbéje
elvi feltevésen áll.

#### B) Flashelés nélkül, UDS-en

| # | mi | nyereség | mi kell |
|---|---|---|---|
| 3 | **utólagos szárítás bekapcsolása** (§45.2) | egy komplett, alvó gyári funkció | As-Built írás (FORScan) |
| 4 | `gp-32549` A/C üzemmód | ismeretlen hatás **[E]** | ugyanaz |

#### C) Kalibrációs hangolás, gyárilag validált értékekkel

| # | mi | mikor érdemes | recept |
|---|---|---|---|
| 5 | `cal.b[633]` 4 → 6/8 | ha a becslés indulás után „ragad" | új |
| 6 | `cal.b[647]` 4 → 2 | ha lassan veszi észre a lehűlést | új |
| 7 | `cal.h[314]` 115 → 134 | ha a becslés nem követi a kifúvást | új |
| 8 | `cal+2060` AUTO fúvógörbe | ha AUTO-ban túl hangos | `autoblower_quiet` **kész** |
| 9 | `cal.b[646]` 10 → 4 | **kis hatás** — csak a §39.6 alsó korlátot érinti, egyetlen olvasója van | — |
| 10 | `cal.h[318]` 0 → 262 | **NEM ajánlott** (§41.5) | `lowspeed_anchor` kész |

#### D) Új kód — most már megvalósítható

| # | mi | miért lehet most |
|---|---|---|
| 11 | **sebességfüggő fúvó-trimm** (§31.5) | a szűrt sebesség kész (`FUN_4997E`), a `cal.h[330]` mutatja, hogy a fizika már számol vele |
| 12 | **AUTO LED-származtatás** (§20.4) | az AUTODIST patch után a mód-ajtó változik, tehát a LED-ek követhetnék |
| 13 | `gp-28666` kihasználatlan csatorna (§31.2) | minden ciklusban kiszámolódik, senki nem olvassa |

### 45.4 AMIHEZ NE NYÚLJ

| tétel | miért |
|---|---|
| `cal.h[308] 310 312 316 320 322 324 326 330 332`, `288`, `290`, `300` | **a fizikai modell magja** — mind a hat változatban azonos; ez hőtan, nem ízlés |
| `cal.b[513]` MAX defrost fúvó-minimum | **biztonsági** funkció (szélvédő-párátlanítás) |
| `0xFD04` / `0xFD06` IO-control | 15 bájtos RAM-blokk, ill. léptető-kézivezérlés — méréshez nem kell, hatásuk ismeretlen |
| `cal.h[318]` | a legkevésbé megbízható szenzor felé húz (§41.5) |

### 45.5 Az ajánlott sorrend

1. **`22 FD 0A` kiolvasása** — most, kockázat nélkül, és a 88 bájt leírása.
   Ez megmondja, alszik-e az utólagos szárítás.
2. **A §40.5 mérés** — álló jármű, `10 03`, ~10 perc. Ez lezárja az
   ajtó-geometriát, és ezzel a `COMBO.vbf` véglegessé válik.
3. **A `COMBO.vbf` flashelése** — a `buildfw.py` mindent ellenőriz.
4. Ha az 1. pont szerint alszik: **az utólagos szárítás bekapcsolása**
   As-Built szerkesztővel.
5. Mérés után, ízlés szerint: a C) csoport kalibrációs finomhangolása.

---

## 46. KÜLSŐ FORRÁSOKKAL VALÓ ÖSSZEVETÉS  **[külső]**

2026-08-26-án két nyelvi modellel (Gemini, ChatGPT) kerestettünk rá a
megállapításainkra. Ez a szakasz **csak azt rögzíti, amit külső forrás
megerősít vagy cáfol** — a forrás minősége szerint jelölve.

> **Módszertani megjegyzés.** A promptba szándékosan tettünk kontroll-kérdést
> (a regionális kalibrációra, amire nem várható publikus forrás). A Gemini
> erre és a SecurityAccess-kérdésre is **magabiztos, forrás nélküli választ**
> adott, a ChatGPT viszont „NEM TALÁLTAM FORRÁST"-ot. Ahol a kettő
> ellentmond, ott a **forrással alátámasztott** és a **saját firmware-ből
> ellenőrizhető** állítást fogadjuk el.

### 46.1 MEGOLDVA: az ajtó-geometria  **[külső forrás + kód]**

A Ford workshop manual DTC-táblája (2012 Focus DATC) a következőt adja:

| DTC | hivatalos Ford szöveg | a mi motorunk | státusz |
|---|---|---|---|
| **B1081** | *Left Temperature Damper Motor* | **2 = keverőajtó A (bal)** | **MEGERŐSÍTVE** |
| **B1082** | *Right Temperature Damper Motor* | **3 = keverőajtó B (jobb)** | **MEGERŐSÍTVE** |
| **B1083** | *Recirculation Damper Motor* | **0 = recirkulációs ajtó** | **MEGERŐSÍTVE** |
| **B1086** | *Air Distribution Damper Motor* | **1 = mód-ajtó #1** | **MEGERŐSÍTVE** |
| B1085 (2012) | *Defroster Damper Motor* | 4 = mód-ajtó #2 | lásd 46.2 |

**A Ford saját elnevezése is egybevág a miénkkel:** a `B1086` „Air
Distribution Damper Motor", a `B125B` pedig „Air Distribution Damper **B**
Motor" — pontosan a mi „mód-ajtó **#1** / **#2**" felosztásunk.

A Focus III DATC alkatrészlistája öt aktuátort sorol:
*Blend Door Actuator – Registor-Footwell Door*, *Blend Door Actuator –
Defrost Door*, *Temperature Blend Door Actuator – Driver Side*,
*Temperature Blend Door Actuator – Passenger Side*, és az
*air inlet / recirculation* — **öt, ahogy a firmware-ben is.**

> **Ez feloldja a 33. patch fő blokkolóját.** Az AUTO-elosztás patch azon a
> feltevésen állt, hogy az **1-es motor a panel↔padló ajtó**. A Ford szerint
> a `B1086` = „Air Distribution Damper Motor", a hozzá tartozó aktuátor pedig
> a **register/footwell** ajtó. **Ez pontosan az, amit a patch feltételezett.**

### 46.2 KORREKCIÓ: a `B125B` neve  **[külső forrás]**

A §38.5 és a `tools/uds.py` „szélvédő-ajtó" néven hivatkozott rá. A **2018-as
Focus DATC** DTC-indexe szerint a hivatalos név:

```
B125B:00  =  Air Distribution Damper "B" Motor
```

nem „Defroster Damper Motor". A **2012-es** dokumentációban a külön defrost
aktuátor kódja **`B1085`** volt — a facelift átnevezte és átszámozta.

**Hogy fizikailag a szélvédő-ajtót hajtja-e, arra külső forrás nincs.**
A saját kódunk viszont ezt mondja (`cal+2299`, mód → ajtó#2 tábla):

| mód | 3 = MAX defrost | 8 = szélvédő | 1 = fej | 2 = láb |
|---|---|---|---|---|
| ajtó#2 | **100** | **100** | 40 | **0** |

Csak és kizárólag a két szélvédő-módban megy 100-ra, láb módban 0.
**A firmware szerint ez a szélvédő-ajtó** — de a *név* „Air Distribution
Damper B", és a doksiban ezt így kell keresni.

### 46.3 NAGY KORREKCIÓ: az `F1ET-18D619-AM` nem alkatrészszám  **[külső + saját kód]**

Egy 2016-os Focus III UCDS-dump szerint:
```
F110  On-line Diagnostic Database Reference   = DS-F1ET-18C612-AG
F111  ECU Core Assembly Number                = F1ET-14F165-DC
F113  ECU Delivery Assembly Number            = F1ET-18C612-DH
F188  Vehicle Manufacturer ECU Software Number = F1ET-18D619-AM
```

**Ezt a saját binárisunkból ellenőriztük**, és stimmel — a `0x0BCBC`-nél:

```
0BCB0  .. .. .. .. .. .. .. .. .. .. .. .. F1ET
0BCC0  -18D619-AM......
0BCD0  ....DS-F1ET-18C6
0BCE0  12-AG.......BE05
0BCF0  F012............
```

Vagyis a flash-ben **csak a szoftver-szám (`F188`) és a diagnosztikai
adatbázis-hivatkozás (`F110`) van**. A `F111` kezelő (`0x253FE`) a
**`0x7FC00`** címről olvas 24 bájtot — ami **kívül esik a VBF-blokkunkon**
(`0x8000 … 0x77FFF`), tehát a **per-darab azonosítók külön flash-területen**
vannak, amit a VBF nem ír felül.

| | helyesen |
|---|---|
| `F1ET-18D619-AM` | a **szoftver/stratégia** száma (`F188`) — ezt fejtettük vissza |
| `F1ET-18C612-xx` | a modul **hardver/delivery** száma |
| `F1ET-14F165-xx` | a **core assembly** száma |

**A projekt pontosabb megnevezése:** *HVAC `18C612`, stratégia
`F1ET-18D619-AM`.*

### 46.4 Az afterblow — a koncepció igazolt, a Ford-implementáció nem

| állítás | státusz |
|---|---|
| leállítás utáni párologtató-szárítás mint autóipari funkció létezik | **MEGERŐSÍTVE** — GM szervizbulletin *„Enable Afterblow"* néven, szoftverből engedélyezhető |
| a Ford Focus III-nál van blower-es HVAC-szárítás | **MEGERŐSÍTVE** — a Ford *„A/C Odor Treatment"* eljárása: A/C ki, REGISTER mód, teljes meleg, fúvó HI, **25 perc**, „to dry out the A/C system" |
| a Focus Mk3/3.5 DEATC-ben van **automatikus**, key-off afterblow | **NEM TALÁLTAM FORRÁST** (mindkét modell) |
| publikus As-Built bájt/bit hozzá | **NEM TALÁLTAM FORRÁST** |
| bárki bekapcsolta volna C346-on | **NEM TALÁLTAM FORRÁST** |

> **Vagyis a §44.3 / §45.2 találat a jelenlegi publikus tudás szerint új.**
> A koncepció létezik és a Ford maga is alkalmaz kézi szárító eljárást a
> Focuson — de azt, hogy a modul *automatikusan* is tudja, sehol nem
> dokumentálják.
>
> Egy eltérés viszont óvatosságra int: a Ford **kézi** eljárása REGISTER
> módot és **teljes meleget** ír elő, a mi rutinunk viszont a mód-ajtót
> 45 %-ra viszi és **a keverőajtókhoz hozzá sem nyúl**. Nem ugyanaz.
> A cél tehát továbbra is **[E]**.

### 46.5 A `0xFD0A` írása — a firmware felülírja a külső állítást

A Gemini azt állította, hogy a `0xFD0A` írásához **elég az extended session
és nincs SecurityAccess** — **forrás nélkül**. A ChatGPT ugyanerre
„NEM TALÁLTAM FORRÁST"-ot adott.

**A saját firmware-ünk egyértelmű** (§42.3, a `0x2E` kezelő-tábla `0x0AF00`,
`0xFD0A` bejegyzés): `flags = 0x12` →
- session-maszk **2** = `programmingSession` (`10 02`), **nem** extended,
- security-maszk **2**, az alapszint 1 → `2 & 1 = 0` → **`NRC 0x33`**.

**A firmware nyer.** A `0xFD0A` írásához programming session **és**
SecurityAccess kell. (Ez nem baj: a FORScan As-Built írása pontosan ezt
csinálja.)

### 46.6 A regionális kalibráció — a koncepció igazolt, a számok nem

A Ford saját szabadalma (**US6173902**, *Method and system for controlling an
automotive HVAC system*) kimondja, hogy a napterhelés-kompenzáció **külön
kalibrációs konstans** (`KT1`), amit DOE-tesztekkel, `full sun` / `no sun`
állapotokban, több környezeti hőmérsékleten hangolnak, és külön konstansokat
használnak steady-state és tranziens viselkedésre.

**Ez pontosan az a szerkezet, amit a §39.4 / §25.9 táblákban látunk** — a
napterhelés-súly OAT-függő görbe, külön tranziens-tagokkal.

Amire **nincs forrás**: hogy a Ford EU és NA között szándékosan ~3×-os
napterhelés-súlyt használ, és hogy az NA kikapcsolja az alapjel-tranzienst.
Ez marad **saját firmware-eredmény** (a hat változat összevetéséből).

**Egy külső állítást a saját adatunk cáfol:** a Gemini szerint a `C346FAP`
= „Ázsia/Csendes-óceán". A byte-diffünk szerint a `C346` ↔ `C346FAP`
eltérés **38 bájt**, míg egy valódi régióváltás (`C346` ↔ `C346NA`)
**350 bájt**. Egy 38 bájtos eltérés **nem régió**, hanem felszereltség- vagy
motorváltozat (a `FAP` a dízel részecskeszűrő francia rövidítése).

### 46.7 Mérleg

**Amit a külső források megerősítettek:**
- az ajtó-geometria négy motorra (0, 1, 2, 3) — **ez feloldja a 33. patch blokkolóját**
- öt aktuátor a DEATC fűtésdobozban
- a napterhelés-kompenzáció mint kalibrálható gain (Ford-szabadalom)
- az afterblow mint autóipari koncepció

**Amit pontosítottak:**
- `B125B` = *Air Distribution Damper „B" Motor* (§46.2)
- `F1ET-18D619-AM` = **szoftver-szám**, nem alkatrészszám (§46.3)

**Ami saját, publikusan nem dokumentált eredmény maradt:**
- a `0xFD0A` bájtszintű tartalma és az alvó rutin kapcsolója
- a `0x2F` IO-control fehérlistája és a vezérlő bájt skálája
- a §39 kétcsomópontos utastér-modell és együtthatói
- a regionális kalibrációs különbségek konkrét számai
- a §43 NVM blokk-térkép


---

## 47. KORREKCIÓ: az AUTO légelosztás NEM állandóan 58  **[B]**

> **Ez a 33. szakasz (és a `patch_autodist.py`) alapfeltevését érinti.**
> A 46.1 után újraolvastam a `0x44C44` környékét, és a korábbi állítás
> — „AUTO-ban a mód-ajtó pozíciója egy beégetett konstans (58)" —
> **túl erős.**

### 47.1 Amit a kód valójában mond

```
0x44C3C  ha a mod == 9 (AUTO):
0x44C44      gp-31160 = gp-31164             ; << az "AUTO alapertek"
0x44C4C      ha sp[8] != 0 : gp-31160 = cal.b[673] = 60
0x44C60      ha sp[7] != 0 : gp-31160 = cal.b[671] = 17
         kulonben:
0x44C76      gp-31160 = sp[36]               ; a mod -> ajto tablabol
```

És a `gp-31164` **nem konstans** (`0x44B80`…`0x44BEC`):

```
gp-31164 = min( sp[3], cal.b[659] )                 ; SZAMITOTT ertek
ha FUN_3DE94() >= 3 :
     ha FUN_3DE8E() == 1 :  gp-31164 = max(sp[3], sp[50])
     ha FUN_3DE8E() == 2 :  gp-31164 = cal.h[358] >> 1 = 58    ; << CSAK ITT
```

**Az 58 csak akkor él, ha `FUN_3DE8E() == 2`.** És a `FUN_3DE8E()`
(`gp-28680`) egy **időzített reteszből** jön (`0x3E00C`…`0x3E0EE`, a 28-as és
29-es időzítő):

| `gp-28680` | mikor |
|---|---|
| 1 | amíg a **29-es** időzítő fut (`gp-31583` = 1) |
| 2 | amíg a **28-as** időzítő fut (`gp-31584` = 1) |
| 0 | egyébként |

Vagyis az 58 egy **átmeneti ablakban** érvényes, nem tartósan.

### 47.2 Mit jelent ez a 33. patchre

A `patch_autodist.py` a `0x44C44`-nél lévő `ld.hu -31164[gp]`-t cseréli le egy
görbés számításra. Ezzel **nem egy beégetett konstanst vált ki, hanem a teljes
AUTO alapértéket** — beleértve a normál, számított ágat is.

| | |
|---|---|
| ha az AUTO valóban 58-on ragad | a patch **valódi hibát javít** |
| ha a `gp-31164` normálisan követi a fűtésigényt | a patch **fölösleges, sőt ronthat** |

**A `tools/model.py doors` „AUTO: ajtó1 ÁLLANDÓ 58" kiírása ugyanezt a téves
feltevést kódolta** — nem független megerősítés.

### 47.3 Ezt egy két perces mérés dönti el

```
02 22 9B 01        ; mod-ajto #1 tenyleges pozicioja, DEFAULT sessionben
```
AUTO módban, **hideg indításkor és bemelegedve** kiolvasva:

- ha **mindkétszer 58** → a 33. patch premisszája áll,
- ha **változik** (pl. hidegen ~60 = láb, melegen ~21 = fej) → **a modul már
  most alkalmazkodik**, és a patchre nincs szükség.

**A `COMBO.vbf`-et addig nem szabad flashelni.** A `dualzone` rész
(`cal[569]`) ettől függetlenül érvényes — az egy tiszta kalibrációs érték.


---

## 48. A §44.3 RUTIN ÚJRAÉRTÉKELVE — a CAN-feltételek azonosítva  **[B]**

A §45-ben leírtam a rutint mint „nem éri meg". **Ez elhamarkodott volt.**
A három kiváltó CAN-jelet a `0xA94C` szűrő- és a `0xAAFC` puffer-táblából,
valamint a 2023-as menetlogokból (`../canbus_re/`) sikerült azonosítani.

### 48.1 A három feltétel

| változó | CAN | küszöb | mit jelent |
|---|---|---|---|
| `gp-28788` | **`0x300` B3** `& 0x7F` (600 ms) | `> 74` | a logokban **két érték**: `0x21`=33 és `0x61`=97 → a küszöb a **6. bitet** teszteli |
| `gp-29253` | **`0x1E0` B2** `& 0x7F` (100 ms) | `(B2−40) > 10…15` → `B2 > 50…55` | a `0x1E0` = kerékfordulat + sebesség (HVAC_CAN.md §64) |
| `gp-29252` | **`0x1E0` B0:B1** big-endian u16 | `(x²)>>8 > 7200` → `x > 1358` | B1 = `0x80` állandó, B0 = `0x42…0xC6` → **mindig teljesül** |

**A `0x300` B3 nem páratartalom.** A két érték különbsége pontosan
`0x40` = a 6. bit, a többi bit állandó (`0b100001` = 33). A `> 74` küszöb
(és a B gép `> 77`-e) **egy bináris jelzőt vizsgál**, nem egy 0-100 skálát.
A korábbi „relatív páratartalom" feltevés **elvetve**.

> **A leglényegesebb: a 2023-as menetlogokban a `0x300` B3 MINDKÉT értéket
> felveszi.** Vagyis a kapcsoló feltétel **ebben az autóban ténylegesen
> bekapcsol** — a rutin nem egy soha nem teljesülő ág.

### 48.2 KORREKCIÓ: ez nem kikapcsolás utáni rutin

A kiváltó (`FUN_54EC4`) megköveteli, hogy **`gp-29310 == 0` és
`gp-29326 == 0`** — vagyis hogy a CAN-üzenetek **élők** legyenek (a 146-os
timeout ne járt volna le). A `gp-29253` feltétel ráadásul **menet közbeni
sebességet** kíván (`0x1E0` B2 > 50…55).

**Tehát a rutin gyújtás alatt, menet közben fut — nem kikapcsolás után.**

Ez **elveti a „párologtató-szárítás / afterblow" értelmezést**, ami a §44.3,
§45.2 és §46.4 alapfeltevése volt. A profil ehelyett:

> nagy sebességnél, egy CAN-jelző bekapcsolásakor **15 másodpercre**
> friss levegőre vált, a mód-ajtót középre viszi (45 %) és a fúvót
> 89 %-ra emeli — majd mindent visszaállít oda, ahol volt.

Ez egy **utastér-átöblítés menet közben**. Hogy mi váltja ki (`0x300` bit6),
az továbbra is **[E]** — de a jellege alapján lehet levegőminőség-jelzés,
szagérzékelés, vagy egy másik modul kérése.

### 48.3 Mit jelent ez a fejlesztési értékére

| korábbi ítélet (§45) | most |
|---|---|
| „kikapcsolás utáni szárítás, de csak 15 s → értelmetlen" | **menet közbeni átöblítés — 15 s ehhez ARÁNYOS** |
| „a feltételek valószínűleg sosem teljesülnek" | **a logok szerint a kapcsoló feltétel bekapcsol** |
| „nem éri meg a SecurityAccess-t" | **újra napirenden** — de előbb tudni kell, mi a `0x300` bit6 |

### 48.4 A következő lépés — és most már olcsó

A `0x300` **600 ms-onként megy, és a logokban a B3 csak két értéket vesz fel**.
Egy MS-CAN olvasás menet közben, a `0x300` B3 bit6-ának figyelésével
megmondja, **mikor** kapcsol be — és ha sikerül összefüggésbe hozni valamivel
(alagút, másik autó mögött, szagos szakasz, A/C állapot), az megadja a
rutin célját.

Ehhez **nem kell UDS, nem kell session, nem kell SecurityAccess** — csak egy
CAN-olvasó az MS-CAN-on, ami már megvan a `../canbus_re/` eszközökben.

---

## 49. A VALÓDI FEJLESZTÉS: zárt hurkú kifúvási hőmérséklet-trim  **[terv]**

Két független kutatási menet (Gemini + ChatGPT, 2026-08-26) ugyanarra jutott,
és megerősítette a §45 utáni sejtést: **a modul legnagyobb kihagyott
lehetősége, hogy a négy beépített kifúvási NTC-t nem használja
szabályozásra.**

### 49.1 Hogy ez nem „2026-os ötlet"  **[külső források]**

| forrás | mit mond |
|---|---|
| **US4899809A** (1989) | cél-kifúvási hő, mért kifúvási hő, a különbségből ciklikus keverőajtó-korrekció |
| **Mercedes W163 AAC** szervizdoksi (2001, **sorozatgyártás**) | a center- és footwell-kifúvás mért hőmérsékletét összeveti a kívánttal, ebből állítja a keverőajtót |
| **Delphi EP1466764A1** (2003) | a duct-szenzor + PID + keverőajtó struktúrát **tipikus autóipari prior artként** írja le |
| **Ford US5937940A** | a kifúvási hőmérséklet becslése fűtőradiátor-hőmérsékletből, ajtópozícióból és **fúvósebességtől függő** kölcsönhatási időből |
| **US7650927B2** | konkrét példa: rossz fűtőradiátor-becslés → 55 °C cél helyett **45 °C tényleges**; a korrekcióhoz 82 %-ról 88 %-ra kellett vinni az ajtót |

**A Ford tehát kifizette és beépítette a négy DAT-érzékelőt, de a visszafejtett
stratégia nem zárja le velük a keverőajtó hurkot.**

### 49.2 Mit javítana ténylegesen

A jelenlegi lánc tisztán előrecsatolt: `cél-kifúvási hő → keverőajtó-térkép →
ajtópozíció`. Ez a térkép **nem tud** a következőkről:

- a **hűtőfolyadék hőmérséklete** (télen a termosztát nyitásakor a fűtőradiátor
  hőmérséklete leesik — a `US7650927B2` szerint ez 10 °C-os kifúvási hibát okoz);
- a **párologtató pillanatnyi állapota**;
- a **légáram** hatása a hőcserére (a `US5937940A` szerint a kölcsönhatási idő
  fúvósebesség-függő);
- az **ajtó mechanikai tűrése és öregedése**.

Egy visszacsatolás ezeket mind **maradó hibaként** látja, és lassan kinullázza.

### 49.3 A struktúra — a gyári algoritmus MEGMARAD

```
gyari:   cel-kifuvasi ho -> keveroajto-terkep -> u_stock -> ajto

patch:                     +---------------------------+
         cel-kifuvasi ho ->| e = T_cel - T_duct        |
                           | ha |e| > holtsav:         |
                           |     trim += Ki * e        |
                           | trim = clamp(+-TRIM_MAX)  |
                           +---------------------------+
                                        |
         u_vegso = clamp( u_stock + trim ,  gyari also/felso hatar )
```

**Nem cseréljük le a gyári számítást** — az adja a gyors, nagy mozgást
(alapszint, napterhelés, alapjel, utastér-modell). A hurok **csak a tartós
maradó hibát** húzza le. Első körben **P nélkül, csak integrál**, mert a
gyors dinamikát már az előrecsatolás intézi.

### 49.4 A beakasztási pont — ugyanolyan alakú, mint a §33 patché  **[B]**

A `0x3DE6C`…`0x3DE80` két darab **8 bájtos `ld.hu` + `st.h` pár**:

```
0003DE6C  ld.hu  -31676[gp], r1     ; a B oldal gyari parancsa
0003DE70  st.h   r1, -29110[gp]     ; keveroajto B
0003DE7C  ld.hu  -31666[gp], r1     ; az A oldal gyari parancsa
0003DE80  st.h   r1, -29112[gp]     ; keveroajto A
```

Ez **pontosan az a minta**, amit a `patch_autodist.py` már bizonyítottan
lecserél (`jarl <rutin>, lp` + `st.h r10, …`). A rutin megkapja a gyári
parancsot a `gp-31666` / `gp-31676`-ból, és a trimmelt értéket adja vissza.

### 49.5 Erőforrás-mérleg  **[B]** — és egy korrekció

| | |
|---|---|
| szabad flash a CRC hatókörén belül | **`0x77E00` … `0x77EFF` = 256 bájt** |
| ebből az AUTODIST már használ | 86 bájt (`0x77E00`…`0x77E55`) |
| **marad** | **170 bájt** |

> **Korrekció:** a §3 cheat sheet és a kutatási prompt „~500 bájt"-ot mondott.
> A tényleges összefüggő `0xFF` terület **256 bájt**; a `0x77F00`-tól kezdődő
> rész `60 00` mintával van kitöltve (nem üres), a `0x77FF4` pedig a belső CRC.

**170 bájt egy korlátos integrátorhoz elég lehet**, de két oldalra és a
mód-függő NTC-választásra már szűkös. Ha kevés, az AUTODIST és a DAT-trim
**egy közös rutinba** vonható (mindkettő ugyanabban a függvényben hat).

### 49.6 A megoldatlan pont: hol legyen az integrátor  **[nyitott]**

Az integrátornak **perzisztens RAM** kell (2 × 2 bájt). A gp-relatív
címtérben statikusan kerestem soha nem hivatkozott réseket, de ez **csapda**:
az indexelt tömbök (pl. az NVM-tükör, a léptető-parancspool) literális
offszet nélkül érhetők el, tehát „szabadnak" látszanak.

Három jelölt, ami a **ismert** szerkezetekkel (NVM-tükör, CAN RX/TX pufferek)
nem ütközik:

| tartomány | méret |
|---|---|
| `0xFEDFC9B0` … `0xFEDFCA83` | 212 bájt |
| `0xFEDFCA90` … `0xFEDFCB23` | 148 bájt |
| `0xFEDFCDC4` … `0xFEDFCE27` | 100 bájt |

**Ez nem bizonyíték.** A `0x23 ReadMemoryByAddress` szolgáltatás **nincs a
modulban** (§42.4), tehát UDS-ből nem lehet RAM-ot olvasni és ellenőrizni.
A biztonságos út: a startup RAM-inicializáló (`.bss` / `.data` másoló)
átolvasása — ha a rés kívül esik minden inicializált szakaszon, valóban
szabad.

### 49.7 Fail-safe lista — kötelező

```
NTC hibas / DTC aktiv           -> trim = 0
lepteto-hiba                    -> trim = 0
fuvo a kuszob alatt             -> integrator BEFAGY (nem nullaz)
mod-valtas                      -> integrator befagy
manualis HI / LO veghelyzet     -> trim = 0
MAX DEFROST                     -> a gyari logika ERINTETLEN
telitodes                       -> kemeny clamp
```

A `MAX DEFROST` kihagyása nem opcionális: az **biztonsági** funkció.

### 49.8 Ami méréssel meghatározandó

| paraméter | miért nincs rá forrás |
|---|---|
| `Ki` | Focus-specifikus; a hurok erősítése a csatorna-geometriától függ |
| holtsáv | az NTC zaja és a léptető holtsávja (±5 lépés) alapján |
| `TRIM_MAX` | mindkét kutatás **±10 %** körüli korlátot javasolt a gyári értékhez képest |
| a fúvó-küszöb | ami alatt nem szabad integrálni |
| **melyik NTC melyik zónához** | a §39.3 párokon belül a bal/jobb **[E]** — a §40.5/C mérés zárja le |

### 49.9 A kockázatok, őszintén

1. **Rétegződés.** A keverőajtó után a hideg és meleg levegő nem tökéletesen
   keveredik. Ha az NTC épp egy hideg áramlatban ül, a szabályozó felmelegít —
   és az utas leforrázódhat. Ezért kell a szűk `TRIM_MAX`.
2. **Érzékelő-késés.** A duct-NTC termikus időállandója tipikusan több
   másodperc; a szabályozó 1,25 s-onként fut. **D-tag semmiképp.**
3. **Kis légáramnál** a holtidő megnő — ezért a befagyasztás.
4. **Ez egy működő autó fűtése.** Egy megszaladt integrátor télen
   fűtés nélkül hagyhat. A `TRIM_MAX` és a fail-safe lista nem díszítés.

### 49.10 A sorrend, amit javaslok

| # | mi | nyereség | kockázat |
|---|---|---|---|
| **1** | **korlátos DAT integrál-trim** | **nagy** | közepes — a §49.7 fail-safe-ekkel |
| 2 | **fúvó rámpa / lengéscsillapítás** (a Ford `EP0706682B1` maga is dokumentál fokozatos átmenetet) | közepes | **kicsi** |
| 3 | **bal/jobb napterhelés-differencia** a két zóna céljára | közepes | kicsi |
| 4 | keverőajtó-holtsáv (hogy a trim ne zizegtesse az aktuátorokat) | kicsi | kicsi |

**Amit mindkét kutatás elvetett ezen a hardveren:** MPC/NMPC (a publikált
autóipari valós idejű példa 3 × 300 MHz, 8 MB flash), online RLS
paraméterbecslés, és PMV/UCB/EHT komfortmodell (a szükséges bemenetek —
utastér-hőmérséklet, sugárzási hőmérséklet, légsebesség, páratartalom —
**nincsenek meg a hardverben**).

**Párásodás-előrejelzés:** a Ford 2026-os saját publikációja
(`SAE 2026-01-0131`) szenzorfúzióval jósol páratartalmat — de a bemenetei
(utaslétszám, ablakállapot, utastér-hőmérséklet) nálunk hiányoznak. A
szélvédő-oldali NTC-ből **nem** lehet harmatpontot becsülni: az a befújt
levegőt méri, nem az utastér vízgőztartalmát.

---

## 50. ÉLŐ MÉRÉS AZ AUTÓBAN — a §47 LEZÁRVA  **[B, mérés]**

**Dátum:** 2026-08-26 · **Eszköz:** UCDS → Additional Function → **CanBus Analyzer**
(ez a tab egyszerre tud küldeni és fogadni; a Logger és a Player **nem** futtatható
párhuzamosan, a Player pedig csak fájlból küld — lásd `tools/mkpoll.py`).

Beállítás: `Speed PINS 3\11 = 125 Kbps`, `Mode = CAN ID 11-Bit Only`, FD ki,
`Start Analyzing`, majd `CAN MSG Send`: `PINS 3\11`, `ID 733`, `DLC 8`,
`DATA 03 22 9B 01 00 00 00 00`. Válasz a `73B` soron.

### 50.1 Az AUTO mód-ajtó NEM állandó — a §47 kérdés eldőlt

Hideg AUTO, alapjel 21 °C:

| jel | válasz | érték |
|---|---|---|
| `9B01` mód-ajtó #1 | `04 62 9B 01 37 00 00` | **55 %** |
| `9834` mód-ajtó #2 | `04 62 98 34 28 00 00` | **40 %** |

Az 55 **nem** az 58 (`cal.h[358] >> 1`), tehát már ez is a **számított ág**.

Végigsöpörve az alapjelen (LO…HI, 1 °C-onként), végig AUTO módban:

```
9B01:  3C 3C 3C 3C 3C 3C 38 33 29 19 17 17 17 17 11
       60 60 60 60 60 60 56 51 41 25 23 23 23 23 17   %

9834:  00 20 20 20 20 20 25 27 27 27 27 27 27 27 0A
        0 32 32 32 32 32 37 39 39 39 39 39 39 39 10   %
```

Ismételve, két végponton: `0x3B` = **59 %** és `0x11` = **17 %**.

**A mód-ajtó #1 tartománya AUTO-ban 17…60 %, sima, monoton átmenettel.**

### 50.2 Következmények

| tétel | státusz |
|---|---|
| **§47 „AUTO-ban beégetett 58"** | **CÁFOLVA méréssel** — a `gp-31164` számított ág fut |
| **§33 / `patch_autodist.py` / `AUTODIST.vbf`** | **fölösleges** — a modul már alkalmazkodik. A `COMBO.vbf` **nem flashelendő** |
| **§20.4 / §33.4 LED-patch** | **ez a helyes fejlesztés** — van mit kijelezni |
| **§32.4 „a LED-patch önmagában rossz eredményt ad"** | **érvénytelen** — az a megállapítás az 58-as premisszán állt |

### 50.3 NAGY KORREKCIÓ: a mód-ajtó #1 skálája FORDÍTOTT a dokumentációhoz képest  **[B, mérés]**

Manuális módban, gombonként kiolvasva:

| gomb | `9B01` mért | a §20/§33 tábla szerint |
|---|---|---|
| **FEJ** (szellőzők) | `0x3B` = **59 %** | 21 % ❌ |
| **LÁB** | `0x15` = **21 %** | 60 % ❌ |

**A `cal+2320` tábla ÉRTÉKEI helyesek, a mode-hozzárendelésük fordított.**
Az igazság: **60 % = FEJ, 21 % = LÁB.**

Ezzel az AUTO viselkedése teljesen konzisztens lesz:

| AUTO alapjel | `9B01` | irány |
|---|---|---|
| **LO** (max hűtés) | 59 | **FEJ** ✅ |
| **HI** (max fűtés) | 17 | **LÁB** ✅ |

**Következmények:**
- A §32.4 „nearest-neighbour rosszul kondicionált" eredmény **fordított táblával
  futott** — újra kell értékelni.
- A §33.4 küszöbei (`fej ≤ 46`, `láb ≥ 27`) **tükrözendők**.
- A `model.py doors` kimenete a mode-neveknél **téves** — javítandó.
- A §46.1 léptető-szerepek (Ford-dokumentációval igazolva) **nem érintettek**:
  ott a motor azonosítása volt a tárgy, nem a pozíció-skála iránya.

### 50.3b A LED-küszöbök NEM vehetők át a §33.4-ből

A §33.4 küszöbei (`fej ≤ 46`, `láb ≥ 27`) a `cal+2320` tábla mode-hozzárendelésén
állnak, ami szerint mode 1 (fej) → 21 és mode 2 (láb) → 60. A mérés viszont azt
mutatja, hogy **AUTO-ban a hidegebb alapjel felé a szám NŐ** (a 60-as vég felé),
ami ezzel a hozzárendeléssel ellentmondásos.

**Nyitott, egy méréssel zárható:** manuális módban a **fej** és a **láb** gombra
kiolvasott `9B01` érték. Ez közvetlenül összeköti a számot a fizikai iránnyal,
tábla nélkül. A küszöböket **csak ezután** szabad felírni — fordított irányú
küszöbökkel a LED pont ellentétesen mutatna.

### 50.4 Passzív MS-CAN log — a `0x190` harmadszor is megerősítve

Ugyanazon a napon 136 s, 93 579 keret a 3/11 buszról
(`Can_bus_logger_2608261657_MScan`). A `0x190` dekódolva:

| t [s] | B4 | B5 | irány-bitek |
|---|---|---|---|
| 0…95 | `01` | `F2` | **–– egyik sem ––** (AUTO) |
| 95,0 | `00` | `FA` | SZÉLVÉDŐ |
| 98,4 | `00` | `FE` | LÁB+SZÉLVÉDŐ |
| 101,1 | `00` | `FF` | FEJ+LÁB+SZÉLVÉDŐ |
| 113,9 | `01` | `F2` | **–– egyik sem ––** (vissza AUTO) |

Manuálisan mind a három bit helyesen megy ki; **AUTO-ban mind a három 0** — a
§9 megállapítás élőben, harmadszor.

**Javítás a `canbus_re/HVAC_CAN.md`-hez:** a `0x190` `B4 = 0x00` **nem** „modul
alszik", hanem **manuális mód**. Ébren lévő modultól mérve, `B5`-ben érvényes
iránybitekkel.

### 50.5 A TELJES MÓD-TÁBLA MÉRVE — 16/16 illeszkedés  **[B, mérés]**

Manuális módban, gombonként, mindkét mód-ajtó kiolvasva (`22 9B 01` / `22 98 34`):

| panel-gomb | `9B01` mért | `9834` mért | a §20 tábla melyik sorával egyezik |
|---|---|---|---|
| FEJ | **59** | **0** | „lab" (60 / 0) |
| FEJ + LÁB | **33** | **0** | „fej+lab" (33 / 0) |
| LÁB | **21** | **40** | „fej" (21 / 40) |
| LÁB + SZÉLVÉDŐ | **9** | **55** | „fej+szel" (9 / 55) |
| FEJ + SZÉLVÉDŐ | **100** | **65** | „lab+szel" (100 / 65) |
| MIND3 | **45** | **75** | „mind3" (45 / 75) |
| SZÉLVÉDŐ | **0** | **100** | „szelvedo" (0 / 100) |
| MAX fűtés/defrost | **0** | **100** | „MAX defrost" (0 / 100) |

**Mind a 16 érték illeszkedik, EGYETLEN következetes cserével: FEJ ↔ LÁB.**
Nincs kilógó érték, nincs maradék. A `cal+2320` / `cal+2299` táblák **értékei
helyesek**; a §9 mód-állapotgép **fej/láb bit-hozzárendelése fordított**
(`gp-32097` és `gp-32088` szerepe cserélve a §9 táblához képest).

Ez megmagyarázza, miért adott a §32.4 nearest-neighbour szimuláció értelmetlen
eredményt: fordított táblával futott.

### 50.6 AZ AUTO VISELKEDÉSE — a modul HELYESEN szabályoz

| állapot | `9B01` | a mért skálán |
|---|---|---|
| AUTO, alapjel **LO** (max hűtés) | 59 | **FEJ** |
| AUTO, hideg motor, 21-22 °C | 55 | FEJ felé |
| AUTO, **meleg motor**, 21-22 °C | 59 | **FEJ** |
| AUTO, alapjel **HI** (max fűtés) | 17 | **LÁB** (a 21-en is túl) |

Az alapjel-söprés (LO→HI, 1 °C-onként) folytonos: 60 → 56 → 51 → 41 → 25 → 23 → 17.

**A modul tehát pontosan azt csinálja, amit kell** — hűtésnél fejre, fűtésnél
lábra, sima átmenettel. Egyedül a visszajelzés hiányzik.

### 50.7 A LED-KÜSZÖBÖK — kizárólag a mért adatokból

A fej/láb tengely monoton a `9B01`-ben: **FEJ 59 → FEJ+LÁB 33 → LÁB 21.**
Küszöbök a szomszédos mért értékek felezőpontjain:

```
FEJ      = d1 >= 27          ; (33+21)/2
LAB      = d1 <= 46          ; (59+33)/2
SZELVEDO = d2 >= 48          ; (40+55)/2   -- d2 = 40 a legnagyobb szelvedo NELKULI ertek
```

Ellenőrzés a mért manuális pontokon:

| gomb | d1 | d2 | számított LED | helyes? |
|---|---|---|---|---|
| FEJ | 59 | 0 | `F--` | ✅ |
| FEJ+LÁB | 33 | 0 | `FL-` | ✅ |
| LÁB | 21 | 40 | `-L-` | ✅ |
| LÁB+SZÉLVÉDŐ | 9 | 55 | `-LS` | ✅ |
| FEJ+SZÉLVÉDŐ | 100 | 65 | `F-S` | ✅ |
| MIND3 | 45 | 75 | `FLS` | ✅ |
| SZÉLVÉDŐ | 0 | 100 | `--S` | ✅ |

**7/7 helyes.** Az AUTO mért tartománya (`d1` 17…59, `d2` 0…40) végig a
fej/fej+láb/láb sávban marad, szélvédő-bit nélkül — ami helyes: AUTO nem
kapcsol defrostot magától.

*(Számszerűen ugyanaz a 27 / 46 / 48 hármas, mint a §33.4-ben — csak a fej és a
láb összehasonlítása fordítva, a §50.3 korrekció miatt.)*

### 50.8 As-Built rekordok — a `0xFD0A` NEM a konfigurációs blokk  **[B, mérés]**

A UCDS *Direct Configuration* nyolc rekordot mutat a HVAC-on:

| # | rekord | tartalom |
|---|---|---|
| 1 | `F111` ECU Core Assembly | `F1ET-14F165-DC` |
| 2 | `F113` ECU Delivery Assembly | `F1ET-18C612-DJ` |
| 3 | `F18C` ECU Serial | `WZ8V128233` |
| 4 | `FD01` Date code | `131017` |
| 5 | **`FD0A` Illumination Calibration** | **88 bájt** |
| 6 | `FD0B` CCP enabled | `00` |
| 7 | `DE00` Configuration Parameters | ECU brand: Ford Europe · Heated Seat Time-out: 60 min |
| 8 | `DE01` Climate System Configuration | R134a · CCC compressor · China Purge letiltva · 13 fenntartott bájt |

**Javítás a §36-37 / §44 feltételezéshez:** a `0xFD0A` **a megvilágítás-kalibráció**,
nem az általános As-Built konfigurációs rekord. A konfiguráció a **`DE00`** és a
**`DE01`** — és a `DE01` első három bájtja az, amit a §44 „konfig-rekordnak" hívott.

#### A `FD0A` szerkezete

```
011B3745 00CC27CD 009A1E07 021189AD 01705FCB 02088780
01F88344 00BB248B 00A6206B 00A41FF2 00C626A5 02C037B5
027232B5 06A49C7A 05B4909C 0688B049 078CCA28 0575A077
00ED2E4D 07768F3C 005A7392 00000000
```

**88 bájt = 22 × 4**, azaz **21 aktív csatorna + egy lezáró nulla-bejegyzés.**
Ez egybevág a §44.1 láncával: `FUN_540C8` csatornánként interpolál a
`gp-23132` (min) és `gp-23040` (max) kalibrációs táblák között.

Minden bejegyzés két big-endian u16-nak olvasható; a második rendre a
sokszorosa az elsőnek (a szorzó csatornánként ~19…67), tehát **min/max
fényerő-pár** a legvalószínűbb — de ez **[E]**, nem bizonyított. A pontos
formátum lezárásához a `FUN_540C8` és a két tábla betöltőjének átolvasása kell.

> **Ez a rekord a LED-fényerő hangolásának a kulcsa** — külön munkacsomag,
> és **UDS-ből írható** (`0x2E`, programming session + SecurityAccess).

---

## 51. A `led_auto` PATCH — MEGÉPÍTVE ÉS ELLENŐRIZVE (2026-08-26)  **[B]**

**Eszköz:** `tools/patch_led_auto.py` (`build` / `verify`)
**Kimenet:** `F1ET-18D619-AM_LEDAUTO.vbf`

### 51.1 Mit csinál

AUTO-ban (mode 9, `FUN_37820`) a modul feltétel nélkül nullázza a három
iránybájtot. A patch ezt lecseréli a **két mód-ajtó tényleges parancsából**
számított értékekre, a **§50.5-ben mért** küszöbökkel:

```
d1 = gp-29044   (mod-ajto #1, 0..100 %,  UDS 9B01, lepteto 1)
d2 = gp-29048   (mod-ajto #2, 0..100 %,  UDS 9834, lepteto 4)

FEJ      = d1 >= 27                 -> gp-32088
LAB      = 5 <= d1 <= 46            -> gp-32097
SZELVEDO = d2 >= 48                 -> gp-32087
```

A `LAB` alsó küszöbe (5) választja el a „láb+szélvédő" állást (d1 = 9) a
tiszta „szélvédő" állástól (d1 = 0). A rutin ugyan **csak AUTO-ban fut**,
ahol a mért `d1` tartomány 17…60, de fail-safe-ből a teljes 0…100
tartományon helyes eredményt ad.

### 51.2 A beakasztás

A három `st.b r0` pontosan 12 bájt, egymás után:

```
0x37848  4407a882   st.b r0, -32088[gp]     ->   8407b805   jr 0x77E00
0x3784C  44079f82   st.b r0, -32097[gp]     ->   0000 0000  nop nop
0x37850  4407a982   st.b r0, -32087[gp]     ->   0000 0000  nop nop
```

**`jr`, nem `jarl`** — ez kötelező: a `FUN_37820` a `jmp [lp]`-vel tér vissza,
tehát az `lp`-t nem szabad elrontani. Az új rutin `jr 0x37854`-gyel ugrik vissza.

### 51.3 Az új rutin (`0x77E00`, 90 bájt)

```
77E00  581a       add      -8, sp                ; r6/r7 mentese
77E02  63370100   st.w     r6, 0[sp]
77E06  633f0500   st.w     r7, 4[sp]
77E0A  e4378d8e   ld.hu    -29044[gp], r6        ; d1
77E0E  e43f898e   ld.hu    -29048[gp], r7        ; d2
77E12  4407a882   st.b     r0, -32088[gp]        ; FEJ = 0
77E16  44079f82   st.b     r0, -32097[gp]        ; LAB = 0
77E1A  4407a982   st.b     r0, -32087[gp]        ; SZEL = 0
77E1E  200e1b00   movea    27, r0, r1            ; --- FEJ ---
77E22  e131       cmp      r1, r6
77E24  c105       bl       0x77E2C
77E26  010a       mov      1, r1
77E28  440fa882   st.b     r1, -32088[gp]
77E2C  200e2f00   movea    47, r0, r1            ; --- LAB ---
77E30  e131       cmp      r1, r6
77E32  e905       bnl      0x77E3E
77E34  6532       cmp      5, r6
77E36  c105       bl       0x77E3E
77E38  010a       mov      1, r1
77E3A  440f9f82   st.b     r1, -32097[gp]
77E3E  200e3000   movea    48, r0, r1            ; --- SZELVEDO ---
77E42  e139       cmp      r1, r7
77E44  c105       bl       0x77E4C
77E46  010a       mov      1, r1
77E48  440fa982   st.b     r1, -32087[gp]
77E4C  23370100   ld.w     0[sp], r6             ; helyreallitas
77E50  233f0500   ld.w     4[sp], r7
77E54  481a       add      8, sp
77E56  bb07fef9   jr       0x37854               ; vissza
```

**Regiszterek:** az `r6`/`r7` a vermen mentve. Az `r1` bizonyíthatóan halott
a hookpontnál — a `FUN_37820` a `0x3785C`-nél tölti újra. Az `lp` érintetlen.

**A §2/1. csapda elkerülve:** itt végig `cmp` van, nem `addi -N`, tehát a
carry a szokásos irányba mutat. `cmp r1, r6` = `r6 − r1`, `bl` = CY==1 = `r6 < r1`.

### 51.4 Az ellenőrzés

A `verify` **visszadisassemblálja a saját kimenetét** a `v850dis`-szel, és
mind a 27 utasítást szövegre hasonlítja. Ezen felül:

| ellenőrzés | eredmény |
|---|---|
| a hook pontosan 12 bájt, `0x37854`-nél végződik | ✅ |
| minden elágazás célja a rutinon belül vagy a `0x37854` | ✅ |
| logikai önteszt a **mért** manuális táblán (§50.5) | **7/7 OK** |
| bájt-diff az eredetihez | **103 bájt, 4 tartomány** — hook (11), rutin (90), CRC (2) |
| belső flash CRC `resign` után | `8E67` tárolva = számolva ✅ |
| VBF blokk-CRC | **`B9A6`** ✅ (az invariáns, §2/5) |
| VBF file-CRC32 | `A6F11173` ✅ |
| VBF → kicsomagolás → újraellenőrzés | ✅ |

### 51.5 Amit a patch várhatóan mutat AUTO-ban

| állapot | d1 | d2 | LED |
|---|---|---|---|
| AUTO LO (max hűtés) | 59 | 0 | **F--** fej |
| AUTO meleg, 21-22 °C | 59 | 0 | **F--** fej |
| AUTO hideg, 21-22 °C | 55 | 32 | **F--** fej |
| AUTO közép | 33 | 32 | **FL-** fej+láb |
| AUTO HI (max fűtés) | 17 | 40 | **-L-** láb |

Manuális módban **semmi nem változik** — a patch csak a mode 9 ágban fut.

### 51.6 Amit a patch NEM csinál

- **A CAN-t nem érinti.** A `0x190` `B5` iránybitek a `FUN_4CC42`-ből jönnek,
  a `gp-30695`-ön keresztül, közvetlenül a `mode`-ból — az továbbra is `F2`
  marad AUTO-ban. Ha ez is kell, az külön hook.
- **A szabályozásba nem nyúl.** Se ajtó, se fúvó, se kompresszor. Csak három
  állapotbájt, amit a firmware maga is csak LED-hajtásra használ.
- **A LED-fényerőt nem állítja.** Az a `FD0A` rekord dolga (§50.8).

### 51.7 Maradék szabad flash

A rutin 90 bájt a 256-ból (`0x77E00…0x77E59`), **166 bájt marad**
(`0x77E5A…0x77EFF`). Az `autodist` patch (86 bájt) elvetve (§50.2),
tehát a terület nem ütközik.

---

## 52. A `led_auto` V1 MEGBUKOTT AZ AUTÓBAN — és a V2  **[B, mérés]**

### 52.1 Amit a mérés mutatott

A V1 (§51) beflashelve: **egy LED kigyulladt, de soha nem váltott** — hiába
ment a hőfok LO-ról HI-ra, és hiába volt érezhető, hogy máshova fúj.

**Az ok:** a V1 a `FUN_37820`-ba (mode 9 állapotfüggvény) akaszkodott, azt
viszont **nem hívja meg minden ciklus**. A mód-diszpécser előtt kapu van:

```
0002EF34  ld.bu  -31922[gp], r1      ; kapu
0002EF38  cmp    r0, r1
0002EF3A  bz     0x2EFD2             ; ha 0 -> a diszpecser KIMARAD
0002EF3C  ld.bu  -29132[gp], r1      ; mode
0002EF40  cmp    10, r1
0002EF44  shl    0x2, r1             ; ugrotabla 0x2EF50-tol
   ...      jr 0x2EF78  ->  jarl FUN_37820   (mode 9)
```

A `gp-31922` a `0x314E4`-nél a `gp-32109`-ből másolódik — egy állapotjelző,
nem ciklusonkénti engedély. A V1 rutinja tehát **AUTO-ba lépéskor egyszer**
lefutott, és a három bájt onnantól befagyott.

> **Tanulság a projektre:** a §9-ben leírt „mód-állapotgép" nevéhez híven
> **állapot**gép — belépési akciókat futtat, nem ciklikus számítást. Bármi,
> aminek folyamatosan kell frissülnie, **nem oda való.**

### 52.2 A V2 — a fogyasztói oldal

A helyes beakasztási pont ott van, ahol a firmware **ciklusonként** átmásolja
a három bájtot a LED-struktúrába (`gp-31888`-tól):

```
00031420  ld.bu -32097[gp], r1      ->  jarl LAB_rutin,  lp
00031424  st.b  r1, -31888[gp]          (VALTOZATLAN)
00031440  ld.bu -32088[gp], r1      ->  jarl FEJ_rutin,  lp
00031444  st.b  r1, -31887[gp]          (VALTOZATLAN)
00031460  ld.bu -32087[gp], r1      ->  jarl SZEL_rutin, lp
00031464  st.b  r1, -31886[gp]          (VALTOZATLAN)
```

Ez **konstrukciónál fogva ciklusonként fut** — ez az a kód, ami a LED-eket
eteti. A rutin `r1`-ben adja vissza az értéket, a **változatlanul hagyott**
`st.b` tárolja el.

**Az `lp` elrontása itt biztonságos:** a befoglaló függvény a `0x2E8C8`-nál
`prepare 9, 0x79F0`-val menti, a `0x314FA`-nál `dispose 9, 0x79FF, [lp]`-vel
állítja vissza, és maga is hív `jarl`-t a testében (`0x30D56`, `0x31510`).

### 52.3 A három rutin (28 bájt egyenként)

Mindhárom azonos alakú; példa a FEJ-re (`0x77E1C`):

```
77E1C  a40fa582   ld.bu    -32091[gp], r1     ; mode
77E20  690a       cmp      9, r1              ; AUTO?
77E22  8a0d       bnz      0x77E32            ; nem -> eredeti bajt
77E24  e40f8d8e   ld.hu    -29044[gp], r1     ; d1
77E28  010ee5ff   addi     -27, r1, r1        ; d1 - 27, flagek
77E2C  ee0f0000   setf     ge, r1             ; r1 = (d1 >= 27)
77E30  7f00       jmp      [lp]
77E32  840fa982   ld.bu    -32088[gp], r1     ; MANUALIS: az eredeti bajt
77E36  7f00       jmp      [lp]
```

A `setf` **448 helyen** szerepel a firmware-ben, tehát bevett utasítás.

**Manuális módban semmi nem változik** — a rutin az eredeti bájtot adja vissza.
Ez erősebb garancia, mint a V1-é: ott a mode-9 ág átírása elvileg más
állapotokra is kihathatott volna.

**Nincs verem-használat**, a rutinok csak az `r1`-et és az `lp`-t írják.

### 52.4 A LAB alsó küszöb elhagyva

A V1-ben a `LAB` feltétel `5 <= d1 <= 46` volt, hogy a tiszta szélvédő-állást
(`d1 = 0`) elválassza. A V2-ben **erre nincs szükség**: az ág csak AUTO-ban
fut (`gp-32091 == 9`), ahol a mért `d1` tartomány 17…60, manuális módban pedig
a rutin az eredeti bájtot adja vissza. Így egyetlen `setf` elintézi.

### 52.5 Az ellenőrzés

| ellenőrzés | eredmény |
|---|---|
| visszadisassemblálás, mind a 27 utasítás (3 × 9) | ✅ |
| a csere **utáni** `st.b r1, -3188x[gp]` érintetlen | ✅ |
| minden elágazás a saját rutinján belül | ✅ |
| logikai önteszt a mért táblán | **6/6 OK** |
| bájt-diff az eredetihez | **94 bájt**: 3 × 4 hook + 84 rutin + 2 CRC |
| a V1 hookja (`0x37848`) visszaállt eredetire | ✅ |
| belső flash CRC `resign` után | `2991` ✅ |
| VBF blokk-CRC | **`B9A6`** ✅ |
| VBF file-CRC32 | `05CC35CA` ✅ |

**Kimenet:** `F1ET-18D619-AM_LEDAUTO_V2.vbf`

### 52.6 AZ AUTÓBAN IGAZOLVA (2026-08-26)  **[B, mérés]**

A `F1ET-18D619-AM_LEDAUTO_V2.vbf` beflashelve, a felhasználó megerősítette:
**a fúvási-irány LED-ek AUTO módban működnek és követik a szabályozást.**

Ezzel a §9-ben 2026-08-21-én felvetett kérdés — „miért sötét mind a három
irány-LED AUTO-ban" — a teljes láncon végigkövetve **lezárult**:

```
felismeres (9.)  ->  a mode 9 szandekosan nullaz
meres     (50.)  ->  a mod-ajtok VALOJABAN mozognak (17..60 %), a tabla
                     fej/lab hozzarendelese viszont forditott volt
V1        (51.)  ->  rossz beakasztasi pont: allapotgep = belepesi akcio
V2        (52.)  ->  a ciklusonkent futo fogyasztoi oldal  ->  MUKODIK
```

**Az egyetlen dolog, ami a V1-et megbuktatta, egy hibás feltevés volt arról,
hogy MIKOR fut a kód — nem a logika, nem a küszöbök, nem a kódolás.**
A küszöbök (27 / 47 / 48) az első nekifutásra helyesek voltak, mert a
felhasználó saját, autóban mért táblájából jöttek.

---

## 53. A `0xFD0A` MEGVILÁGÍTÁS-KALIBRÁCIÓ TELJESEN DEKÓDOLVA  **[B]**

**Eszköz:** `tools/illum.py` (`decode` / `set` / `scale`)

### 53.1 A rekord szerkezete

A modul a `0x53B8A`-nál **86 bájtot** tölt a `0xFE000080` NVM-blokkból a
`gp-23218`-tól, majd a `0x53BAA`-nál ellenőrzi:

```
43 x u16 (BIG ENDIAN):
  [0..41]   21 par (min, max)   --  minden parra KOTELEZO: min < max
  [42]      XOR(hw[0..41]) ^ 0x0042        (ellenorzo osszeg)
```

Az UDS `22 FD 0A` olvasás ebből a **84 adatbájtot** adja vissza, plusz **4
fixen nullázott bájtot** (`0x25682`: `sst.b r0`) → összesen 88.
**Az ellenőrző összeg NINCS benne az As-Built stringben.**

**Ha az ellenőrzés megbukik** (rossz checksum vagy bármelyik páron
`min >= max`), a modul a `0x53F6E`-nél a **gyári, flashbeli alapértékekre**
esik vissza. Vagyis egy hibás rekord **nem tesz kárt** — csak elveszti a
finomhangolást.

### 53.2 A felhasználás

```
FUN_540C8(csatorna, szint):
    lo  = **(u16**)(gp-23132 + 4*csatorna)      ; MUTATOTABLA a min-re
    hi  = **(u16**)(gp-23040 + 4*csatorna)      ; MUTATOTABLA a max-ra
    raw = lo + (hi - lo) * (szint - 1) / 1022   ; szint 1..1023

FUN_5410A(csatorna, szint):
    ha szint == 0        -> ertek = 0
    tipus = tabla_0x11FAE[csatorna]             ; 0 = nem hajtott
    pct   = (tipus == 1) ? gp-30801 : gp-30802  ; GLOBALIS fenyero, 0..100 %
    ertek = max(1, raw * pct / 100)             ; 16 bites PWM
    FUN_2B902(csatorna, ertek)
```

A `gp-23132` / `gp-23040` tehát **nem a min/max táblák, hanem 23-23 darab
u32 MUTATÓ** rájuk. Ezeket a `0x53E0A…0x53F66` tölti fel az NVM-blokkba
mutatva (siker) vagy a flash-alapértékekre (bukás).

> **Javítás a §44.1-hez:** ott „a `gp-23132` (min) és `gp-23040` (max)
> kalibrációs táblák" szerepel. Valójában **mutatótáblák**; az értékek a
> `0xFD0A`-ból jönnek.

### 53.3 A csatorna → pár leképezés — teljes

A `0x53E0A…0x53F66` mutatófeltöltésből kiolvasva: **csatorna k → pár k**
egy-az-egyben `k = 0…17`-ig, a **18. és 19. csatorna LETILTVA** (NULL
mutató, és a `0x11FAE` típusa is 0), majd 20/21/22 → 18/19/20. pár.

A felhasználó modulján mért értékek (`WZ8V128233`):

| csat | pár | típus | min | max | max % | bájtok | szerep |
|---|---|---|---|---|---|---|---|
| 0 | 0 | 2 | `011B` | `3745` | 21,6 % | 0–3 | |
| 1 | 1 | 2 | `00CC` | `27CD` | 15,5 % | 4–7 | |
| 2 | 2 | 2 | `009A` | `1E07` | 11,7 % | 8–11 | |
| 3 | 3 | 1 | `0211` | `89AD` | 53,8 % | 12–15 | |
| 4 | 4 | 1 | `0170` | `5FCB` | 37,4 % | 16–19 | |
| 5 | 5 | 1 | `0208` | `8780` | 52,9 % | 20–23 | |
| 6 | 6 | 1 | `01F8` | `8344` | 51,3 % | 24–27 | |
| 7 | 7 | 2 | `00BB` | `248B` | 14,3 % | 28–31 | |
| 8 | 8 | 2 | `00A6` | `206B` | 12,7 % | 32–35 | |
| 9 | 9 | 2 | `00A4` | `1FF2` | 12,5 % | 36–39 | |
| 10 | 10 | 2 | `00C6` | `26A5` | 15,1 % | 40–43 | |
| 11 | 11 | 1 | `02C0` | `37B5` | 21,8 % | 44–47 | |
| 12 | 12 | 1 | `0272` | `32B5` | 19,8 % | 48–51 | |
| 13 | 13 | 1 | `06A4` | `9C7A` | 61,1 % | 52–55 | |
| 14 | 14 | 1 | `05B4` | `909C` | 56,5 % | 56–59 | |
| **15** | **15** | 1 | `0688` | `B049` | **68,9 %** | **60–63** | **SZÉLVÉDŐ irányLED** |
| **16** | **16** | 1 | `078C` | `CA28` | **79,0 %** | **64–67** | **FEJ irányLED** |
| **17** | **17** | 1 | `0575` | `A077` | **62,7 %** | **68–71** | **LÁB irányLED** |
| 18 | — | 0 | — | — | — | — | **LETILTVA** |
| 19 | — | 0 | — | — | — | — | **LETILTVA** |
| 20 | 18 | 1 | `00ED` | `2E4D` | 18,1 % | 72–75 | |
| 21 | 19 | 1 | `0776` | `8F3C` | 56,0 % | 76–79 | |
| 22 | 20 | 1 | `005A` | `7392` | 45,1 % | 80–83 | |

Ellenőrző összeg ehhez a rekordhoz: **`0xE17A`**.

### 53.4 A három irány-LED azonosítása — bizonyítva

A `0x509F8…0x50A70` (`FUN_50674`) a `FUN_38F4E`-vel lemásolja a
`gp-31888` indikátor-struktúrát, és a másolat bájtjaiból kapcsol:

| kód | struktúra-bájt | változó | LED-csatorna |
|---|---|---|---|
| `0x50A00`: `ld.bu 68[sp]`, dest = `sp+68` | +0 | `gp-31888` = **LÁB** | **17** |
| `0x50A2C`: `ld.bu 53[sp]`, dest = `sp+52` | +1 | `gp-31887` = **FEJ** | **16** |
| `0x50A58`: `ld.bu 38[sp]`, dest = `sp+36` | +2 | `gp-31886` = **SZÉLVÉDŐ** | **15** |

Ez **egybevág a §52 patchével** (ugyanaz a három bájt, ugyanabban a
sorrendben), és megadja a §44 nyitott kérdésének a válaszát a három
LED-csatornára.

### 53.5 A típustábla (`0x11FAE`, 23 bájt)

```
csat:  0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22
tip:   2 2 2 1 1 1 1 2 2 2  2  1  1  1  1  1  1  1  0  0  1  1  1
```

`1` → a `gp-30801` globális százalék, `2` → a `gp-30802`, `0` → nem hajtott.
Ez **nem** a §9-ben feltételezett „0…10 háttér / 11…17 visszajelző" bontás;
a két csoport a `{0,1,2,7,8,9,10}` és minden más.

### 53.6 Az írásról — amit tudunk és amit nem

A `0x2E` fehérlistán a `FD0A` rajta van, és FORScan As-Builtből írható.
**Nyitott:** a `0x258FA` írókezelő egy általános NVM-író állapotgép
(`FUN_29DF0` / `FUN_29ECA`), amiből **nem derült ki, hogy a 43. halfwordöt
(az ellenőrző összeget) a modul maga számolja-e**, vagy a beírt blokk
valahogy tartalmazza.

**A kockázat viszont korlátozott:** ha az összeg nem stimmel, a modul a
`0x53F6E`-nél a gyári alapértékekre esik vissza. A legrosszabb eset tehát
**a gyári fényerő**, nem hibás működés.

### 53.7 Mit lehet vele csinálni

```bash
python tools/illum.py decode <88-bajtos-hex>
python tools/illum.py set    <hex> 17 --max 0xCA28     # a LAB LED-et a FEJ szintjere
python tools/illum.py scale  <hex> 15 1.25             # a SZELVEDO LED-et +25 %-kal
```

A `set`/`scale` **megtagadja** az érvénytelen értéket (`min >= max`), mert azt
a modul is elutasítaná.

Példa: a három irány-LED gyárilag **különböző** maximumot kap
(79,0 % / 68,9 % / 62,7 %) — ez a LED-ek eltérő hatásfokának a
kompenzációja. Ha egyenlő fényűre akarod őket, ezt a három párt kell
egymáshoz igazítani.

---

## 54. KORREKCIÓ: a négy kifúvási NTC-t a modul IGENIS HASZNÁLJA  **[B]**

> **A §49 alapfeltevése — „a modul négy kalibrált kifúvási NTC-t hordoz, és
> egyiket sem használja" — TÉVES.** A felhasználó kételkedett benne („a Fordot
> ismerve nem tenne be semmi érzékelőt, ha nem muszáj"), és igaza lett.

### 54.1 A teljes fogyasztói lánc

A négy NTC (ADC-index 0…3) útja:

```
FUN_4FF8E(i) -> gp-29002[i]
  -> a 0x3E9A8..0x3ECA8 hihetoseg-allapotgepek  (gp-31512..31520)
  -> KIPUBLIKALVA:  gp-29090 / 29092 / 29094 / 29096 / 29098 / 29100
  -> getterek: FUN_3E8E8 / 3E8EE / 3E8F4 / 3E8FA / 3E900 / 3E906
```

És ezeknek a gettereknek **nem csak az UDS DID-ek a hívói**:

| hívó | mit csinál |
|---|---|
| `0x43054` (`FUN_42DA2`) | `FUN_3E8FA() + FUN_3E906()`, majd `shl 4` — **a pár átlaga** |
| `0x43F56` (`FUN_43E64`) | `FUN_3E8F4() + FUN_3E900()`, majd `shl 4` — **a másik pár átlaga** |
| `0x44634` | `max(FUN_3E8DC(), FUN_3E8E8())` — **a nagyobbik hőmérséklet** |
| `0x483A6` | ugyanaz a `max` minta |
| `0x251B8/25204/25250/2529C` | a `9B04…9B07` UDS DID-ek |

### 54.2 Mire kellenek — a valószínű ok

A **`FUN_42DA2`** (`0x42DA2…0x43765`) az a függvény, ami a `0x4372E`-nél a
**`gp-29062`-t** írja — a **becsült belső hőmérsékletet** (§39.1). A `0x43054`
kifúvási NTC-pár tehát **ennek a becslésnek a bemenete.**

Ez pontosan megmagyarázza, miért van négy érzékelő: **a modulban NINCS
belsőtér-érzékelő** (§4). Ahelyett hogy egy szívócsöves utastér-szenzort
építene be, a Ford **négy kifúvási NTC-ből + modellből** számolja a
belső hőmérsékletet. Az érzékelők nem „kihasználatlanok" — ők a
belsőhő-becslés mérési horgonyai.

Emellett saját DTC-jük is van: **B10B3 / B10B4 / B10B5 / B10B6** (a
`0x0BC34` táblából), és hiba esetén a `0x3EACA` egy **kalibrált
alapértékkel** helyettesíti a jelet (`cal+160`) — ami szintén csak akkor
indokolt, ha az értéket tényleg használják.

### 54.3 Mit jelent ez a §49-re

| §49 állítás | státusz |
|---|---|
| „a négy kifúvási NTC-t semmi nem használja" | **CÁFOLVA** |
| „egyiket sem használja a keverőajtó korrigálására" | **valószínűleg áll** — a mért út a belsőhő-becslésbe vezet, nem a keverőajtó-korrekcióba, de ez **[E]** amíg a `FUN_42DA2` teljes egészében nincs lebontva |
| a zárt hurkú kifúvási trim ötlete | **nem dől meg, de átgondolandó**: ha ugyanaz a jel már most hat a belsőhő-becslésen keresztül a szabályozásra, akkor egy ráépített integrátor **kettős visszacsatolást** hozna létre — ez instabilitás forrása lehet |

**A §49 következő lépése tehát megváltozik:** nem az integrátor RAM-helyének
keresése, hanem a **`FUN_42DA2` lebontása** — pontosan hogyan és milyen
súllyal hat a négy NTC a belsőhő-becslésre.

### 54.4 Módszertani tanulság

A §49 két „független kutatási menetre és négy szabadalomra" hivatkozott, de
**a fogyasztói oldalt sosem kereste vissza**. Az `xref` a getterekre
(`FUN_3E8E8` és társai) tíz perc alatt megadta volna a választ.

> **Szabály:** mielőtt bármiről kijelentjük, hogy „nem használt", végig kell
> menni a **teljes** hívási láncon — a nyers ADC-től a publikált getterekig,
> és azok MINDEN hívóján. A közbenső publikálás (`gp-2909x`) elrejti a
> kapcsolatot a naiv keresés elől.

---

## 55. A `can_dir` PATCH — az AUTO fúvási irány a CAN-en is  **[B]**

**Eszköz:** `tools/patch_can_dir.py` · **Testvérpatch:** `patch_led_auto.py` (§52)
**Mérés:** a felhasználó megerősítette — manuálisan **mutat** valamit a kijelzőn,
AUTO-ban **semmit**. Ugyanaz a hiba, másik kimeneten.

### 55.1 A számítás

A `0x4CD48…0x4CDAA` kizárólag a `mode`-ból állítja a `gp-30695` bitjeit:

| bit | feltétel | jelentés (§50.3 korrekcióval) |
|---|---|---|
| 0 | mode ∈ {1,4,6,7} | **LÁB** |
| 1 | mindig 1 | — |
| 2 | mode ∈ {2,4,5,7} | **FEJ** |
| 3 | mode ∈ {3,5,6,7,8} | **SZÉLVÉDŐ** |

AUTO (mode 9) egyik halmazba sem esik → mind törlődik → `B5 = 0xF2`.
Pontosan ezt mutatta a passzív MS-CAN log (§50.4).

### 55.2 A beakasztás

`0x4CDAA` (`clr1 3, -30695[gp]`, 4 bájt) → `jarl 0x77E54, lp`.

Ez a cím a **szélvédő-feltétel bukott ága**, és AUTO-ban **mindig** erre fut
(9 ∉ {3,5,6,7,8}). Manuális módban vagy szintén ide fut — ekkor a rutin csak
az eredeti `clr1`-et végzi el és kilép —, vagy a `0x4CDA4` `set1`-re ugrik,
oda nem nyúlunk.

Az `lp` elrontása biztonságos: a befoglaló függvény a `0x4CCC6`-nál
`prepare 31, 0x1870`-nel menti, és maga is hív `jarl`-t (`0x4CDAE`).

**A `set1`/`clr1` kódolása négy valódi firmware-utasításon ellenőrizve**
(`0x4CD58` / `0x4CD5E` / `0x4CD7E` / `0x4CDA4`) — bájtra egyezik.

### 55.3 A rutin (`0x77E54`, 68 bájt)

```
77E54  c49f1988   clr1     3, -30695[gp]     ; az EREDETI utasitas
77E58  a40fa582   ld.bu    -32091[gp], r1    ; mode
77E5C  690a       cmp      9, r1
77E5E  ca1d       bnz      0x77E96           ; nem AUTO -> kesz
77E60  e40f8d8e   ld.hu    -29044[gp], r1    ; --- FEJ ---
77E64  010ee5ff   addi     -27, r1, r1
77E68  c605       blt      0x77E70
77E6A  c4171988   set1     2, -30695[gp]
77E6E  b505       br       0x77E74
77E70  c4971988   clr1     2, -30695[gp]
77E74  e40f8d8e   ld.hu    -29044[gp], r1    ; --- LAB ---
77E78  010ed1ff   addi     -47, r1, r1
77E7C  ce05       bge      0x77E84
77E7E  c4071988   set1     0, -30695[gp]
77E82  b505       br       0x77E88
77E84  c4871988   clr1     0, -30695[gp]
77E88  e40f898e   ld.hu    -29048[gp], r1    ; --- SZELVEDO ---
77E8C  010ed0ff   addi     -48, r1, r1
77E90  b605       blt      0x77E96
77E92  c41f1988   set1     3, -30695[gp]
77E96  7f00       jmp      [lp]
```

### 55.4 Ellenőrzés

| | |
|---|---|
| visszadisassemblálás, mind a 21 utasítás | ✅ |
| mind a 6 elágazás a rutinon belül | ✅ |
| **konzisztencia a LED-patchcsel** — ugyanaz a bemenet, ugyanaz az eredmény | ✅ 5/5 |
| a `set1`/`clr1` kódolás valódi firmware-utasításokon | ✅ 4/4 bájtra |

Amit AUTO-ban ki fog küldeni (a `B5` alsó nibble-je):

| állapot | előtte | utána |
|---|---|---|
| max hűtés / meleg 21-22 °C | `0x2` | **`0x6`** = fej |
| közép | `0x2` | **`0x7`** = fej+láb |
| max fűtés | `0x2` | **`0x3`** = láb |

### 55.5 Flash-térkép a szabad területen

```
0x77E00..0x77E53   led_auto harom rutinja   (84 bajt)
0x77E54..0x77E97   can_dir rutin            (68 bajt)
0x77E98..0x77EFF   szabad                   (104 bajt)
```

### 55.6 A kombinált fájl

```
python tools/buildfw.py build led_auto can_dir dualzone -o F1ET-18D619-AM_V3.vbf
```

A `buildfw.py` mostantól ismeri a `led_auto` és `can_dir` kód-patcheket is.
Az eredmény: **165 bájt eltérés**, 14 tartományban — a 4 hook, a két rutin,
a `dualzone` két kalibrációs bájtja (C346 és C346FAP), és a CRC.
Blokk-CRC `B9A6` ✅, belső CRC `1B8C` ✅, file-CRC `6F05818A` ✅.

---

## 56. A `FD0A` FÉNYERŐ-KIEGYENLÍTÉS — kész rekord  **[B]**

A három irány-LED gyárilag különböző maximumot kap (§53.3):

| csat | LED | gyári max | gyári % |
|---|---|---|---|
| 16 | FEJ | `CA28` | 79,0 % |
| 15 | SZÉLVÉDŐ | `B049` | 68,9 % |
| 17 | LÁB | `A077` | 62,7 % |

Mindhármat a legfényesebbre (`0xCA28` = 79,0 %) igazítva **4 bájt változik**
a 88-ból: a **62–63.** (szélvédő max) és a **70–71.** (láb max).

```
EREDETI:
011B374500CC27CD009A1E07021189AD01705FCB0208878001F8834400BB248B00A6206B
00A41FF200C626A502C037B5027232B506A49C7A05B4909C0688B049078CCA280575A077
00ED2E4D07768F3C005A739200000000

KIEGYENLITVE:
011B374500CC27CD009A1E07021189AD01705FCB0208878001F8834400BB248B00A6206B
00A41FF200C626A502C037B5027232B506A49C7A05B4909C0688CA28078CCA280575CA28
00ED2E4D07768F3C005A739200000000
```

A `min < max` invariáns mind a 21 páron teljesül, tehát a modul elfogadja —
feltéve, hogy az ellenőrző összeget íráskor maga számolja (§53.6, nyitott).
Ha nem: a modul a **gyári alapértékekre** esik vissza, ami ártalmatlan, és az
eredeti stringgel bármikor visszaírható.

> **A gyári eltérés valószínűleg szándékos** — a három LED eltérő
> hatásfokának a kompenzációja. A kiegyenlítés tehát ízlés kérdése, nem
> hibajavítás: lehet, hogy egyenlő PWM mellett **nem** lesznek egyforma
> fényűek. Ezért érdemes előbb megnézni, hogy a mostani állapot zavaró-e.
