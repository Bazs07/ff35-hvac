import sys, collections, json
sys.path.insert(0,'tools')
import v850dis as V
buf=V.load(); BASE=V.BASE
insns=[]; off=0
while off+2<=len(buf):
    i=V.decode(buf,off,BASE+off); insns.append(i); off+=i.size
byva={i.va:i for i in insns}
calls=collections.Counter()
xref=collections.defaultdict(list)
for i in insns:
    if i.kind in ('call',) and i.target is not None:
        calls[i.target]+=1; xref[i.target].append(i.va)
funcs=sorted(t for t in calls if 0x8000<=t<0x78000)
json.dump({'funcs':funcs,'xref':{hex(k):[hex(x) for x in v] for k,v in xref.items() if 0x8000<=k<0x78000}},open('tools/funcs.json','w'))
print("funcs in image:",len(funcs), "first %05X last %05X"%(funcs[0],funcs[-1]))
with open('full.asm','w') as f:
    for i in insns:
        if i.va in calls: f.write('\n; ===== FUN_%05X  (xrefs=%d) =====\n'%(i.va,calls[i.va]))
        f.write(str(i)+'\n')
print("wrote full.asm")
