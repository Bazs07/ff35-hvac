"""Kimeneti portbit-terkep: az `olvas-modosit-visszair' mintat keresi
   (s)ld.hu 0[ep] -> ori/andi -> (s)st.h 0[ep], plusz set1/clr1 abszolut EA-n."""
import re,collections
movhi=re.compile(r'movhi\s+(-?\d+), (\w+), (\w+)')
mov32=re.compile(r'mov\s+0x([0-9A-F]{8}), (\w+)')
movi =re.compile(r'mov\s+(-?\d+), (\w+)')
addi =re.compile(r'addi\s+(-?\d+), (\w+), (\w+)')
movea=re.compile(r'movea\s+(-?\d+), (\w+), (\w+)')
res=collections.defaultdict(lambda: collections.defaultdict(set))
cur=None; regs={}; win=[]
for line in open('full.asm'):
    m=re.match(r'; ===== FUN_([0-9A-F]+)',line)
    if m: cur=int(m.group(1),16); regs={}; win=[]; continue
    if cur is None or cur<0x12000: continue
    t=line[10:].rstrip(); win.append(t); win[:] = win[-6:]
    mm=movhi.search(t)
    if mm:
        b=0 if mm.group(2)=='r0' else regs.get(mm.group(2))
        regs[mm.group(3)]=None if b is None else (b+((int(mm.group(1))&0xFFFF)<<16))&0xFFFFFFFF; continue
    mm=mov32.search(t)
    if mm: regs[mm.group(2)]=int(mm.group(1),16); continue
    mm=movi.search(t)
    if mm: regs[mm.group(2)]=int(mm.group(1)); continue
    for rx in (addi,movea):
        mm=rx.search(t)
        if mm:
            s=regs.get(mm.group(2)); regs[mm.group(3)]=None if s is None else (s+int(mm.group(1)))&0xFFFFFFFF; break
    # visszairas felismerese
    mo=re.search(r'\b(?:s?st)\.\w+\s+(\w+), (-?\d+)\[(\w+)\]',t)
    if mo:
        base=regs.get(mo.group(3)); 
        if base is None: continue
        ea=(base+int(mo.group(2)))&0xFFFFFFFF
        if (ea>>24)!=0xFF: continue
        reg=mo.group(1)
        for w in reversed(win[:-1]):
            m2=re.search(r'\b(ori|andi)\s+0x([0-9A-F]{4}), %s, %s'%(reg,reg),w)
            if m2:
                v=int(m2.group(2),16)
                bits=v if m2.group(1)=='ori' else (~v)&0xFFFF
                if bin(bits).count('1')<=4:
                    for b in range(16):
                        if bits>>b&1: res[ea][cur].add(b)
                break
    mo=re.search(r'\b(set1|clr1)\s+(\d+), (-?\d+)\[(\w+)\]',t)
    if mo:
        base=regs.get(mo.group(4))
        if base is not None and (base>>24)==0xFF:
            res[(base+int(mo.group(3)))&0xFFFFFFFF][cur].add(int(mo.group(2)))
for ea in sorted(res):
    fs=res[ea]
    print("%08X  bitek=%s"%(ea,sorted(set().union(*fs.values()))))
    for f in sorted(fs): print("      FUN_%05X -> bit %s"%(f,sorted(fs[f])))
