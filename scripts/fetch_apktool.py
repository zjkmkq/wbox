#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载 apktool.jar 到 tools/apktool/。

apktool 是第三方开源工具（Apache-2.0）。本仓库**不附带**其二进制，
以免把来源/许可证不确定的网络素材直接入库。请按需自行下载，
便于你确认来源与许可证后再使用。

用法：
    python scripts/fetch_apktool.py
或从仓库根目录：
    python -m scripts.fetch_apktool
"""
import json
import os
import sys
import urllib.request

REPO = "iBotPeaches/Apktool"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TARGET_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, "tools", "apktool")
)
TARGET = os.path.join(TARGET_DIR, "apktool.jar")


def _pick_jar_asset(rel: dict):
    # 优先取名为 apktool_<tag>.jar 之类；退而求其次取第一个 .jar
    assets = rel.get("assets") or []
    for a in assets:
        name = (a.get("name") or "").lower()
        if name.endswith(".jar") and "source" not in name and "sources" not in name:
            return a
    for a in assets:
        if (a.get("name") or "").lower().endswith(".jar"):
            return a
    return None


def main() -> int:
    os.makedirs(TARGET_DIR, exist_ok=True)
    print(f"查询 apktool 最新发布：{API_URL}")
    try:
        req = urllib.request.Request(API_URL, headers={"User-Agent": "wbox-fetch"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            rel = json.load(resp)
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 无法访问 GitHub API：{e}")
        print(f"请手动从 https://github.com/{REPO}/releases 下载 apktool.jar 到：{TARGET}")
        return 1

    asset = _pick_jar_asset(rel)
    if not asset:
        print(f"[错误] 未找到 jar 资产，请手动从 {rel.get('html_url', API_URL)} 下载 apktool.jar 到：{TARGET}")
        return 1

    url = asset["browser_download_url"]
    print(f"下载 {url}\n  -> {TARGET}")
    try:
        urllib.request.urlretrieve(url, TARGET)
    except Exception as e:  # noqa: BLE001
        print(f"[错误] 下载失败：{e}")
        return 1

    print("完成。apktool.jar 已就绪，可继续打包 exe 或运行解包。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
