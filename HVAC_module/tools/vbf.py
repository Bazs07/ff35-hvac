#!/usr/bin/env python3
"""Ford VBF 2.4 ki/becsomagolo a HVAC (DEATC) modulhoz.

  python tools/vbf.py unpack <file.vbf>          -> <part>_<addr>.bin + header.txt
  python tools/vbf.py pack  <orig.vbf> <bin> <out.vbf>
  python tools/vbf.py verify <file.vbf>

Bizonyitott (2026-08-21):
  blokk-checksum = CRC16-CCITT (poly 0x1021, init 0xFFFF), a blokk adatan
  file_checksum  = szabvanyos CRC32 a header utani teljes binaris testen
Mindket VBF-en (619-AM es 618-AA) pontosan egyezik.
"""
import sys, os, re, zlib, struct

def split(raw):
    i = raw.index(b'header'); depth = 0; j = i
    while True:
        c = raw[j:j+1]
        if c == b'{': depth += 1
        elif c == b'}':
            depth -= 1
            if depth == 0: break
        j += 1
    off = j + 1
    while raw[off] in (10, 13, 32, 9): off += 1
    return raw[:off], raw[off:]

def crc16(data, poly=0x1021, init=0xFFFF):
    c = init
    for b in data:
        c ^= b << 8
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFFFF if c & 0x8000 else (c << 1) & 0xFFFF
    return c

def blocks(body):
    out, off = [], 0
    while off < len(body) - 4:
        addr, ln = struct.unpack('>II', body[off:off+8])
        if off + 10 + ln > len(body): break
        data = body[off+8:off+8+ln]
        chk = struct.unpack('>H', body[off+8+ln:off+10+ln])[0]
        out.append((addr, data, chk))
        off += 10 + ln
    return out

def main():
    cmd = sys.argv[1]
    raw = open(sys.argv[2], 'rb').read()
    hdr, body = split(raw)
    bl = blocks(body)
    if cmd in ('unpack', 'verify'):
        fc = int(re.search(rb'file_checksum\s*=\s*0x([0-9A-Fa-f]+)', hdr).group(1), 16)
        ok = zlib.crc32(body) & 0xFFFFFFFF
        print('file_checksum  header=%08X  szamolt=%08X  %s' % (fc, ok, 'OK' if fc == ok else 'ELTER'))
        for a, d, c in bl:
            print('blokk %08X  len=0x%X  chk=%04X szamolt=%04X %s'
                  % (a, len(d), c, crc16(d), 'OK' if c == crc16(d) else 'ELTER'))
            if cmd == 'unpack':
                n = '%s_%08X.bin' % (os.path.splitext(os.path.basename(sys.argv[2]))[0], a)
                open(n, 'wb').write(d); print('   ->', n)
    elif cmd == 'pack':
        new = open(sys.argv[3], 'rb').read()
        assert len(bl) == 1, 'tobb blokkos VBF-hez bovitsd a scriptet'
        addr = bl[0][0]
        assert len(new) == len(bl[0][1]), 'meret valtozott (%d != %d)' % (len(new), len(bl[0][1]))
        nb = struct.pack('>II', addr, len(new)) + new + struct.pack('>H', crc16(new))
        nh = re.sub(rb'file_checksum\s*=\s*0x[0-9A-Fa-f]+',
                    b'file_checksum = 0x%08x' % (zlib.crc32(nb) & 0xFFFFFFFF), hdr)
        open(sys.argv[4], 'wb').write(nh + nb)
        print('kiirva:', sys.argv[4], len(nh + nb), 'bajt')
    else:
        print(__doc__)

main()
