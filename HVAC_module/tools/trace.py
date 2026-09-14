"""gp-relativ valtozo visszakovetese: st.b rX,-N[gp] <- ld.bu -M[gp] lancok."""
import re,sys
buf=[l.rstrip() for l in open('full.asm')]
def writers(off):
    res=[];cur=None
    for i,l in enumerate(buf):
        m=re.match(r'; ===== FUN_([0-9A-F]+)',l)
        if m: cur=m.group(1)
        if re.search(r'st\.\w+\s+\w+, %d\[(gp|ep)\]'%off,l):
            prev=buf[i-1].strip()
            mm=re.search(r'ld\.\w+\s+(-?\d+)\[gp\], ',prev)
            res.append((cur,l[:8],int(mm.group(1)) if mm else None,prev))
    return res
seen=set(); q=[(int(sys.argv[1]),0)]
while q:
    off,d=q.pop(0)
    if off in seen or d>6: continue
    seen.add(off)
    ws=writers(off)
    print("%sgp%d (0x%08X):"%('  '*d,off,0xFEE04000+off))
    for f,a,src,prev in ws:
        print("%s   FUN_%s @%s  <- %s"%('  '*d,f,a,prev))
        if src is not None and src not in seen: q.append((src,d+1))
