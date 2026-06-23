"""Try to identify EFT icon-cache hash: compute candidate hashes of every item id
and count how many land in index.json's keys. High overlap => cracked mapping."""
import os, json, zlib, hashlib

DATA="data"
CACHE=r'C:\Users\basvi\AppData\Local\Temp\Battlestate Games\EscapeFromTarkov\Icon Cache\live'
idx=json.load(open(os.path.join(CACHE,"index.json"),encoding="utf-8"))
keys=set(int(k) for k in idx.keys())
print("index keys:",len(keys),"sample:",list(keys)[:4])

items=json.load(open(os.path.join(DATA,"items.json"),encoding="utf-8"))
ids=[it["id"] for it in items]
print("item ids:",len(ids))

def s32(u): return u-2**32 if u>=2**31 else u

def net_framework_hash(s):
    # classic .NET Framework string GetHashCode (x86), deterministic
    h1=h2=(5381,5381)
    h1=5381; h2=5381
    b=s
    i=0; n=len(b)
    # process pairs of chars
    arr=[ord(c) for c in b]+[0]
    while i+1< n+1 and i< n:
        h1=((h1<<5)+h1+(h1>>27)) & 0xffffffff
        h1=(h1 ^ arr[i]) & 0xffffffff
        if i+1< n:
            h2=((h2<<5)+h2+(h2>>27)) & 0xffffffff
            h2=(h2 ^ arr[i+1]) & 0xffffffff
        i+=2
    return s32((h1+ h2*1566083941)&0xffffffff)

def candidates(s):
    out={}
    out["crc32"]=s32(zlib.crc32(s.encode()))
    out["crc32_u"]=zlib.crc32(s.encode())
    out["crc32_utf16"]=s32(zlib.crc32(s.encode("utf-16-le")))
    out["adler"]=s32(zlib.adler32(s.encode()))
    md=hashlib.md5(s.encode()).digest()
    out["md5_i32"]=s32(int.from_bytes(md[:4],"little"))
    out["md5_i32_be"]=s32(int.from_bytes(md[:4],"big"))
    try: out["net"]=net_framework_hash(s)
    except Exception: pass
    return out

names=["crc32","crc32_u","crc32_utf16","adler","md5_i32","md5_i32_be","net"]
hits={n:0 for n in names}
for i in ids:
    c=candidates(i)
    for n in names:
        if n in c and c[n] in keys: hits[n]+=1
print("\nhash function hits (of %d ids, %d keys):"%(len(ids),len(keys)))
for n in names: print(f"  {n:12s}: {hits[n]}")
