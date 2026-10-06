# 최소 PNG 디코더(8bit RGB/RGBA, non-interlaced) + 픽셀 차이 비율 계산
import sys, zlib, struct
def decode(path):
    d = open(path,'rb').read(); assert d[:8] == b'\x89PNG\r\n\x1a\n'
    pos = 8; idat = b''; w=h=0; ct=0
    while pos < len(d):
        ln, = struct.unpack('>I', d[pos:pos+4]); typ = d[pos+4:pos+8]; body = d[pos+8:pos+8+ln]; pos += 12+ln
        if typ == b'IHDR': w,h,bd,ct = struct.unpack('>IIBB', body[:10]); assert bd == 8
        elif typ == b'IDAT': idat += body
    bpp = {2:3, 6:4, 0:1, 4:2}[ct]; raw = zlib.decompress(idat); stride = w*bpp; out = bytearray(); prev = bytearray(stride); p = 0
    for y in range(h):
        f = raw[p]; line = bytearray(raw[p+1:p+1+stride]); p += 1+stride
        if f == 1:
            for i in range(bpp, stride): line[i] = (line[i] + line[i-bpp]) & 255
        elif f == 2:
            for i in range(stride): line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride): line[i] = (line[i] + ((line[i-bpp] if i>=bpp else 0) + prev[i])//2) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i-bpp] if i>=bpp else 0; b = prev[i]; c = prev[i-bpp] if i>=bpp else 0
                pa, pb, pc = abs(b-c), abs(a-c), abs(a+b-2*c)
                pr = a if (pa<=pb and pa<=pc) else (b if pb<=pc else c)
                line[i] = (line[i] + pr) & 255
        out += line; prev = line
    return w, h, bpp, bytes(out)
def diff(a, b):
    wa,ha,ba,da = decode(a); wb,hb,bb,db = decode(b)
    if (wa,ba) != (wb,bb): return f'SIZE-MISMATCH {wa}x{ha} vs {wb}x{hb}'
    h = min(ha,hb); stride = wa*ba; n = 0; tot = wa*h
    for y in range(h):
        ra = da[y*stride:(y+1)*stride]; rb = db[y*stride:(y+1)*stride]
        if ra == rb: continue
        for x in range(wa):
            if ra[x*ba:x*ba+3] != rb[x*ba:x*ba+3]: n += 1
    return f'{n/tot*100:.3f}% ({n}px) h={ha}/{hb}'
if __name__ == '__main__': print(diff(sys.argv[1], sys.argv[2]))
