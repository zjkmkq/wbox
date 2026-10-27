"""Minimal PNG alpha bounding-box decoder (no PIL): zlib + unfilter."""
import struct, zlib, sys

def decode_png(path):
    data = open(path, 'rb').read()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    pos = 8
    idat = b''
    ihdr = None
    plte = None
    trns = None
    while pos < len(data):
        ln, typ = struct.unpack('>I4s', data[pos:pos+8])
        chunk = data[pos+8:pos+8+ln]
        if typ == b'IHDR':
            ihdr = struct.unpack('>IIBBBBB', chunk[:13])
        elif typ == b'IDAT':
            idat += chunk
        elif typ == b'PLTE':
            plte = chunk
        elif typ == b'tRNS':
            trns = chunk
        pos += 12 + ln
    w, h, bitd, ctype, comp, filt, inter = ihdr
    assert bitd == 8 and inter == 0, f'unsupported {ihdr}'
    ch = {0:1, 2:3, 3:1, 4:2, 6:4}[ctype]
    raw = zlib.decompress(idat)
    stride = w * ch
    out = bytearray(h * stride)
    prev = bytearray(stride)
    p = 0
    for y in range(h):
        f = raw[p]; p += 1
        line = bytearray(raw[p:p+stride]); p += stride
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i-ch]) & 0xff
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xff
        elif f == 3:
            for i in range(stride):
                a = line[i-ch] if i >= ch else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xff
        elif f == 4:
            for i in range(stride):
                a = line[i-ch] if i >= ch else 0
                b = prev[i]
                c = prev[i-ch] if i >= ch else 0
                pa, pb, pc = abs(b-c), abs(a-c), abs(a+b-2*c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xff
        out[y*stride:(y+1)*stride] = line
        prev = line
    # alpha bbox
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(h):
        row = out[y*stride:(y+1)*stride]
        if ctype == 6:
            for x in range(w):
                if row[x*4+3] > 8:
                    if x < minx: minx = x
                    if x > maxx: maxx = x
                    if maxy < y: maxy = y
                    if miny == h: miny = y
            if miny == h and maxx >= 0: miny = y
        elif ctype == 4:
            for x in range(w):
                if row[x*2+1] > 8:
                    if x < minx: minx = x
                    if x > maxx: maxx = x
                    if maxy < y: maxy = y
                    if miny == h: miny = y
            if miny == h and maxx >= 0: miny = y
        elif ctype == 3:
            t = trns if trns else b''
            for x in range(w):
                idx = row[x]
                a = t[idx] if idx < len(t) else 255
                if a > 8:
                    if x < minx: minx = x
                    if x > maxx: maxx = x
                    if maxy < y: maxy = y
                    if miny == h: miny = y
            if miny == h and maxx >= 0: miny = y
        else:
            minx, miny, maxx, maxy = 0, 0, w-1, h-1
            break
    if maxx < 0:
        return (w, h, None)
    return (w, h, (minx, miny, maxx, maxy))

for path in sys.argv[1:]:
    w, h, bb = decode_png(path)
    if bb is None:
        print(f'{path}: {w}x{h} EMPTY')
    else:
        minx, miny, maxx, maxy = bb
        vw, vh = maxx-minx+1, maxy-miny+1
        print(f'{path}: {w}x{h} bbox=({minx},{miny})-({maxx},{maxy}) visible={vw}x{vh} '
              f'pad L={minx} R={w-1-maxx} T={miny} B={h-1-maxy}')
