# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
