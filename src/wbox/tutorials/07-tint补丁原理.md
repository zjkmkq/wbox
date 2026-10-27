---
title: 无 WebGL 时的渲染补偿（tint bake）
summary: 为什么强制 Canvas 是错的、为什么字会全白、以及怎么在不改游戏一个字节的前提下把颜色完整还原。
tags: [渲染, canvas, webgl, tint, phaser, 深度]
steps: [assemble, seal]
order: 7
---

# 无 WebGL 时的渲染补偿

## 现象

H5 游戏装到鸿蒙上，**所有文字变成白色，标题糊成一片**，但形状、布局、音乐全部正常。

## 错误的第一反应（我当时就犯了）

"Canvas 画出来是花屏 → 强制引擎回落 Canvas2D 就稳了。"

**这是错的，而且会让问题从"花"变成"全白"。**

## 真正的原因

Phaser/Pixi 这类引擎的常见做法是：

1. 用 `fillStyle = '#ffffff'` 生成一张**白色字模图**（atlas）
2. 每个对象 `setTint(0x3A3328)` 之类把颜色"乘"上去

Phaser 4 的 **Canvas 渲染器完全不处理 tint**（源码里 `tintFill` 出现 0 次，`globalCompositeOperation` 只服务 blendMode）。

于是：白色字模 × 被忽略的 tint = **永远白色**。

鸿蒙 x86_64 模拟器的 ArkWeb **拿不到 WebGL 上下文**（`webgl2:null || webgl:null || experimental-webgl:null`），所以 `type: AUTO` 只能回落 Canvas，问题必然出现。

## 判断方法（30 秒）

```
node scripts/browser_probe.js "http://127.0.0.1:8799/index.html?renderer=webgl" webgl a.png 810x366 1
node scripts/browser_probe.js "http://127.0.0.1:8799/index.html" canvas b.png 810x366 1
```

两张图对比：
- WebGL 颜色正确、Canvas 全白 → 确认是 tint 问题
- 两张都一样错 → 问题在 H5 本身，不在渲染器

## 解法：tint bake

**思路**：既然渲染器不认 tint，就在渲染前把「纹理 × tint」**预先烘成一张新纹理**，让对象直接用烘好的纹理。

### 挂载点

`window.game` 是 Phaser.Game 实例，可直接访问：

```javascript
game.renderer.type   // 1 = CANVAS, 2 = WEBGL
game.scene.scenes    // 所有场景
game.textures        // 纹理管理
```

**只在 `type === 1` 时激活**。有 WebGL 就一行都不干预。

### 烘焙

```
drawImage(原帧) → getImageData → 逐像素 r*tr/255 → putImageData
→ game.textures.addCanvas(key, canvas)
```

用的是**乘法**（`r * tr / 255`），和 Phaser 的 tint 语义一致。不能用 `globalCompositeOperation='multiply'`——它会把透明区域变成不透明黑块。

缓存 key：`__wboxb_<原key>|<帧名>|<tint hex>`。

### 应用到对象

```
setTexture(烘好的 key) + clearTint()
对象上记 __wboxBakedTint = 原 tint
```

**每 500ms 扫一遍场景**，因为游戏会按昼夜重新给对象上色。

## 三个只有实测才知道的坑

### 坑 1：`tintTop` 是 undefined

Phaser 4 里 `o.tintTop` 取不到值，真正的 tint 在 **`o.tint`**。

按 `tintTop` 判空会**静默失效**（tintHit = 0，什么都不烘，也不报错）。

### 坑 2：文字是 BitmapText，不是 Image

对 `BitmapText` 调 `setTexture` **完全无效** —— 它按 `fontData.chars` 自己逐字画。

正确做法：
1. 把整套字体 atlas 烘一遍（复制全部帧）
2. `cache.bitmapFont.add(新字体名, {data, texture, frame, fromAtlas})`
3. `bitmapText.setFont(新字体名)`

不做这步，标题还是白的。

### 坑 3：别等 `game.isBooted`

设备上 `isBooted` 要 **8.5 秒**才为真。但 `renderer` 在 `new Game()` 就绪了。

等 isBooted = 前 8 秒画面是白的。改成只等 `window.game`（约 400ms）就激活。

## 验收标准

- 与 Chromium WebGL 截图**逐像素对比**，差异 > 40 的像素应 < 1%
- 设备端纯白像素数量应该从"满屏"降到个位数（只剩高光）

跳石子工程实测：整屏差异 0.77%（标题区 0.26%、按钮区 0.05%，中部差异是会动的浮尘水波），设备端纯白像素只剩 42 个。

## 什么时候不要用

- 设备**有** WebGL → 让它走原生路径，不要干预
- 游戏不用 tint（颜色直接写在 fillStyle 里）→ 不需要
- 逐帧连续微调 tint 的游戏 → bake 会不断重烘，需要把 tint 量化到 5bit 再当缓存 key

## 代价

首次扫描（约 45 张纹理 + 6 套字体）在模拟器上耗时 **1.8 秒**。必须发生在原生加载页期间，用户看不到。**不要挪到游戏跑起来之后**，那会是一次可见卡顿。
