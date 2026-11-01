# RKA-3000 铁矿石氧化/还原动力学实验系统（上位机）

面向实验室实验人员的 Windows 10/11 x64 桌面软件：按配方自动配气并采集炉温、重量与气体流量，
记录与查询历史实验，计算失重法还原动力学指标并生成报表。

**技术栈**：桌面窗口 **Tauri 2**（Rust 壳）+ **Svelte 5 / TypeScript / Vite**；业务、数据、计算与设备通信
全部在 **Python** 中，以随包交付的 sidecar（`rka3000-backend.exe`）运行，窗口通过受限、鉴权的本地
JSON API 调用它。终端用户不需要安装 Python、Node.js 或 Rust。

> 版本以 `rka_desktop.__version__`（当前 0.8.0）为准；`scripts/check_version.py` 保证 Python、Rust、
> npm 清单与 CHANGELOG 一致。变更详见 [CHANGELOG.md](CHANGELOG.md)。

## 功能

一次实验按“待机 → 预检 → 运行 → 惰性处置 → 待核查 → 已归档”推进，完整规则见
[docs/experiment-lifecycle.md](docs/experiment-lifecycle.md)。

| 页面 | 能力 |
| --- | --- |
| 实时总览 | 当前或待核查实验、四项关键指标、接下来会发生什么、最近事件、待办 |
| 实验准备 | 三步预检：样品与配方 → 设备回读与现场检查 → 复核与启动；任一启动条件不满足不能启动 |
| 当前实验 | 阶段进度、炉温 / 重量 / 还原度、曲线、事件记录；每种气体一张卡；**按配方 / 手动切换需二次确认**；手动调气三态确认（受理 → 回读验证 → 生效）；提前结束与紧急停气都进入惰性处置 |
| 实验配方 | 还原 / 氧化类型、惰性气（N₂ / Ar）、吹扫参数、7 种气体；保存即评估可执行性；版本历史；导入 / 导出 |
| 历史实验 | 按已归档 / 待核查 / 已中止筛选与搜索；详情、事件摘要、导出 |
| 报警事件 | 待确认（处理说明必填）、已确认、规则与阈值 |
| 分析与归档 | 40% 速率、t₄₀、t₆₀、终态还原 / 氧化度；三种动力学模型拟合；归档前复核与归档；同配方对比 |
| 报告中心 | 仅已归档实验可生成；带版本号的 Excel 报告 |
| 设备诊断 | 三台设备回读新鲜度、MFC 通道设备上限 / 使用上限 / 实测；空闲时手动调试 |
| 操作审计 | 操作者、对象、原因、结果，按类型与实验筛选，导出 CSV |
| 系统设置 | 气体使用上限（预览影响、原因、版本）、采集与设备、主题（浅色 / 深色 / 科技蓝）与当前操作者、诊断与日志 |

**控制语义**：实验按配方阶段自动配气；温度控制默认为“仪表程序”模式——启动时把配方温度曲线一次性下发到
温控仪程序段，由仪表执行，过程中软件不调节温度，配方阶段跟随仪表当前运行段（仪表不支持远程启动 / 停止，
需在面板上操作）。PLC 通路保留“逐段下发设定值”模式。详见 [docs/technical-architecture.md](docs/technical-architecture.md)。

## 下载与安装

发行版见 [GitHub Releases](https://github.com/kevinalliswell/RKA-3000-desktop/releases)。

| 资产 | 用途 |
| --- | --- |
| `RKA3000-desktop_<版本>_windows-x64_setup.exe` | 当前用户 NSIS 安装器，内含 Python 后端；缺少 WebView2 时**联网**下载安装 |
| `RKA3000-desktop_<版本>_windows-x64_portable.zip` | 便携包：完整解压后运行 `rka3000-desktop.exe`，`rka3000-backend.exe` 必须同目录；需已安装 WebView2 Runtime |
| `SHA256SUMS.txt` | 两个资产的 SHA-256，可用 `Get-FileHash <文件> -Algorithm SHA256` 核对 |

要求：Windows 10/11 x64 与 [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
（Windows 11 自带）。离线机器请先安装 WebView2 后再使用便携包。当前**未配置代码签名**，系统可能提示未知
发布者；SHA-256 只用于核对下载完整性，不等同于签名。**未实现自动更新**，升级请下载新版本覆盖安装；
升级与卸载默认保留用户数据。

## 用户数据与日志

| 内容 | Windows 位置 | 说明 |
| --- | --- | --- |
| 配置 | `%LOCALAPPDATA%\RKA3000\config.json` | 原子写入的 JSON；未知字段与损坏文件会报错而不是被覆盖 |
| 数据库 | `%LOCALAPPDATA%\RKA3000\data\rka3000.db` | SQLite（schema v2，与 v0.7 兼容） |
| 导出与报告 | `%LOCALAPPDATA%\RKA3000\exports\` | CSV / Excel / 报告 |
| 日志 | `%LOCALAPPDATA%\RKA3000\logs\backend.log`、`desktop.log` | 后端 5 MB 轮转×3；桌面壳启动诊断 |
| 备份 | `%LOCALAPPDATA%\RKA3000\backups\` | 导入旧数据库时的自动备份 |

macOS 对应 `~/Library/Application Support/RKA3000/`，Linux 为 `~/.local/share/rka3000/`；
环境变量 `RKA3000_DATA_DIR` 可覆盖。日志不记录令牌与密码。

旧版本（v0.7 及以前）的 `.env` 与 `data/rka.db` 迁移方法见 [docs/migration.md](docs/migration.md)。

## 开发

需要 Python ≥ 3.10（发布用 3.12）、Node.js ≥ 20（CI 用 22）、Rust stable；Windows 另需
Visual Studio C++ Build Tools、Windows SDK 与 WebView2 Runtime。

```bash
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
npm ci && npm --prefix frontend ci
npm run tauri dev
```

`npm run tauri dev` 启动 Vite 与 Tauri 开发窗口；开发构建使用仓库 `.venv` 中的 Python（或
`RKA3000_PYTHON` 指定的解释器）运行 `python -m rka_desktop.adapters.api`，不会回退到 PATH 上的任意解释器。
发布构建只运行随包的 `rka3000-backend.exe`。

### 无原生工具链时在浏览器联调

```bash
export RKA3000_API_TOKEN=local-development-only-token-change-me   # PowerShell: $env:RKA3000_API_TOKEN=...
python -m rka_desktop.adapters.api --port 8765        # 终端一
npm --prefix frontend run dev                          # 终端二，同样设置 RKA3000_API_TOKEN
```

打开 <http://127.0.0.1:5174>。令牌只由 Python 与 Vite 代理读取，不进入前端包。浏览器模式**不能**验证
Tauri 的窗口与进程生命周期。

### 命令行

```bash
python -m rka_desktop paths                      # 数据目录、数据库、日志位置
python -m rka_desktop recipes list
python -m rka_desktop export 12 --kind measurements_csv
python -m rka_desktop kinetics 12 --m0 50 --tfe 60 --feo 0 --report
python -m rka_desktop import-legacy-db data/rka.db
```

## 验证

```bash
python -m pytest -q
python -m ruff check .
python scripts/check_version.py
python scripts/smoke_backend.py                  # 源码后端：握手、鉴权、健康、配方、关闭
npm --prefix frontend run check
npm --prefix frontend run test
npm --prefix frontend run build
cargo fmt --manifest-path src-tauri/Cargo.toml -- --check
cargo check --locked --manifest-path src-tauri/Cargo.toml
```

GitHub Actions `Checks` 在 PR 与 `main` 推送时运行上述检查，并在 Windows runner 上冻结 Python 后端、
构建 NSIS 安装器与便携包、执行后端/桌面/安装卸载冒烟并上传资产；`Release` 在 `v*` 标签上复用同一流程，
校验资产后创建 GitHub Release。详见 [docs/releasing.md](docs/releasing.md)。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [docs/technical-architecture.md](docs/technical-architecture.md) | 组件关系、请求与数据流、进程生命周期、鉴权边界、构建分发 |
| [docs/layered-design.md](docs/layered-design.md) | 六层职责、依赖方向、组合根、新增功能步骤、测试对应 |
| [docs/api.md](docs/api.md) | 本地 JSON API：请求/响应结构、错误语义、任务与运行状态、版本 |
| [docs/protocols.md](docs/protocols.md) | 设备通路：TAIE 程序段、Azbil CPL、天平、PLC contract_v1 |
| [docs/experiment-lifecycle.md](docs/experiment-lifecycle.md) | 实验生命周期、预检、处置、报警、复核归档的业务规则 |
| [docs/migration.md](docs/migration.md) | 旧结构到新结构的映射、配置与数据兼容、回退与剩余风险 |
| [docs/releasing.md](docs/releasing.md) | 工具链、本地构建、CI/CD、版本与标签、资产验收 |
| [docs/analysis/current-state-2026-10-31.md](docs/analysis/current-state-2026-10-31.md) | 迁移前的现状分析 |
| [docs/legacy/](docs/legacy/) | PySide6 时代的架构与部署文档（存档） |

产品需求、硬件规格与联调 SOP 等历史文档仍在 `docs/` 下保留。

## 已知限制

- 仅发布并验证 Windows x64；macOS/Linux 可从源码运行但未提供构建产物。
- CI 冒烟覆盖冻结后端、窗口启动/退出、安装/卸载，**不替代真机设备验收**；TAIE 程序段时间单位、
  MFC 满量程与串口参数需在现场确认。
- 多设备通路没有 PLC 报警/联锁字与气体探头，硬件报警联锁仅在 PLC 通路有效；软件报警规则只覆盖炉温、
  MFC 偏差、天平跳变与回读过期。断电或后端被强杀时无法保证最后一条设备命令（含吹扫设定）送达。
- 未启用账号与权限；“当前操作者”由使用者自行填写，审计中的操作者未经认证。
- TAIE `SEG`（当前运行段）在程序未运行时的取值未在现场确认。
- 未签名、无自动更新、安装器补齐 WebView2 需要联网。

## 协作约束

- 任何分支合并都必须同步更新 README。
- README 需要反映最新的功能、工作流、开发与发布方式。

## 许可

商业项目，保留所有权利，详见 [LICENSE](LICENSE)；第三方组件许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
