"""Multi-scale template matching: locate game sprites inside screenshots.
Gives exact screen scale (px per world unit) and positions."""
import cv2
import numpy as np
import sys

RAW = 'D:/harmony/CircularSawAuto4/entry/src/main/resources/rawfile/'

def match(screen_path, templates):
    img = cv2.imread(screen_path)
    H, W = img.shape[:2]
    print(f'== {screen_path} ({W}x{H})')
    for name, path, scales in templates:
        tpl0 = cv2.imread(RAW + path, cv2.IMREAD_UNCHANGED)
        if tpl0 is None:
            print(f'  {name}: tpl missing')
            continue
        tpl0 = tpl0[:, :, :3]
        th0, tw0 = tpl0.shape[:2]
        best = None
        for s in scales:
            tw, th = int(tw0*s), int(th0*s)
            if tw < 8 or th < 8 or tw >= W or th >= H:
                continue
            tpl = cv2.resize(tpl0, (tw, th), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
            _, mx, _, loc = cv2.minMaxLoc(res)
            if best is None or mx > best[0]:
                best = (mx, s, loc, tw, th)
        if best is None:
            print(f'  {name}: no match')
            continue
        conf, s, (x, y), tw, th = best
        # world size of template = png px / 150; screen scale k = 150*s px/world
        k = 150 * s
        print(f'  {name}: conf={conf:.3f} scale={s:.4f} -> k={k:.1f}px/world '
              f'rect=({x},{y})-({x+tw},{y+th}) worldWH={tw0/150:.3f}x{th0/150:.3f}')

scales_all = [0.15+0.01*i for i in range(85)]  # 0.15..0.99
match(sys.argv[1], [
    ('body-m1', 'model/1/img/465.png', scales_all),
    ('log-1-4', 'logs/1/4.png', scales_all),
    ('disk-1', 'disks/disk1.png', scales_all),
    ('spindle', 'model/spindle.png', scales_all),
])
