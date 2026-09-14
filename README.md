# HVAC — Automatic Climate Control / DEATC Module (Ford Focus Mk3.5)

The HVAC module (Ford calls it DEATC — Dual/Electronic Automatic Temperature Control) runs the
vehicle's automatic climate control: cabin temperature regulation, blower speed, air-distribution
door positioning, recirculation, A/C compressor request, heated-seat control, and button/LED
feedback on the control panel. Its diagnostic address is `0x733` on MS-CAN. This is by far the
most completely reverse-engineered module in this project — essentially the entire firmware has
been mapped, and multiple working patches have been built and flashed to a real vehicle.

## What we know

- **Hardware/platform:** NEC/Renesas V850 (Fx4-L family), made by Visteon. Firmware identifies
  itself internally as unit part number `DS-F1ET-18C612-AG`, calibration ID `BE05F012`,
  `Copyright 1998, Visteon Corp`.
- **Firmware present:** main application `F1ET-18D619-AM` (459,474 bytes, one block
  `0x00008000`–`0x00077FFF`), plus its SBL/flash-driver `F1ET-18D618-AA` (4,591 bytes, loaded at RAM
  address `0xFEDF8000`, used only during flashing, not part of normal operation).
- **Runtime architecture:** a static, OSEK-like scheduler with function-pointer tables
  (init/hook lists, a ~125+81-entry periodic task list, a tick handler decrementing ~10 software
  timers). Roughly 1,838 functions identified across the code region `0xC000`–`0x5B000` plus a
  second block `0x57000`–`0x59000`.
- **I/O inventory, fully mapped:** 7 analog climate sensors (ADC channels for two exhaust-air
  temperatures, panel exhaust temperature ×2, two sun-load sensors, one outside-temperature sensor),
  3 more ADC channels for heated-seat NTC thermistors, 5 stepper-motor door actuators (recirculation,
  two mode/air-distribution doors, two temperature-blend doors), heated-seat outputs with 2×3-level
  indicator LEDs, and a diagnostic I/O-override path. There is **no cabin (interior) temperature
  sensor** — interior temperature is instead estimated by a software thermal model (see below).
  There is no display controller of any kind in this module — it drives buttons and indicator LEDs
  only.
- **Checksums — fully solved:** VBF block checksum is CRC16-CCITT (poly `0x1021`, init `0xFFFF`);
  VBF file checksum is standard CRC32; and an **internal flash-integrity CRC** (background task,
  poly `0x1021`, init `0x0000`, table-driven, table at `0x11FC6`) covers `0x8000`–`0x77FF3` and is
  stored big-endian at `0x77FF4` (factory value `0xD8DF`, independently recomputed and confirmed to
  match). Any firmware edit must re-run this internal CRC (`fwcrc.py resign`) or the module raises a
  fault code (22 / U3000-41). The full patch round-trip (unpack → edit → resign → pack) has been
  verified to reproduce a bit-identical VBF when no actual change is made.
- **Calibration data, fully mapped:** a header block (`0xBB40`–`0xBD90`) with part numbers and
  configuration bytes; global calibration tables at `0xC800`–`0xE400` (e.g. an 8.8 fixed-point
  blower-voltage map, 6.0–12.0 V, and a 29-step, 0.5 °C set-point table from 16.0–30.0 °C); and six
  vehicle/body-style-specific calibration blocks (`C344GM`, `C344CM`, `C346` [Focus], `C346NA`,
  `C346FAP`, `C344NA`), each 0x9E0 bytes, fully offset-mapped in `HVAC_module/CAL_BLOKK_TERKEP.txt`
  (602 offsets, each with the function that reads it).
- **Air-distribution ("AUTO mode direction LEDs are always dark") investigation — fully resolved
  and fixed:** in AUTO mode the firmware computes a *continuous* door position rather than picking
  one of the ten discrete named modes (off/head/floor/defrost/combinations), so there is nothing
  discrete to display and the three indicator-LED bits are intentionally zeroed
  (`FUN_37820`/mode 9). This was confirmed independently through static code analysis and live
  CAN capture (message `0x190`, byte 5: `0xF2` in AUTO vs `0x43` in manual head mode). A working fix
  was designed, built, flashed to a real vehicle, and confirmed functioning: derive the three
  indicator bits from the actual door position instead of zeroing them.
- **AUTO air-distribution "stuck door" hypothesis — investigated and disproved:** an earlier
  hypothesis that the AUTO-mode air-distribution door was pinned at a fixed 58% position was
  disproved by live measurement (it actually ranges roughly 17–60%, adapting normally); a more
  invasive "adaptive AUTO redistribution" patch was therefore judged unnecessary and explicitly
  should not be flashed.
- **Heated-seat behavior:** heated-seat level is intentionally reset to off on every controller
  wake-up/power-on (`FUN_534DE`), gated by ignition/run-state — this is confirmed to be a deliberate
  runtime gate, not just a one-time init.
- **Temperature/blend-door control model:** an outside-air-temperature estimator, a cabin thermal
  model (a two-node — air mass and cabin air — thermal simulation updated at 1.25 s intervals, whose
  state is saved across ignition cycles in NVM), and nine calibration curves feeding a blend-door
  position calculator were all reverse engineered function-by-function, including the breakpoint
  table format used throughout the calibration data.
- **UDS diagnostics:** service and DID (data identifier) tables were decoded (a 48-entry, 16-byte
  DID table at `0xB2CC`; a service-ID map at `0xAD55`/`0xAD9C`), including several militarily useful
  live-data IDs (outside temperature, blower duty cycle, recirculation/door positions, the four
  exhaust-air NTC readings, and an 88-byte As-Built configuration block).

## Current status / what's been done

- Complete firmware disassembly (`tools/dump.py` → `full.asm`, 9.2 MB) and a large custom Python
  toolset (`tools/`) covering VBF pack/unpack, internal-CRC verify/resign, calibration read/patch,
  a cabin thermal-model reimplementation, UDS/live-data client, NVM block-map reader, and a one-shot
  firmware builder.
- Two patches built, flashed to a real vehicle, and confirmed working:
  - `F1ET-18D619-AM_LEDAUTO_V2.VBF` — the AUTO-mode direction-LED fix (validated fix).
  - A dual-zone calibration tweak (`cal[569]` 32→48, in `F1ET-18D619-AM_DUALZONE.VBF`).
- One earlier LED patch attempt (`F1ET-18D619-AM_LEDAUTO.VBF`, V1) failed on the vehicle (LED froze)
  and was superseded by V2.
- One more invasive patch (`F1ET-18D619-AM_AUTODIST.VBF`, adaptive AUTO air distribution) and its
  combination with the dual-zone tweak (`F1ET-18D619-AM_COMBO.VBF`) were built but **should not be
  flashed** — live measurement showed the premise behind them (a stuck door position) was false.
  `F1ET-18D619-AM_V3.VBF` is recorded as the then-current combined target build.
- A live CAN-bus measurement session on the vehicle confirmed several static-analysis hypotheses and
  corrected several others (see `HVAC_module/HVAC_ELEMZES.md` for the full, itemized list of
  corrections made over the course of the investigation).

## Plans / next steps


- Confirm whether the heated-seat level truly survives ignition cycles in battery-backed RAM (needed
  before implementing "seat memory"); if not, an NVM write needs to be added.
- Implement automatic heated-seat activation on cold starts, proposed to be combined with the seat
  memory feature (restore heat level only when outside temperature is below a threshold, rather than
  unconditionally).
- A few secondary open items remain around a specific CAN status bit and an internal routine's
  trigger condition — see `HANDOFF_SUMMARY.md` for the consolidated list of what was still open at
  last handoff.

## Note on `HVAC_module/HVAC_ELEMZES.md`

The deep, chronological analysis notebook for this module (`HVAC_module/HVAC_ELEMZES.md`, ~5,000
lines) remains in Hungarian in this snapshot. It is the single largest analysis document in this
project and a full line-by-line translation could not be completed in this pass; everything of
substance from it has been synthesized into this README and `HANDOFF_SUMMARY.md` above. Translating
that file in full is recommended as a follow-up if a fully English repository is required.
