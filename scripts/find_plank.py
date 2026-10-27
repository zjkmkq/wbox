"""Match candidate plank images within the plank region of the reference screenshot."""
import cv2
import numpy as np

RAW = 'D:/harmony/CircularSawAuto4/entry/src/main/resources/rawfile/'
img = cv2.imread('C:/Users/Administrator/.workbuddy/clipboard-images/clipboard-2026-10-25T11-00-18-667Z-e2f9dc95.jpg')
# plank region of interest (generous): x 200..1500, y 400..700
roi = img[380:720, 200:1500]

cands = ['logs/1/1.png', 'logs/1/2.png', 'logs/1/3.png', 'logs/1/4.png',
         'logs/2/4.png', 'logs/4/4.png', 'logs/2/full.png']
for path in cands:
    tpl0 = cv2.imread(RAW + path, cv2.IMREAD_UNCHANGED)
    if tpl0 is None:
        print(path, 'missing')
        continue
    tpl0 = tpl0[:, :, :3]
    th0, tw0 = tpl0.shape[:2]
    best = None
    for s in [0.60+0.01*i for i in range(31)]:
        tw, th = int(tw0*s), int(th0*s)
        if tw >= roi.shape[1] or th >= roi.shape[0]:
            continue
        tpl = cv2.resize(tpl0, (tw, th), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(roi, tpl, cv2.TM_CCOEFF_NORMED)
        _, mx, _, loc = cv2.minMaxLoc(res)
        if best is None or mx > best[0]:
            best = (mx, s, loc, tw, th)
    conf, s, (x, y), tw, th = best
    print(f'{path}: conf={conf:.3f} scale={s:.2f} rect=({x+200},{y+380})-({x+200+tw},{y+380+th})')
