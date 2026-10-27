"""scripts/sim_newdevice.py —— 模拟"新设备缺依赖"场景，验证引导链路。

本机三项依赖全 OK，证明不了缺依赖时的表现。本脚本在进程内打补丁
（不碰真实环境），验证三种场景下 check_all 的输出与修复引导：

  场景 A 全依赖      —— 基线（应全 OK）
  场景 B 缺 Java     —— 应 MISS + fix=install + 180MB 一键安装
  场景 C 缺工具链    —— 应 MISS + fix=install + 2465MB（CLT 大件）
  场景 D 全缺        —— 应全 MISS，首页渲染三条安装引导

用法：python scripts/sim_newdevice.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wbox import deps  # noqa: E402

BROKEN = "C:/__wbox_nonexistent__/java.exe"


def show(title: str) -> None:
    print(f"\n=== {title} ===")
    for st in deps.check_all():
        mark = "OK  " if st.ok else "MISS"
        print(f"  [{mark}] {st.name} —— {st.purpose}")
        if st.ok:
            print(f"         位置: {st.location} ({st.version or st.source if hasattr(st, 'source') else st.version})")
        else:
            fix = st.fix or "无自动修复"
            size = ""
            if st.fix == "install" and st.size_mb:
                size = (f"，约 {st.size_mb:.0f}MB" if st.size_mb < 1024
                        else f"，约 {st.size_mb / 1024:.1f}GB")
            print(f"         修复: {fix}{size}")
            if st.detail:
                print(f"         详情: {st.detail}")


def main() -> int:
    # 场景 A：基线
    show("场景 A：全依赖（本机基线）")

    # 场景 B：缺 Java（patch java_bin 指向不存在路径）
    orig_java = deps.java_bin
    deps.java_bin = lambda cfg=None: BROKEN  # type: ignore[assignment]
    show("场景 B：缺 Java（模拟新设备无 JDK）")

    # 场景 C：缺工具链（resolve_toolchain 返回 None）
    orig_tc = deps.resolve_toolchain
    deps.resolve_toolchain = lambda cfg=None: None  # type: ignore[assignment]
    show("场景 C：缺 Java + 缺 HarmonyOS 工具链")

    # 场景 D：恢复 Java，只缺工具链
    deps.java_bin = orig_java  # type: ignore[assignment]
    show("场景 D：只缺工具链（有 Java 无 SDK）")

    deps.resolve_toolchain = orig_tc  # type: ignore[assignment]
    print("\n环境已恢复，真实检测不受影响。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
