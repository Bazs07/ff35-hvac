# HVAC — Handoff Summary

This file consolidates the project handoff notes that previously lived in the working folder
(`HANDOFF.md`, since removed) into a short synthesis. It reflects the state of investigation as of
2026-08-26.

## What was investigated
- Full reverse engineering of the Ford Focus Mk3.5 DEATC (automatic climate control) ECU firmware
  `F1ET-18D619-AM` (NEC/Renesas V850 Fx4-L core), including memory map, RTOS-style task scheduler,
  CAN message handling, the variant calibration blocks, NVM/EEPROM layout, UDS diagnostic services,
  and the internal flash-CRC integrity scheme.
- In particular: why the three air-distribution "direction" LEDs on the control panel stay dark
  while the system is in AUTO mode, and whether the AUTO air-distribution logic actually adapts to
  conditions or is stuck at a fixed door position.
- A live CAN/UDS measurement pass on the actual vehicle to confirm or refute hypotheses that could
  not be settled by static analysis alone.

## What was learned / decided
- The firmware's checksum chain (VBF block CRC16, VBF file CRC32, and an internal flash CRC16 at
  offset `0x77FF4`) was fully reverse engineered and is round-trip verified: unpack → patch →
  resign → pack reproduces a bit-identical file for unmodified input.
- Early analysis passes contained a number of mistaken conclusions (wrong variable roles, wrong
  mode-to-door mapping, a mis-decoded LED subsystem, etc.) that were later corrected through deeper
  code review and live measurement — the corrections are catalogued in the original notes as a
  "corrections" table so later readers don't rely on the superseded claims.
- Root cause of the dark AUTO-mode indicator LEDs: in AUTO (mode 9) the firmware computes a
  continuous door position rather than one of the discrete named modes, so it has nothing discrete
  to report and intentionally zeroes the three indicator bits — this is confirmed by both static
  code analysis and live CAN capture (`0x190` byte 5 = 0xF2 in AUTO vs. 0x43 in manual head mode).
- A live-measurement pass disproved an earlier hypothesis that the AUTO air-distribution door was
  "stuck" at a fixed position (58%); it actually moves between roughly 17–60%, which means the more
  invasive "adaptive AUTO distribution" patch (`AUTODIST`/`COMBO` variants) is unnecessary and should
  **not** be flashed. The simpler LED-only patch is the validated, correct fix.
- A working LED-indicator patch (`LEDAUTO_V2`) was built, flashed to the actual vehicle, and
  confirmed working. An earlier LED patch attempt (`LEDAUTO` V1) failed (LED froze) and was
  superseded.
- A dual-zone calibration tweak (`cal[569]` 32→48) was identified as a separate, low-risk pure
  calibration change, independent of the LED/AUTO-distribution work.
- Full toolchain exists and works: V850 disassembler, VBF pack/unpack, flash-CRC resign, calibration
  reader/patcher, an HVAC cabin-thermal model reimplementation, UDS/live-data client, and a one-shot
  firmware builder (`buildfw.py`) that reproduces known-good VBFs bit-for-bit as a self-check.

## Open questions / blockers
- The seat-heater "remember last level" feature needs a persistent RAM location; whether the
  runtime state actually survives ignition cycles in battery-backed RAM was unverified and is
  flagged as needing confirmation (the NVM block map does not show a seat-heater-level entry).
- Which of the two "mode-door" outputs corresponds to panel/floor vs. defrost was partly resolved
  through later sections of the analysis, but a few secondary items (e.g., meaning of a specific CAN
  byte bit, whether a particular internal routine is armed via configuration) remained open at
  handoff time and were flagged for a live CAN/UDS check on the vehicle.
- The As-Built configuration record format (`FD0A`, 88 bytes) was decoded, but how the checksum is
  computed when *writing* it (vs. reading) was not confirmed — considered low risk since a failed
  write falls back to factory defaults.
- The seat-heating auto-on-when-cold and "seat memory" features were designed but not implemented at
  handoff time; the recommended combined design (restore seat heat level based on outside
  temperature rather than unconditionally) was proposed but not yet built.
