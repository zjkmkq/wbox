# apktool.jar 放置目录

本目录**不随仓库分发** `apktool.jar`（第三方 Apache-2.0 工具，来源与许可证请自行确认）。

## 获取方式（任选其一）
1. 一键下载（推荐）：在仓库根目录运行
   ```bash
   python scripts/fetch_apktool.py
   ```
   会自动从 https://github.com/iBotPeaches/Apktool/releases 拉取最新 `apktool.jar` 到本目录。

2. 手动下载：访问 https://github.com/iBotPeaches/Apktool/releases ，
   把 `apktool.jar` 放到本目录即可。

> 没有 apktool.jar 时，`wbox.extract` 解包与 PyInstaller 打包都会失败——
> 这是预期行为，先取得 jar 再继续。
