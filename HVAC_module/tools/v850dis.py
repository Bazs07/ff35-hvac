#!/usr/bin/env python3
"""V850 / V850ES (V850E1) disassembler for the Ford HCM firmware.

Design rule: only encodings that are certain get a mnemonic. Anything else is
emitted as `.hword 0x....  ?` so an uncertain decode can never be mistaken for
a fact. The unknown rate is itself the quality metric -- see selftest().

Usage:
    python v850dis.py <va> [count]        disassemble `count` instructions
    python v850dis.py --func <va>         follow one function to its returns
    python v850dis.py --selftest          decode-quality + anchor validation
    python v850dis.py --xref <va>         find jarl/jr/branch sources targeting va
"""
import sys

BIN = 'F1ET-18D619-AM_00008000.bin'
BASE = 0x00008000

REG = ['r0', 'r1', 'r2', 'sp', 'gp', 'tp'] + ['r%d' % i for i in range(6, 30)] + ['ep', 'lp']
COND = ['v', 'l', 'z', 'nh', 'n', 'r', 'lt', 'le',
        'nv', 'nl', 'nz', 'h', 'p', 'sa', 'ge', 'gt']


def sx(v, bits):
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


class Insn:
    __slots__ = ('va', 'size', 'text', 'target', 'kind', 'ok')

    def __init__(self, va, size, text, target=None, kind=None, ok=True):
        self.va, self.size, self.text = va, size, text
        self.target, self.kind, self.ok = target, kind, ok

    def __str__(self):
        t = '' if self.target is None else '   ; -> 0x%05X' % self.target
        return '%08X  %-38s%s' % (self.va, self.text, t)


def decode(buf, off, va):
    """Decode one instruction at file offset `off` (virtual address `va`)."""
    if off + 2 > len(buf):
        return None
    hw1 = buf[off] | (buf[off + 1] << 8)
    r1 = hw1 & 0x1F
    r2 = (hw1 >> 11) & 0x1F
    opc = (hw1 >> 5) & 0x3F
    grp = (hw1 >> 7) & 0xF          # bits 10:7 select the format
    A, B = REG[r1], REG[r2]

    def hw(n):                       # fetch extension halfword n (1-based)
        p = off + 2 * n
        return (buf[p] | (buf[p + 1] << 8)) if p + 2 <= len(buf) else 0

    def unk(size=2):
        return Insn(va, size, '.hword 0x%04X' % hw1, kind='unk', ok=False)

    # ---- Format I : register-register, 16 bit -------------------------------
    if grp <= 3:
        if hw1 == 0:
            return Insn(va, 2, 'nop')
        if opc == 0x02 and r2 == 0:
            return Insn(va, 2, 'switch   %s' % A, kind='switch')
        if opc == 0x03:
            if r2 == 0:
                return Insn(va, 2, 'jmp      [%s]' % A, kind='ijmp')
            # V850E sld.bu / sld.hu.  sld.bu takes disp4; sld.hu takes disp5 =
            # field*2 (halfword granularity).  Getting this wrong silently
            # halves every sld.hu offset -- verified at 0x1E27C, where
            # `sld.hu 10[ep]` reads back the slot written by `sst.h r1, 20[ep]`
            # at 0x1E268 and re-read as `ld.hu 20[sp]` at 0x1F8E4.
            if (hw1 >> 4) & 1:
                return Insn(va, 2, 'sld.hu   %d[ep], %s' % ((hw1 & 0xF) * 2, B))
            return Insn(va, 2, 'sld.bu   %d[ep], %s' % (hw1 & 0xF, B))
        # V850E zxb/sxb/zxh/sxh occupy opc 4..7 with reg2 == 0
        if r2 == 0 and opc in (4, 5, 6, 7):
            return Insn(va, 2, '%-8s %s' % (['zxb', 'sxb', 'zxh', 'sxh'][opc - 4], A))
        name = ['mov', 'not', 'divh', None, 'satsubr', 'satsub', 'satadd', 'mulh',
                'or', 'xor', 'and', 'tst', 'subr', 'sub', 'add', 'cmp'][opc]
        return Insn(va, 2, '%-8s %s, %s' % (name, A, B))

    # ---- Format II : imm5, reg2, 16 bit -------------------------------------
    if grp <= 5:
        if opc == 0x10 and r2 == 0:
            return Insn(va, 2, 'callt    0x%02X' % (hw1 & 0x3F), kind='callt')
        if opc in (0x14, 0x15, 0x16):                     # shifts: imm5 unsigned
            return Insn(va, 2, '%-8s 0x%X, %s' % ({0x14: 'shr', 0x15: 'sar', 0x16: 'shl'}[opc], r1, B))
        name = {0x10: 'mov', 0x11: 'satadd', 0x12: 'add', 0x13: 'cmp', 0x17: 'mulh'}[opc]
        return Insn(va, 2, '%-8s %d, %s' % (name, sx(r1, 5), B))

    # ---- Format IV : short-format load/store via ep, 16 bit -----------------
    if grp == 6:
        return Insn(va, 2, 'sld.b    %d[ep], %s' % (hw1 & 0x7F, B))
    if grp == 7:
        return Insn(va, 2, 'sst.b    %s, %d[ep]' % (B, hw1 & 0x7F))
    if grp == 8:
        return Insn(va, 2, 'sld.h    %d[ep], %s' % ((hw1 & 0x7F) << 1, B))
    if grp == 9:
        return Insn(va, 2, 'sst.h    %s, %d[ep]' % (B, (hw1 & 0x7F) << 1))
    if grp == 10:
        d = (hw1 & 0x7E) << 1
        return (Insn(va, 2, 'sst.w    %s, %d[ep]' % (B, d)) if hw1 & 1
                else Insn(va, 2, 'sld.w    %d[ep], %s' % (d, B)))

    # ---- Format III : conditional branch, 16 bit ----------------------------
    if grp == 11:
        disp = sx((((hw1 >> 11) & 0x1F) << 3 | ((hw1 >> 4) & 7)) << 1, 9)
        tgt = va + disp
        c = COND[hw1 & 0xF]
        return Insn(va, 2, 'b%-7s 0x%05X' % (c, tgt), tgt,
                    kind='jmp' if c == 'r' else 'br')

    # ---- Format VI : imm16 ops, 32 bit --------------------------------------
    if grp in (12, 13):
        imm = hw(1)
        # V850E 48-bit  mov imm32, reg1  (movea slot with reg2 == 0)
        if opc == 0x31 and r2 == 0:
            v = imm | (hw(2) << 16)
            return Insn(va, 6, 'mov      0x%08X, %s' % (v, A))
        # V850E dispose sits in the movhi slot with reg2 == 0 (movhi into r0 is
        # pointless).  imm5 = hw1[5:1] stack words; the register list is in hw2.
        # This is a function EXIT -- without it a linear sweep runs past the end.
        if opc == 0x32 and r2 == 0:
            return Insn(va, 4, 'dispose  %d, 0x%04X%s'
                        % ((hw1 >> 1) & 0x1F, imm >> 1, ', [lp]' if (imm & 0x1F) == 0x1F else ''),
                        kind='ret')
        name = ['addi', 'movea', 'movhi', 'satsubi', 'ori', 'xori', 'andi', 'mulhi'][opc - 0x30]
        if opc in (0x34, 0x35, 0x36):                     # logical: zero-extended
            return Insn(va, 4, '%-8s 0x%04X, %s, %s' % (name, imm, A, B))
        return Insn(va, 4, '%-8s %d, %s, %s' % (name, sx(imm, 16), A, B))

    # ---- Format VII : load/store disp16, 32 bit -----------------------------
    if grp == 14:
        d16 = hw(1)
        if opc == 0x38:
            return Insn(va, 4, 'ld.b     %d[%s], %s' % (sx(d16, 16), A, B))
        if opc == 0x39:
            m, d = ('ld.w', sx(d16 & 0xFFFE, 16)) if d16 & 1 else ('ld.h', sx(d16, 16))
            return Insn(va, 4, '%-8s %d[%s], %s' % (m, d, A, B))
        if opc == 0x3A:
            return Insn(va, 4, 'st.b     %s, %d[%s]' % (B, sx(d16, 16), A))
        if opc == 0x3B:
            m, d = ('st.w', sx(d16 & 0xFFFE, 16)) if d16 & 1 else ('st.h', sx(d16, 16))
            return Insn(va, 4, '%-8s %s, %d[%s]' % (m, B, d, A))

    # ---- Format V : jr / jarl disp22, 32 bit --------------------------------
    # disp[21:16] live in hw1[5:0], disp[15:1] in hw2[15:1], disp[0] == 0.
    # Verified against the reset vector (0x04008 -> 0x0BF80) and the cornering
    # call sites (0x1D8C4/0x1D8D6 -> 0xF5CE, 0x1D8CA -> 0xF5E0).
    if opc in (0x3C, 0x3D):
        # V850E ld.bu shares the jr/jarl slot.  hw2 bit0 == 1 discriminates it,
        # because jr/jarl always have disp[0] == 0.  Since hw2 bit0 is spent on
        # the discriminator, ld.bu's own disp[0] lives in hw1 bit 5 -- i.e. in
        # the low bit of `opc`.  Confirmed by left/right symmetry at 0x1DFD8:
        # only -31797 belongs to the right-hand channel, -31798 is left-hand.
        h2 = hw(1)
        if h2 & 1:
            # prepare shares this slot: reg2 == 0 means the ld.bu would target
            # r0, which is meaningless, so reg2 == 0 marks a function ENTRY.
            if r2 == 0:
                return Insn(va, 4, 'prepare  %d, 0x%04X' % ((hw1 >> 1) & 0x1F, h2 >> 1))
            return Insn(va, 4, 'ld.bu    %d[%s], %s'
                        % (sx((h2 & 0xFFFE) | (opc & 1), 16), A, B))
        disp = sx(((hw1 & 0x3F) << 16) | (h2 & 0xFFFE), 22)
        tgt = va + disp
        if r2 == 0:
            return Insn(va, 4, 'jr       0x%05X' % tgt, tgt, kind='jmp')
        return Insn(va, 4, 'jarl     0x%05X, %s' % (tgt, B), tgt, kind='call')

    # ---- Format VIII : bit manipulation on disp16[reg1], 32 bit -------------
    if opc == 0x3E:
        d16 = sx(hw(1), 16)
        m = ['set1', 'not1', 'clr1', 'tst1'][(hw1 >> 14) & 3]
        return Insn(va, 4, '%-8s %d, %d[%s]' % (m, (hw1 >> 11) & 7, d16, A), kind='bitop')

    # ---- Format IX/X/XI : extended 32-bit ops -------------------------------
    if opc == 0x3F:
        h2 = hw(1)
        # V850E ld.hu shares this slot; hw2 bit0 == 1 discriminates it from the
        # extended ops (whose sub-opcodes are all even).  Confirmed at 0x1DFA6.
        if h2 & 1:
            return Insn(va, 4, 'ld.hu    %d[%s], %s' % (sx(h2 & 0xFFFE, 16), A, B))
        sub = h2 & 0x07FF
        r3 = (h2 >> 11) & 0x1F
        simple = {0x0000: ('setf', 'cond'), 0x0020: ('ldsr', 'sr'), 0x0040: ('stsr', 'sr'),
                  0x0080: ('shr', 'rr'), 0x00A0: ('sar', 'rr'), 0x00C0: ('shl', 'rr')}
        if sub in simple:
            m, k = simple[sub]
            if k == 'cond':
                return Insn(va, 4, '%-8s %s, %s' % (m, COND[r1 & 0xF], B))
            if k == 'sr':
                return (Insn(va, 4, 'ldsr     %s, sr%d' % (B, r1)) if m == 'ldsr'
                        else Insn(va, 4, 'stsr     sr%d, %s' % (r1, B)))
            return Insn(va, 4, '%-8s %s, %s' % (m, A, B))
        # di and ei share sub-opcode 0x0160; hw1 bit15 selects ei.  Decoding
        # every ei as di hides the interrupt-enable that arms the scheduler.
        if sub == 0x0160:
            return Insn(va, 4, 'ei' if (hw1 >> 15) & 1 else 'di')
        fixed = {0x0100: 'trap', 0x0120: 'halt', 0x0140: 'reti'}
        if sub in fixed:
            return Insn(va, 4, fixed[sub], kind='ret' if sub == 0x0140 else None)
        # V850E mul/mulu with a 9-bit immediate split across both halfwords.
        if (sub >> 6) == 0b01001:
            imm9 = sx((((h2 >> 2) & 0xF) << 5) | r1, 9)
            return Insn(va, 4, '%-8s %d, %s, %s'
                        % ('mulu' if (h2 >> 1) & 1 else 'mul', imm9, B, REG[r3]))
        mul = {0x0220: 'mul', 0x0222: 'mulu', 0x0280: 'divh', 0x0282: 'divhu',
               0x02C0: 'div', 0x02C2: 'divu'}
        if sub in mul:
            return Insn(va, 4, '%-8s %s, %s, %s' % (mul[sub], A, B, REG[r3]))
        # Two condition-indexed families at 0x300|cond<<1 and 0x320|cond<<1:
        # the imm5 and reg1 forms of cmov.  Every observed sub-opcode maps to a
        # valid condition code, which is what identifies the family.
        if 0x300 <= sub <= 0x33F and not (sub & 1):
            c = COND[(sub >> 1) & 0xF]
            src = '%d' % sx(r1, 5) if sub < 0x320 else A
            return Insn(va, 4, 'cmov%-4s %s, %s, %s' % (c, src, B, REG[r3]))
        return unk(4)

    return unk()


# -------------------------------------------------------------------------- #

def load():
    return open(BIN, 'rb').read()


def dis(buf, va, count):
    out, off = [], va - BASE
    for _ in range(count):
        i = decode(buf, off, va)
        if i is None:
            break
        out.append(i)
        off += i.size
        va += i.size
    return out


def func(buf, va, limit=4000):
    """Linear sweep until the function clearly ends (jmp [lp] / unconditional
    tail jump backwards out of range), with a hard instruction cap."""
    out, off, seen_end = [], va - BASE, False
    for _ in range(limit):
        i = decode(buf, off, va)
        if i is None:
            break
        out.append(i)
        if i.kind == 'ijmp' and '[lp]' in i.text:
            seen_end = True
            break
        if i.kind == 'ret':
            seen_end = True
            break
        off += i.size
        va += i.size
    return out, seen_end


def selftest(buf):
    print('=== decode-quality sweep ===')
    total = bad = 0
    off = 0
    while off + 2 <= len(buf):
        i = decode(buf, off, BASE + off)
        total += 1
        if not i.ok:
            bad += 1
        off += i.size
    print('  linear sweep from 0x%05X: %d insns, %d unknown (%.2f%%)'
          % (BASE, total, bad, 100.0 * bad / total))

    print('\n=== anchor validation ===')
    anchors = [(0x00004008, 'reset vector'), (0x0000BF80, 'reset entry (doc)'),
               (0x0001D2AA, 'LIN target scaler'), (0x0001D8BC, 'cornering bit0 consumer'),
               (0x0001D8CE, 'cornering bit1 consumer'), (0x00021D98, 'mode lookup'),
               (0x0000F5CE, 'logical output SET'), (0x0000F5E0, 'logical output CLR'),
               (0x000150A6, 'CAN 0x7DF handler')]
    for va, name in anchors:
        print('\n-- 0x%05X  %s' % (va, name))
        for i in dis(buf, va, 6):
            print('   ', i)


def xref(buf, target):
    """Every call/branch in the image whose resolved target == `target`."""
    hits, off = [], 0
    while off + 2 <= len(buf):
        i = decode(buf, off, BASE + off)
        if i.target == target and i.kind in ('call', 'jmp', 'br'):
            hits.append(i)
        off += i.size
    return hits


if __name__ == '__main__':
    b = load()
    a = sys.argv[1:]
    if not a or a[0] == '--selftest':
        selftest(b)
    elif a[0] == '--func':
        insns, ended = func(b, int(a[1], 0))
        for i in insns:
            print(i)
        print('; %d insns, terminated=%s' % (len(insns), ended))
    elif a[0] == '--xref':
        for i in xref(b, int(a[1], 0)):
            print(i)
    else:
        for i in dis(b, int(a[0], 0), int(a[2]) if len(a) > 2 else int(a[1], 0) if len(a) > 1 else 40):
            print(i)
