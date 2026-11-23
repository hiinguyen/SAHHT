import sys, struct, os
SIG=b'XXTEA'; KEY=b'aaa'
def dec(data,key):
    key=key[:16].ljust(16,b'\0'); k=struct.unpack('<4I',key)
    n=len(data)//4; v=list(struct.unpack('<%dI'%n,data[:n*4]))
    M=0xFFFFFFFF; d=0x9E3779B9; rounds=6+52//n; s=(rounds*d)&M; y=v[0]
    while rounds>0:
        e=(s>>2)&3
        for p in range(n-1,0,-1):
            z=v[p-1]
            v[p]=(v[p]-((((z>>5)^(y<<2))+((y>>3)^(z<<4)))^((s^y)+(k[(p&3)^e]^z))))&M
            y=v[p]
        z=v[n-1]
        v[0]=(v[0]-((((z>>5)^(y<<2))+((y>>3)^(z<<4)))^((s^y)+(k[(0&3)^e]^z))))&M
        y=v[0]; s=(s-d)&M; rounds-=1
    return struct.pack('<%dI'%n,*v)
src,dst=sys.argv[1],sys.argv[2]
ok=bad=plain=0; kinds={}
for r,_,fs in os.walk(src):
    for f in fs:
        p=os.path.join(r,f); rel=os.path.relpath(p,src); o=os.path.join(dst,rel)
        os.makedirs(os.path.dirname(o),exist_ok=True)
        b=open(p,'rb').read()
        if not b.startswith(SIG): open(o,'wb').write(b); plain+=1; continue
        if len(b)-len(SIG)<8: open(o,'wb').write(b); bad+=1; continue
        raw=dec(b[len(SIG):],KEY)
        # PKCS-like trailing length? cocos2d-x quick: no padding; try strip nulls
        raw=raw.rstrip(b'\0')
        kind='luajit' if raw[:3]==b'\x1bLJ' else 'luac' if raw[:4]==b'\x1bLua' else 'text' if all(c<128 for c in raw[:200]) else 'unknown'
        kinds[kind]=kinds.get(kind,0)+1
        open(o,'wb').write(raw); ok+=1
print('decrypted',ok,'plain',plain,kinds)
