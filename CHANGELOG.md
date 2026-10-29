# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 真实设备只读诊断在首次连接后后台扫描，并以可配置的低频周期复查通讯状态；逐设备显示在线、离线、读数待稳定或状态过期，并尝试重连读取失败的端口。

### Changed
- 三设备只读诊断改用明确的现场配置与逐设备故障状态；MFC 流量按实机量程元数据换算，首次读取失败不再显示为有效零值。
- 加固 CPL、TAIE Modbus RTU 与天平 ASCII 报文校验；真实设备的温度、流量与去皮写入默认拒绝。

### Fixed
- 关闭窗口时不再在 UI 线程等待正在进行的设备诊断扫描；扫描结束后自动完成关闭。

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
