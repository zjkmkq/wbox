"""Measure plank band + blade disc/hub in gameplay screenshots."""
from PIL import Image
import sys

def analyze(path):
    im = Image.open(path).convert('RGB')
    w, h = im.size
    px = im.load()
    # plank: beige (r>170, g>150, b in 120..190, r>b+30), mid-lower band only
    rows = {}
    cols = {}
    y0, y1 = int(h*0.35), int(h*0.85)
    min_row = int(w*0.12)
    for y in range(y0, y1, 2):
        cnt = 0
        for x in range(0, w, 2):
            r, g, b = px[x, y]
            if r > 170 and g > 150 and 110 < b < 195 and r > b + 25 and abs(r-g) < 60:
                cnt += 1
                cols.setdefault(x, 0)
                cols[x] += 1
        if cnt > min_row:
            rows[y] = cnt
    if not rows:
        print(path, 'no plank found')
        return
    ys = sorted(rows)
    # largest contiguous band
    band = [ys[0]]
    best = list(band)
    for y in ys[1:]:
        if y - band[-1] <= 6:
            band.append(y)
        else:
            if band[-1] - band[0] > best[-1] - best[0]:
                best = list(band)
            band = [y]
    if band[-1] - band[0] > best[-1] - best[0]:
        best = list(band)
    pt, pb = best[0], best[-1]
    band_cols = [x for x, c in cols.items() if c > (pb-pt)//6]
    pl, pr = min(band_cols), max(band_cols)
    # blade: silver gray (r,g,b close, 140..225), search right 2/3
    silver = []
    dark = []
    for y in range(0, h, 2):
        for x in range(int(w*0.3), w, 2):
            r, g, b = px[x, y]
            if abs(r-g) < 18 and abs(g-b) < 18 and 140 < r < 228:
                silver.append((x, y))
            if r < 70 and g < 70 and b < 70:
                dark.append((x, y))
    if not silver:
        print(path, 'no blade found')
        return
    # blade vertical extent near the densest silver column
    from collections import Counter
    colcnt = Counter(x for x, y in silver)
    # smooth: find column with max count
    hx0 = max(colcnt, key=lambda k: colcnt[k])
    disc_ys = [y for x, y in silver if abs(x - hx0) <= 8]
    # take largest contiguous run
    disc_ys.sort()
    runs = []
    cur = [disc_ys[0]]
    for y in disc_ys[1:]:
        if y - cur[-1] <= 8:
            cur.append(y)
        else:
            runs.append(cur)
            cur = [y]
    runs.append(cur)
    main = max(runs, key=len)
    dt, db = main[0], main[-1]
    # hub: dark pixels within disc x range
    hub = [(x, y) for x, y in dark if abs(x-hx0) < 40 and dt-10 < y < db+10]
    if hub:
        hx = sum(p[0] for p in hub)/len(hub)
        hy = sum(p[1] for p in hub)/len(hub)
    else:
        hx, hy = hx0, (dt+db)/2
    print(f'{path}')
    print(f'  plank: y {pt}..{pb} (h={pb-pt})  x {pl}..{pr}')
    print(f'  blade disc @x={hx0}: y {dt}..{db} (d={db-dt})  hub=({hx:.0f},{hy:.0f})')
    print(f'  hub rel: hub_y-plank_top={hy-pt:.0f}  hub_y-plank_bot={hy-pb:.0f}  '
          f'disc_bot-plank_bot={db-pb:.0f}  plank_end-hub_x={pr-hx:.0f}  '
          f'disc_diam={db-dt}')

for p in sys.argv[1:]:
    analyze(p)
