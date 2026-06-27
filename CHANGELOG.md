# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-06-27

### Added
- Simulation-first multi-device communication layer (`rka_desktop.comm`): vendored Azbil
  MFC (6 channels, CPL), TAIE temperature controller (Modbus RTU), and electronic balance
  (gs_cpa/longteng) drivers behind narrow RKA ports.
- `MultiDeviceGateway` implementing the `SnapshotSource` seam, mapping multi-device
  readings onto the legacy `DeviceSnapshot` (N2/H2/CO selected by gas type) and exposing a
  richer `MultiDeviceSnapshot`.
- Simulation adapters for all three device types (hardware-free, deterministic) with tests.

### Changed
- `AcquisitionWorker` now accepts any `SnapshotSource` (the legacy `ModbusRtuClient` still
  works unchanged).
- Version is now single-sourced from `rka_desktop.__version__`; `pyproject.toml` reads it
  dynamically.

### Build
- Added `CHANGELOG.md`, `scripts/release.py` bump/notes helper, and a version-sync CI check.
- `release.yml` now publishes the matching CHANGELOG section as release notes.
