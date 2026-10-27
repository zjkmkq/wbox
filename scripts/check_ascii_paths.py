"""check_ascii_paths.py —— 中文目录铁律自动检查（2026-10-25 增补）。

背景：DevEco Studio / hvigor 无法识别中文目录（用户实测确认）。WBox 生成的
一切路径组件必须 ASCII。本脚本把这条铁律变成可执行断言：

  1. 单元层：ascii_name 样本转换 + 确定性（同入同出）
  2. 模板层：templates/harmony/ 全部路径 ASCII
  3. 工程层：给定工程（默认圆锯工程）的 work/draft/exports 无非 ASCII 组件
  4. 装配层：真跑一次 assemble 到临时 ASCII 目录，扫描产物树——
     路径组件全 ASCII、main_pages.json 可解析且含主页、
     EntryAbility.loadContent 与主页面一致
  5. 存量兼容：旧中文解包目录仍能被 _resolve_work_dir 定位（构造副本验证）

用法：
    python scripts/check_ascii_paths.py [工程目录]
退出码 0 = 全部通过；1 = 有违例（逐条打印）。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wbox.assemble import TEMPLATE_DIR, assemble_project, _resolve_work_dir  # noqa: E402
from wbox.ascii_names import ascii_initials, ascii_name, is_ascii_path, non_ascii_parts, work_dir_name  # noqa: E402

DEFAULT_PROJECT = Path("D:/Game/GC/92934圆锯模拟器8.wbox")

# 模板必备文件（来自 D:/harmony/CircularSaw 可编译工程的非产物全集）。
# 2026-10-25 教训：find 输出被 head 截断，漏掉 entry/build-profile.json5 与
# entry/hvigorfile.ts，装配出的工程直接 00304056。清单化，防再漏。
REQUIRED_TEMPLATE_FILES = [
    "build-profile.json5", "hvigorfile.ts", "hvigor/hvigor-config.json5",
    "oh-package.json5", "oh-package-lock.json5",
    "AppScope/app.json5",
    "AppScope/resources/base/element/string.json",
    "AppScope/resources/base/media/app_icon.png",
    "entry/build-profile.json5", "entry/hvigorfile.ts", "entry/oh-package.json5",
    "entry/src/main/module.json5",
    "entry/src/main/ets/entryability/EntryAbility.ets",
    "entry/src/main/resources/base/element/color.json",
    "entry/src/main/resources/base/element/string.json",
    "entry/src/main/resources/base/media/app_icon.png",
    "entry/src/main/resources/base/profile/router_map.json",
]

SAMPLE_CASES = [
    ("92934圆锯模拟器8", "92934yuanjumoniqi8"),
    ("218834灾难模拟器去广告2", "218834zainanmoniqiquguanggao2"),
    ("跳石子_1.1", "tiaoshizi_1.1"),
    ("白盒工作台", "bahegongzuotai"),
    ("我的世界", "wodeshijie"),
    ("test_中文目录", "test_zhongwenmulu"),
]

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(f"{'✓' if ok else '✗'} {name}" + (f" —— {detail}" if detail else ""))


def rel_bad(path: Path, base: Path) -> list[str]:
    """path 相对于 base 的非 ASCII 组件。

    铁律对象是 WBox 自己生成的路径组件，不是用户选的上级目录——
    工程目录叫 "92934圆锯模拟器8.wbox" 是存量事实，检查它没意义，
    要查的是它下面 work/draft/exports/harmony 这些 WBox 造的名字。
    """
    try:
        rel = path.resolve().relative_to(base.resolve())
    except ValueError:
        return non_ascii_parts(path)
    return [p for p in rel.parts if p and not p.isascii()]


def main() -> int:
    # 1. 单元层
    for src, expect in SAMPLE_CASES:
        got = ascii_name(src)
        check(f"ascii_name({src!r})", got == expect, f"得到 {got!r}，期望 {expect!r}")
    check("ascii_name 确定性", ascii_name("圆锯模拟器") == ascii_name("圆锯模拟器"))
    check("ascii_name 幂等（ASCII 原样）", ascii_name("CircularSaw") == "CircularSaw")
    # work_dir_name = 拼音首字母（2026-10-25 用户钦定），输入应已去扩展名
    check("work_dir_name（首字母）", work_dir_name("92934圆锯模拟器8") == "92934yjmnq8")
    check("ascii_initials（白盒工作台）", ascii_initials("白盒工作台") == "bhgzt")
    check("ascii_initials 保留点号", ascii_initials("跳石子_1.1") == "tsz_1.1")

    # 2. 模板层（相对模板根：绝对路径里的仓库目录名是开发机事实，不归铁律管）
    bad_tpl = [str(p.relative_to(TEMPLATE_DIR)) for p in TEMPLATE_DIR.rglob("*")
               if rel_bad(p, TEMPLATE_DIR)]
    check("模板树路径全 ASCII", not bad_tpl, f"{len(list(TEMPLATE_DIR.rglob('*')))} 项" + (f"；违例 {bad_tpl[:3]}" if bad_tpl else ""))
    missing_tpl = [f for f in REQUIRED_TEMPLATE_FILES if not (TEMPLATE_DIR / f).is_file()]
    check("模板必备文件无缺失", not missing_tpl, f"缺 {missing_tpl}" if missing_tpl else f"{len(REQUIRED_TEMPLATE_FILES)} 项齐全")

    # 3. 工程层（给定工程存在才查；相对工程根，用户选的上级目录名不追究）
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PROJECT
    if project.is_dir():
        for sub in ("work", "draft", "exports"):
            base = project / sub
            if base.is_dir():
                bad = [str(p.relative_to(project)) for p in base.rglob("*")
                       if rel_bad(p, project)]
                check(f"{sub}/ 无非 ASCII 路径组件", not bad, f"违例 {bad[:3]}" if bad else "")
        spec_path = project / "spec.json"
        if spec_path.is_file():
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            wd = _resolve_work_dir(spec_path, spec)
            check("_resolve_work_dir 定位到 ASCII 解包目录",
                  wd.is_dir() and not rel_bad(wd, project), str(wd.name))
            # 4. 装配层（临时 ASCII 目录）
            with tempfile.TemporaryDirectory(prefix="wbox-ascii-check-") as td:
                out = Path(td) / "Out"
                r = assemble_project(spec_path, out_dir=out)
                if not r.ok:
                    check("assemble 成功", False, r.error)
                else:
                    check("assemble 成功", True, f"{len(r.code_files)} 代码 / {len(r.resource_files)} 资源")
                    # 落点断言：显式 out_dir 必须被尊重（曾经被默认逻辑吞掉，
                    # 产物静默写进 D:/Game/GC/harmony/，检查还全绿）
                    check("assemble 尊重显式 out_dir",
                          Path(r.project_dir).resolve() == out.resolve(),
                          f"{r.project_dir} != {out}")
                    check("装配产物路径全 ASCII", is_ascii_path(r.project_dir),
                          f"违例 {non_ascii_parts(r.project_dir)[:3]}" if non_ascii_parts(r.project_dir) else "")
                    bad_tree = [str(p) for p in Path(r.project_dir).rglob("*") if non_ascii_parts(p)]
                    check("装配树内无中文路径组件", not bad_tree, f"违例 {bad_tree[:3]}" if bad_tree else "")
                    mp = Path(r.project_dir) / "entry/src/main/resources/base/profile/main_pages.json"
                    try:
                        pages = json.loads(mp.read_text(encoding="utf-8"))["src"]
                        check("main_pages.json 可解析且非空", bool(pages), f"{pages}")
                        check("主页面在登记列表", r.main_page in pages, r.main_page)
                    except Exception as e:  # noqa: BLE001
                        check("main_pages.json 可解析", False, str(e))
                    ea = Path(r.project_dir) / "entry/src/main/ets/entryability/EntryAbility.ets"
                    ea_text = ea.read_text(encoding="utf-8")
                    check("EntryAbility.loadContent 与主页面一致",
                          f"loadContent('{r.main_page}'" in ea_text, r.main_page)
    else:
        # 工程被移走/删除不是违例：明确提示并给出用法
        check(f"工程层（{project.name}）", True,
              "工程目录不存在，跳过工程层检查（可用命令行参数指定工程路径）")

    # 5. 存量兼容：旧中文解包目录副本仍可定位
    with tempfile.TemporaryDirectory(prefix="wbox-legacy-") as td:
        legacy = Path(td) / "proj"
        (legacy / "work" / "92934圆锯模拟器8").mkdir(parents=True)
        (legacy / "work" / "92934圆锯模拟器8" / "AndroidManifest.xml").write_text(
            '<manifest package="com.dim.circularsaw"></manifest>', encoding="utf-8")
        wd = _resolve_work_dir(legacy / "spec.json", {"project": {"source": "92934圆锯模拟器8"}})
        check("存量中文解包目录兼容定位", wd.is_dir(), str(wd))

    # 报告
    print(f"\n===== ASCII 路径铁律检查：{len(passes)} 通过 / {len(failures)} 违例 =====")
    for line in passes:
        print(" ", line)
    for line in failures:
        print(" ", line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
