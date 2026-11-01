# 构建与发布

## 工具链

| 工具 | 版本 | 用途 |
| --- | --- | --- |
| Python | 3.12 x64（发布）；≥ 3.10 可开发 | 后端、测试、PyInstaller（`requirements/build.txt`） |
| Node.js / npm | 22 LTS（CI）；≥ 20 | Vite、Svelte、Tauri CLI |
| Rust | stable + `rustfmt`，Windows 用 MSVC 工具链 | Tauri 壳 |
| Visual Studio Build Tools + Windows SDK | 最新 | `link.exe` 等 |
| WebView2 Runtime | Evergreen | 运行与冒烟 |
| NSIS | Tauri 自动下载 | 安装器 |

锁文件：`package-lock.json`、`frontend/package-lock.json`、`src-tauri/Cargo.lock`、`requirements/build.txt`。
`scripts/check_version.py` 要求 `package.json`、`frontend/package.json`、两个 lock、`src-tauri/tauri.conf.json`、
`Cargo.toml`、`Cargo.lock`、`rka_desktop.__version__`、CHANGELOG 顶部版本完全一致。

## 本地构建（Windows PowerShell）

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements/build.txt -e ".[dev]"
npm ci
npm --prefix frontend ci
python scripts/check_version.py
python -m pytest -q
python -m ruff check .
npm --prefix frontend run check
npm --prefix frontend run test
npm --prefix frontend run build
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
python scripts/build_backend.py                                   # 冻结 rka3000-backend.exe + 许可
python scripts/smoke_backend.py src-tauri/binaries/rka3000-backend-x86_64-pc-windows-msvc.exe
python scripts/collect_notices.py                                 # Rust / 前端许可
npm run tauri build -- --ci --config src-tauri/tauri.release.conf.json -- --locked
python scripts/stage_release.py                                   # 便携目录、ZIP、安装器、SHA256SUMS
$exe = Get-ChildItem build/portable -Recurse -Filter rka3000-desktop.exe
./scripts/smoke_desktop.ps1 -Executable $exe.FullName
./scripts/smoke_installer.ps1                                     # 会在当前用户安装/卸载，建议仅在测试机执行
```

输出在 `dist/release/`：`RKA3000-desktop_<版本>_windows-x64_setup.exe`、`…_portable.zip`、`SHA256SUMS.txt`。
`stage_release.py` 要求 `build/portable/` 与 `dist/release/` 不存在，避免混入旧资产。

开发配置 `src-tauri/tauri.conf.json` 不打包（`bundle.active=false`），`npm run tauri dev` 直接运行仓库 `.venv` 中的 Python；
发布配置 `tauri.release.conf.json` 启用 NSIS 并通过 `externalBin` 嵌入 sidecar，安装器在缺少 WebView2 时联网下载安装
（`downloadBootstrapper`），便携包需预装 WebView2。

macOS/Linux 可执行 Python 测试、前端检查、`cargo check`，但不能生成 Windows 资产；本机缺工具链时在 GitHub `Checks`
工作流手动运行并下载 artifact。

## CI/CD

- **Checks**（`.github/workflows/checks.yml`）：PR、`main` 推送、手动、被 Release 调用。`python-linux` 任务做快速 Python 反馈；
  `windows-build` 任务执行上节全部步骤并上传 `rka3000-desktop-windows-x64` artifact（保留 14 天），失败时上传诊断包。
  权限仅 `contents: read`。
- **Release**（`.github/workflows/release.yml`）：推送 `v*` 标签触发，复用 Checks；`publish` 任务下载 artifact、
  `sha256sum --check`、从 CHANGELOG 提取说明、`gh release create --verify-tag`。仅该任务拥有 `contents: write`。
  标签含 `-`（如 `v0.9.0-rc.1`）标记 prerelease 且不设为 Latest；正式标签设为 Latest。
- 已发布的标签与资产不覆盖、不移动；修复后用新版本号重新发布。工作流不合并 PR，也不实现自动更新。

## 版本与标签

```bash
python scripts/release.py bump 0.9.0     # 更新所有清单 + 把 CHANGELOG Unreleased 提升为 0.9.0
python scripts/check_version.py
git commit -am "release: 0.9.0"
git tag -a v0.9.0 -m "RKA-3000 desktop v0.9.0"
git push origin v0.9.0
```

`release.py bump` 修改 `__init__.py`、`package.json`、`frontend/package.json`、两个 `package-lock.json`、
`tauri.conf.json`、`Cargo.toml`、`Cargo.lock`；之后运行 `npm install --package-lock-only` 可确认 lock 一致。

## 资产验收

1. Release 页面应有 3 个资产；`SHA256SUMS.txt` 与下载文件核对一致。
2. 在干净的 Windows 10/11 x64 上：安装器静默安装（`/S`）后启动，窗口显示“本地服务在线 · 仿真”，关闭后任务管理器无
   `rka3000-backend.exe` 残留；卸载后 `%LOCALAPPDATA%\RKA3000\` 仍保留。
3. 便携包完整解压运行，与安装版共用用户数据目录。
4. 现场设备验收（真实串口、TAIE 程序段单位、MFC 量程）不在 CI 覆盖范围，必须另行执行。

## 失败处理

- Checks 失败：查看任务日志与 `rka3000-windows-failure` artifact（含便携目录、冻结后端、日志）。
- 冻结后端冒烟失败：本地用 `python scripts/smoke_backend.py build/backend/rka3000-backend.exe` 复现，stderr 会被打印。
- 桌面冒烟失败：`smoke_desktop.ps1` 输出隔离 profile 目录下的 `backend.log` 与 `desktop.log`。
- Release 发布任务失败不会留下半成品 Release；修复后用新标签重跑。

## 说明

- 运行时要求 WebView2；安装器联网补齐，便携包离线需预装。
- 未配置 Authenticode 代码签名；SHA-256 不替代签名。
- 未实现自动更新。
