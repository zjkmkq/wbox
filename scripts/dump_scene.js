#!/usr/bin/env node
/* dump_scene.js —— 在 Chromium 里 dump 游戏的运行时结构，定位 tint 补偿的挂载点。 */
const puppeteer = require('puppeteer-core');
const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';

const URL = process.argv[2] || 'http://127.0.0.1:8799/index.html';
const MODE = process.argv[3] || 'canvas';   // canvas | webgl
const WAIT = Number(process.argv[4] || 9000);

(async () => {
  const browser = await puppeteer.launch({
    executablePath: EDGE,
    headless: true,
    userDataDir: 'D:/harmony/_edgeprof_dump',
    args: ['--no-sandbox', '--hide-scrollbars', '--mute-audio', '--window-size=810,366']
      .concat(MODE === 'webgl' ? ['--use-gl=swiftshader', '--enable-unsafe-swiftshader'] : ['--disable-gpu'])
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 810, height: 366, deviceScaleFactor: 1 });

  if (MODE === 'canvas') {
    await page.evaluateOnNewDocument(() => {
      const orig = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (t, a) {
        const s = String(t).toLowerCase();
        if (s === 'webgl' || s === 'webgl2' || s === 'experimental-webgl') return null;
        return orig.call(this, t, a);
      };
    });
  }

  const logs = [];
  page.on('console', m => { const t = m.text(); if (t.startsWith('[WBOX]')) logs.push(t.slice(0, 400)); });
  page.on('pageerror', e => logs.push('ERR ' + String(e).slice(0, 300)));

  await page.goto(URL, { waitUntil: 'load', timeout: 40000 });
  await new Promise(r => setTimeout(r, WAIT));

  const info = await page.evaluate(() => {
    const g = window.game;
    const out = { hasGame: !!g };
    if (!g) return out;

    out.renderer = {
      ctor: g.renderer && g.renderer.constructor && g.renderer.constructor.name,
      type: g.renderer && g.renderer.type,
      keys: Object.keys(g.renderer).slice(0, 40),
      protoMethods: g.renderer ? Object.getOwnPropertyNames(Object.getPrototypeOf(g.renderer)) : []
    };

    out.sceneKeys = g.scene.scenes.map(s => s.scene.key + '|active=' + s.scene.isActive());

    // 遍历当前活动场景的显示列表，统计 tint
    const stat = { total: 0, tinted: 0, whiteFixed: 0, samples: [], texKeys: {} };
    const WHITE = 0xffffff;
    function walk(list, depth) {
      if (!list || depth > 6) return;
      const arr = list.list || list.children || (Array.isArray(list) ? list : null);
      if (!arr) return;
      for (const o of arr) {
        if (!o) continue;
        stat.total++;
        const t = o.tintTop !== undefined ? o.tintTop : o.tint;
        if (typeof t === 'number' && t !== WHITE && t !== -1) {
          stat.tinted++;
          const tk = o.texture && o.texture.key;
          stat.texKeys[tk] = (stat.texKeys[tk] || 0) + 1;
          if (stat.samples.length < 14) {
            stat.samples.push({
              type: o.type, key: tk,
              tint: '0x' + (t >>> 0).toString(16),
              cls: o.constructor && o.constructor.name,
              setTint: typeof o.setTint,
              hasTexture: !!o.texture
            });
          }
        }
        if (o.list || o.children) walk(o, depth + 1);
      }
    }
    for (const s of g.scene.scenes) {
      if (s.children && s.children.list) walk(s.children, 0);
    }
    out.stat = stat;
    out.textureKeys = Object.keys(g.textures.list || {}).slice(0, 30);
    return out;
  });

  console.log(JSON.stringify(info, null, 2));
  if (logs.length) { console.log('--- 探针日志 ---'); console.log(logs.slice(0, 20).join('\n')); }
  await browser.close();
})().catch(e => { console.error('FATAL', e); process.exit(1); });
