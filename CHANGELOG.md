# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.8.0] - 2026-10-31
### Changed
- **桌面技术栈迁移**：界面由 PySide6 改为 **Tauri 2 + Svelte 5 / TypeScript**；Python 以随包交付的
  sidecar（`rka3000-backend.exe`）继续承担业务、数据、计算与设备通信。页面按业务组织：运行监控、
  配方、设备、数据分析、历史、报警与日志、设置；支持浅色/深色主题。
- **Python 六层分层**：`domain/`（纯规则：配方校验、执行引擎、报警字、失重法动力学、控制模式）、
  `application/`（实验运行用例、任务注册表、配方/历史/分析/设备用例、端口声明）、`adapters/`
  （loopback JSON API 与 CLI）、`infrastructure/`（SQLite、串口/Modbus 设备、导出、配置、日志）、
  `bootstrap.py` 组合根。旧 `controllers/`、`ui/`、`services/`、`repositories/`、`hardware/` 已移除。
- **本地 API**：仅监听 127.0.0.1、动态端口、每次启动随机 Bearer 令牌、1 MB 请求体上限、
  统一错误语义（`error.code` / `error.message`）、接口版本号；桌面壳 IPC 白名单，`/api/shutdown`
  只供桌面壳调用。
- **配气与控温语义显式化**：配气模式 `auto`（按配方步骤自动下发 N₂/H₂/CO）或 `manual`（操作员手动下发），
  **运行中切换需二次确认**；温度控制模式 `program`（启动时把配方温度曲线一次性下发到 TAIE 程序段，过程中不调整）
  或 `setpoint`（迁移前行为：每步写入 SP 与升温速率，用于 PLC 通路）。
- **实验运行即长任务**：状态 `idle → starting → running/paused/interrupted → stopping → stopped/completed/faulted`；
  停止是请求，缓冲数据落库完成后才进入终态；已终止的实验不被迟到的请求改写。导出与报告作为后台任务
  （`queued → running → completed/failed`，`running → cancelling → cancelled`）。
- **用户数据目录**：数据库、配置、日志、导出不再写入工作目录，而是平台用户数据目录
  （Windows `%LOCALAPPDATA%\RKA3000\`）；配置改为原子写入的 JSON，首次启动自动导入旧 `.env`，
  旧数据库可用 `rka3000 import-legacy-db` 迁入并自动备份。
- **导出**：CSV/Excel 导出不再依赖 pandas（列名与顺序不变）；pydantic-settings、PySide6、
  pyqtdarktheme、qtawesome 已移出依赖。
- **CI/CD**：`Checks` 工作流（Linux 快速测试 + Windows x64 全链路：pytest、ruff、svelte-check、
  vitest、Vite 构建、cargo fmt、PyInstaller 冻结、冻结后端冒烟、Tauri NSIS 构建、便携包、SHA256SUMS、
  桌面启动/退出与安装/卸载验收）；`Release` 工作流在标签上复用 Checks，校验资产后创建 Release，
  带 `-` 的标签标记 prerelease。版本一致性由 `scripts/check_version.py` 检查。

### Added
- 设备页：空闲时手动下发 MFC 流量 / 温控 SV / 天平去皮（均需确认，实验运行中禁止）。
- 配方 JSON 导入/导出（`rka3000-recipe` 格式）、配置 JSON 导入/导出、后端日志查看与下载。
- 设备持续无响应（默认 30 s）导致实验故障停止的保护。
- 多设备通路下按气体类型映射 MFC 通道；配方步骤校验（温度 0–1600 ℃、流量 0–50 L/min 等）。
- CLI：`rka3000 api | paths | import-legacy-db | recipes | export | kinetics`。

### Removed
- PySide6 界面与 Qt 相关测试；PyInstaller 整包打包脚本（`scripts/packaging/`）；旧 CI 工作流。

### Compatibility
- SQLite 表结构不变（schema v2），旧数据库可直接迁入。
- 实验状态值（RUNNING/PAUSED/INTERRUPTED/STOPPED/COMPLETED/FAULTED）、报警与审计表不变。
- 默认设备通路改为“温控仪 + MFC + 天平（仿真）”；导入旧 `.env`（含 `SERIAL_PORT`）时自动选择
  PLC 通路与 `setpoint` 温度模式以保持旧行为。

### Verification
- 本次验证：Python 单元/集成测试（含 API、运行生命周期、任务取消、配置、分层守卫）、ruff、
  svelte-check、vitest、Vite 生产构建、`cargo fmt` 与 `cargo check`（macOS）。Windows 冻结、NSIS、
  便携包与安装/卸载验收由 GitHub Actions 执行；真机串口设备、WebView2 离线部署未在本次验证。

## [0.7.0] - 2026-06-29
### Added
- **Reusable UI component library** (`rka_desktop.ui.components`): `Card` (a titled
  container block) and `MetricTile` (a KPI block — icon + label + big value + unit).

### Changed
- **Componentized, dashboard-style layout.** Metric-heavy areas are recomposed as modular
  blocks: 数据分析 关键指标 is now a row of four KPI tiles, and 监控 实时数据 is six colored
  KPI tiles (温度/重量/压力/N₂/H₂/CO) with run status in its own card.

## [0.6.0] - 2026-06-28
### Changed
- **Professional UI redesign.** A cohesive design system (built on `pyqtdarktheme` +
  `qtawesome`): a light theme with brand accent, a navy app header (title + version), a
  status bar, Material Design icons on the toolbar and tabs, card-style sections, primary
  accent action buttons, and restyled antialiased charts with readable axes. Replaces the
  unstyled default Qt look across every page.

## [0.5.0] - 2026-06-28
### Added
- **日志 tab**: an in-app audit-log viewer showing operator actions (time / actor / action / detail).
- **Experiment management** on the 历史 page: 重命名 (rename) and 删除 (delete) experiments.
  Delete cascades the experiment's measurements and alarms and is blocked for a running
  experiment; rename and delete are both written to the audit log.

## [0.4.0] - 2026-06-28
### Added
- **实验报告生成**: a 生成报告 button on the 数据分析 page exports an Excel report
  (summary sheet with sample params and key indices, a data sheet, and an embedded
  R(t) line chart) via the new `rka_desktop.reporting` service.
- **帮助 menu** with 使用帮助 (quick usage guide) and 关于 (shows the app version).

## [0.3.0] - 2026-06-28
### Added
- **数据分析** (data analysis) is now a headline top-level tab: 失重法 (mass-loss method)
  reduction-degree kinetics. Pick an experiment, enter/save per-experiment sample params
  (initial mass m₀, TFe%, FeO%), and view R(t) and dR/dt curves plus key indices (final
  reduction degree, time to 40%/60%, reduction rate at 40%).
- `rka_desktop.analysis.reduction_kinetics`: pure, hardware-free computation of reduction
  degree and rate, validated against hand-computed values.
- Per-experiment sample parameters persisted on the `experiments` table (schema v2 migration,
  applied idempotently to existing databases).

### Changed
- Device communication is demoted from a headline to a supporting service: the multi-device
  monitor/control panel is now a **设备状态** view nested under 监控, not a top-level tab.

## [0.2.0] - 2026-06-27

### Added
- Simulation-first multi-device communication layer (`rka_desktop.comm`): vendored Azbil
  MFC (6 channels, CPL), TAIE temperature controller (Modbus RTU), and electronic balance
  (gs_cpa/longteng) drivers behind narrow RKA ports.
- `MultiDeviceGateway` implementing the `SnapshotSource` seam, mapping multi-device
  readings onto the legacy `DeviceSnapshot` (N2/H2/CO selected by gas type) and exposing a
  richer `MultiDeviceSnapshot`.
- Simulation adapters for all three device types (hardware-free, deterministic) with tests.
- **设备状态** view nested under the 监控 tab (a secondary view, not a headline feature):
  live temperature PV/SV, six MFC channels with editable setpoints and live flow readback,
  balance weight + tare, and a degraded-link indicator — driven by `MultiDeviceGateway` on a
  poll timer.

### Changed
- `AcquisitionWorker` now accepts any `SnapshotSource` (the legacy `ModbusRtuClient` still
  works unchanged).
- Version is now single-sourced from `rka_desktop.__version__`; `pyproject.toml` reads it
  dynamically.

### Build
- Added `CHANGELOG.md`, `scripts/release.py` bump/notes helper, and a version-sync CI check.
- `release.yml` now publishes the matching CHANGELOG section as release notes.
- CI now installs headless Qt system libraries (`libegl1` et al.) and runs the suite under
  `QT_QPA_PLATFORM=offscreen`, so the PySide6 GUI tests execute on the Ubuntu runner.
