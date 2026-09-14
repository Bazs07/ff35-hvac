#!/usr/bin/env python3
"""UCDS CanBus Player log-fajl generator UDS 0x22 lekerdezesekhez.

Formatum (a mukodo TBT_Player fajlokbol visszafejtve):
    <busz>:\t<ID hex>\t<8 adatbajt szokozzel>\t\t<timer>\t<delta>\n
"""
import sys

BUS = "3/11"          # MS-CAN, OBD pins 3/11
REQ_ID = "733"        # HVAC diagnosztikai kereses cime

# (DID, megnevezes) -- mind egyszavas valasz, nincs multiframe
CYCLE = [
    ("9B01", "mod-ajto #1 (panel/padlo)"),
    ("9834", "mod-ajto #2 (szelvedo)"),
    ("9924", "kulso homerseklet (OAT)"),
    ("9805", "fuvo kitoltes"),
]


def frame(did: str) -> str:
    """ISO-TP single frame: PCI=03, SID=22, DID hi/lo, 0-padding 8 bajtra."""
    data = ["03", "22", did[:2], did[2:], "00", "00", "00", "00"]
    return f"{BUS}:\t{REQ_ID}\t{' '.join(data)}\t\t0.0\t0.0\n"


def build(path: str, cycles: int) -> None:
    with open(path, "w", newline="\n") as fh:
        for _ in range(cycles):
            for did, _name in CYCLE:
                fh.write(frame(did))
    lines = cycles * len(CYCLE)
    print(f"{path}: {lines} keret ({cycles} ciklus x {len(CYCLE)} DID)")
    print(f"  500 ms Frames Delay mellett kb. {lines * 0.5 / 60:.1f} perc")


if __name__ == "__main__":
    build("HVAC_POLL_TEST.log", 10)
    build("HVAC_POLL_25MIN.log", 750)
