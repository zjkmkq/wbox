#!/usr/bin/env node
/*
 * browser_probe.js —— 用真实浏览器（Edge/Chromium）验证同一份 H5，独立于 ArkWeb。
 *
 * 为什么必须有它：
 *   ArkWeb 出问题时，光看鸿蒙侧无法判断是「H5 本身就不行」还是「ArkWeb 把它跑坏了」。
 *   同一个 URL 在桌面 Chromium 上跑一遍，就能把这两者分开 —— 这是迁移校验的第一道分水岭。
 *
 * 用法：
 *   node scripts/browser_probe.js <url> [normal|canvas] <out.png> [WxH] [dpr]
 *     normal = 原样跑（WebGL 可用）
 *     canvas = 拦掉 getContext('webgl')，强制引擎回落 Canvas2D（对比用）
 *     WxH    = 视口尺寸，默认 1280x586；dpr = 设备像素比，默认 1
 *              例：810x366 + dpr 3.5 可以精确复现鸿蒙模拟器的运行条件。
 *
 * 会打印：渲染器类型（WEBGL/CANVAS）、canvas 尺寸、当前场景、控制台前 40 条。
 * 依赖：puppeteer-core（只驱动浏览器，不下载 Chromium）。
 */
const puppeteer = require('puppeteer-core');

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

(async () => {
  const url = process.argv[2] || 'http://127.0.0.1:8791/index.html';
  const mode = process.argv[3] || 'normal';
  const out = process.argv[4] || 'D:/harmony/_shots/browser.png';
  const vp = (process.argv[5] || '1280x586').split('x');
  const dpr = Number(process.argv[6] || 1);
  const vw = Number(vp[0]);
  const vh = Number(vp[1]);

  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: true,
    userDataDir: 'D:/harmony/_edgeprof_pw',
    // mode=webgl 时要保留 GPU/SwiftShader 才能拿到 WebGL 上下文；其它模式用软件光栅更稳定
    args: ['--no-sandbox', '--hide-scrollbars', '--mute-audio'].concat(
      mode === 'webgl' ? ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] : ['--disable-gpu']
    )
  });
  const page = await browser.newPage();
  await page.setViewport({ width: vw, height: vh, deviceScaleFactor: dpr });

  const logs = [];
  page.on('console', (m) => logs.push('[console:' + m.type() + '] ' + m.text()));
  page.on('pageerror', (e) => logs.push('[pageerror] ' + e.message));
  page.on('requestfailed', (r) => {
    const f = r.failure();
    logs.push('[reqfail] ' + r.url() + ' ' + (f ? f.errorText : ''));
  });

  if (mode === 'canvas') {
    await page.evaluateOnNewDocument(() => {
      const orig = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (t, a) {
        const s = String(t).toLowerCase();
        if (s.indexOf('webgl') >= 0) {
          return null;
        }
        return orig.call(this, t, a);
      };
    });
  }

  try {
    await page.goto(url, { waitUntil: 'networkidle2', timeout: 60000 });
  } catch (e) {
    logs.push('[goto] ' + e.message);
  }
  await new Promise((r) => setTimeout(r, 12000));

  let info = {};
  try {
    info = await page.evaluate(() => {
      const g = window.game;
      const cs = [];
      document.querySelectorAll('canvas').forEach((c) => {
        const b = c.getBoundingClientRect();
        cs.push(c.width + 'x' + c.height + '@css' + Math.round(b.width) + 'x' + Math.round(b.height));
      });
      let scenes = [];
      try {
        scenes = g.scene.getScenes(true, true).map((s) => s.scene.key);
      } catch (e) {
        /* noop */
      }
      return {
        renderer: g && g.renderer ? (g.renderer.type === 2 ? 'WEBGL' : 'CANVAS') : 'no-game',
        canvases: cs,
        scenes: scenes,
        dpr: window.devicePixelRatio
      };
    });
  } catch (e) {
    info = { error: e.message };
  }

  await page.screenshot({ path: out });
  console.log('MODE=' + mode);
  console.log(JSON.stringify(info, null, 1));
  console.log('--- logs ---');
  console.log(logs.slice(0, 40).join('\n'));
  await browser.close();
})().catch((e) => {
  console.error('FATAL', e);
  process.exit(1);
});
