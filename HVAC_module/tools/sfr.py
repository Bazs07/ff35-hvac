import re,collections
cur=None; regs={}; hits=collections.Counter(); who=collections.defaultdict(set)
movhi=re.compile(r'movhi\s+(-?\d+), (\w+), (\w+)')
mov32=re.compile(r'mov\s+0x([0-9A-F]{8}), (\w+)')
movi =re.compile(r'mov\s+(-?\d+), (\w+)')
movea=re.compile(r'movea\s+(-?\d+), (\w+), (\w+)')
addi =re.compile(r'addi\s+(-?\d+), (\w+), (\w+)')
addr =re.compile(r'add\s+(\w+), (\w+)\s*$')
mem  =re.compile(r'\b(ld\.\w+|st\.\w+|set1|clr1|not1|tst1)\s+(?:\w+, )?(-?\d+)\[(\w+)\]')
memb =re.compile(r'\b(sld\.\w+|sst\.\w+)\s+(?:\w+, )?(-?\d+)\[ep\]')
for line in open('full.asm'):
    m=re.match(r'; ===== FUN_([0-9A-F]+)',line)
    if m: cur=int(m.group(1),16); regs={}; continue
    if cur is None or cur<0x12000: continue
    t=line[10:] if len(line)>10 else ''
    mm=movhi.search(t)
    if mm:
        b=0 if mm.group(2)=='r0' else regs.get(mm.group(2))
        regs[mm.group(3)]=None if b is None else (b+((int(mm.group(1))&0xFFFF)<<16))&0xFFFFFFFF
        continue
    mm=mov32.search(t)
    if mm: regs[mm.group(2)]=int(mm.group(1),16); continue
    mm=movi.search(t)
    if mm: regs[mm.group(2)]=int(mm.group(1)); continue
    mm=movea.search(t)
    if mm:
        s=regs.get(mm.group(2)); regs[mm.group(3)]=None if s is None else (s+int(mm.group(1)))&0xFFFFFFFF; continue
    mm=addi.search(t)
    if mm:
        s=regs.get(mm.group(2)); regs[mm.group(3)]=None if s is None else (s+int(mm.group(1)))&0xFFFFFFFF; continue
    mm=addr.match(t.strip())
    if mm:
        a=regs.get(mm.group(1)); b=regs.get(mm.group(2))
        regs[mm.group(2)]=None if (a is None or b is None) else (a+b)&0xFFFFFFFF; continue
    for rx in (mem,memb):
        mm=rx.search(t)
        if mm:
            base='ep' if rx is memb else mm.group(3)
            b=regs.get(base)
            if b is not None and (b>>24)==0xFF:
                ea=(b+int(mm.group(2)))&0xFFFFFFFF
                hits[ea]+=1; who[ea].add(cur)
            break
    else:
        # kill dest regs of unknown ops
        mo=re.match(r'\s*\w+\s+.*?,\s*(\w+)\s*$',t)
        if mo and mo.group(1) in regs: regs.pop(mo.group(1),None)
print("distinct SFR addrs:",len(hits))
for a in sorted(hits):
    print("  %08X  n=%-3d funcs=%s"%(a,hits[a],[hex(f) for f in sorted(who[a])][:5]))
