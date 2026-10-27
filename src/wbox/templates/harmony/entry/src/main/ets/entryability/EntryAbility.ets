// 入口 Ability：原版 com.dim.circularsaw.AndroidLauncher 的鸿蒙侧对应。
// 原版 Application（w0/g.b 读档键全部迁入 W0G，不在本类初始化）与
// 广告/Firebase（t1/f4 包）按方法论 §3 单机化不迁移（dec_001/002）。

import { AbilityConstant, UIAbility, Want } from '@kit.AbilityKit';
import { hilog } from '@kit.PerformanceAnalysisKit';
import { window } from '@kit.ArkUI';

const DOMAIN: number = 0x0000;
const TAG: string = 'EntryAbility';

export default class EntryAbility extends UIAbility {
  onCreate(want: Want, launchParam: AbilityConstant.LaunchParam): void {
    // 原版 onCreate 的广告/统计初始化不迁移；游戏读档在 W0G.attachWorld 内触发
  }

  onWindowStageCreate(windowStage: window.WindowStage): void {
    const mainWindow = windowStage.getMainWindowSync();
    // 全屏（沉浸式）+ 常亮：原版 FLAG_KEEP_SCREEN_ON + 沉浸式
    mainWindow.setWindowLayoutFullScreen(true).catch((err: Error) => {});
    mainWindow.setWindowKeepScreenOn(true).catch((err: Error) => {});
    // 横屏锁定：原版 AndroidManifest screenOrientation="landscape"（dec_002）。
    // 2026-10-25 用户实测：不锁方向默认竖屏，游戏视野 12.8×7.2 直接错位。
    // API 真身（本机 SDK 26）：setPreferredOrientation(Orientation): Promise<void>
    mainWindow.setPreferredOrientation(window.Orientation.LANDSCAPE)
      .catch((err: Error) => {
        hilog.warn(DOMAIN, TAG, 'setPreferredOrientation failed');
      });

    // 主页面即原版 AndroidLauncher（libGDX AndroidApplication 的鸿蒙等价物）
    windowStage.loadContent('{{MAIN_PAGE}}', (err) => {
      if (err) {
        hilog.error(DOMAIN, TAG, 'loadContent failed: %{public}s', JSON.stringify(err));
      }
    });
  }
}
