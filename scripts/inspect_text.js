/*
 * inspect_text.js —— 一次性诊断：dump 运行中 Phaser 场景里所有 Text 对象的排版样式。
 * 用来判断文字发糊到底是 fontFamily / fontSize / resolution / stroke 还是 image-rendering 导致。
 */
const puppeteer = require('puppeteer-core');
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

(async () => {
  const url = process.argv[2] || 'http://127.0.0.1:8791/index.html?renderer=canvas';
  const vw = Number(process.argv[3] || 810);
  const vh = Number(process.argv[4] || 366);
  const dpr = Number(process.argv[5] || 3.5);
  const browser = await puppeteer.launch({
    executablePath: EDGE, headless: true, userDataDir: 'D:/harmony/_edgeprof_it',
    args: ['--no-sandbox', '--disable-gpu', '--mute-audio']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: vw, height: vh, deviceScaleFactor: dpr });
  await page.evaluateOnNewDocument(() => {
    const orig = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (t, a) {
      if (String(t).toLowerCase().indexOf('webgl') >= 0) { return null; }
      return orig.call(this, t, a);
    };
  });
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }).catch(() => {});
  await new Promise((r) => setTimeout(r, 14000));
  const out = await page.evaluate(() => {
    const res = { fontsLoaded: [], texts: [], canvases: [] };
    try {
      document.fonts.forEach((f) => res.fontsLoaded.push(f.family + ' ' + f.status));
    } catch (e) { /* noop */ }
    document.querySelectorAll('canvas').forEach((c) => {
      const b = c.getBoundingClientRect();
      res.canvases.push(c.width + 'x' + c.height + ' css' + Math.round(b.width) + 'x' + Math.round(b.height)
        + ' ir=' + getComputedStyle(c).imageRendering);
    });
    try {
      const g = window.game;
      const scenes = g.scene.getScenes(true, true);
      scenes.forEach((sc) => {
        sc.children.list.forEach((o) => {
          if (o.type === 'Text' && res.texts.length < 12) {
            const s = o.style;
            res.texts.push({
              text: String(o.text).slice(0, 24),
              family: s.fontFamily, size: s.fontSize, style: s.fontStyle,
              res: s.resolution, stroke: s.strokeThickness, strokeColor: s.stroke,
              shadow: s.shadow ? (s.shadow.blur + '/' + s.shadow.color) : 'none',
              scale: o.scaleX + 'x' + o.scaleY,
              texW: o.width, texH: o.height, dispW: Math.round(o.displayWidth)
            });
          }
        });
      });
    } catch (e) { res.err = e.message; }
    return res;
  });
  console.log(JSON.stringify(out, null, 1));
  await browser.close();
})().catch((e) => { console.error('FATAL', e.message); process.exit(1); });
