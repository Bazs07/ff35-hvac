import sys, collections
sys.path.insert(0,'tools')
import v850dis as V
buf=V.load(); BASE=V.BASE
insns=[]; off=0
while off+2<=len(buf):
    i=V.decode(buf,off,BASE+off)
    insns.append(i); off+=i.size
print("insns",len(insns))
calls=collections.Counter()
for i in insns:
    if i.kind=='call' and i.target is not None: calls[i.target]+=1
print("distinct jarl targets:",len(calls))
lo=min(calls); hi=max(calls)
print("range %05X..%05X"%(lo,hi))
# histogram of code density per 0x1000
import collections as C
dens=C.Counter()
for t in calls: dens[t>>12]+=1
for k in sorted(dens): print("  %05X000: %d funcs"%(k,dens[k]))
