"""build_draft.py —— 一条命令把 draft 变成可安装的 HAP。

    python scripts/build_draft.py D:/WBoxWork/projects/tsz_1.1.wbox --out D:/harmony/SkipTheStone

做三件事（全部确定性，无 AI）：
    1. assemble：draft 代码 + spec 资源清单 + 骨架模板 → 完整鸿蒙工程
    2. hvigor：编译出 unsigned HAP
    3. 打印 HAP 路径与字节数（成功判定以 BUILD SUCCESSFUL 为准）

之所以要这个脚本：之前每次改一行 ArkTS 都要手抄两屏 Python 再 grep 日志，
出错点全在"抄"上（漏拷 overlay、out_dir 被默认值吞掉）。收敛成一个入口。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 允许直接以脚本方式运行（不用先装包）
SRC = Path(__file__).resolve().parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from wbox.assemble import assemble_project  # noqa: E402
from wbox import hvigor  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("project", help="wbox 工程目录（含 spec.json 与 draft/）")
    ap.add_argument("--out", default="", help="输出工程目录；留空用 spec 里的 out_dir")
    ap.add_argument("--no-build", action="store_true", help="只装配不编译")
    args = ap.parse_args()

    proj = Path(args.project).resolve()
    spec = proj / "spec.json"
    if not spec.exists():
        raise SystemExit(f"找不到 spec.json：{spec}")
    draft = proj / "draft"
    if not draft.is_dir():
        raise SystemExit(f"找不到 draft/：{draft}")

    print(f"[1/2] 装配 {proj.name}")
    res = assemble_project(str(spec), draft_dir=str(draft), out_dir=args.out or None)
    print(f"      ok={res.ok} 代码 {len(res.code_files)} 个 / 资源 {len(res.resource_files)} 项 / 页面 {res.pages}")
    if not res.ok:
        print("装配失败：", res.error)
        return 1

    out_dir = args.out or res.project_dir
    if args.no_build:
        print(f"跳过编译，工程在 {out_dir}")
        return 0

    print(f"[2/2] 编译 {out_dir}")
    build = hvigor.run_build(out_dir)
    print(f"      ok={build.ok} summary={build.summary}")
    if build.hap_path:
        hap = Path(build.hap_path)
        size = hap.stat().st_size if hap.exists() else 0
        print(f"      HAP: {hap} ({size:,} 字节)")
    if not build.ok:
        print("编译失败：", build.error or "")
        print("\n".join(build.log_tail[-8:]))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
