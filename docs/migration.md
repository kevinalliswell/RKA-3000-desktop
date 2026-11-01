# 迁移说明：PySide6 → Tauri 2 + Svelte 5 + Python sidecar

本文说明 v0.7.0 到 v0.8.0 的结构变化、数据与配置兼容方式、回退方法与剩余风险。迁移前的现状分析见
[analysis/current-state-2026-10-31.md](analysis/current-state-2026-10-31.md)。

## 结构映射

| 旧位置（v0.7.0） | 新位置（v0.8.0） | 处理 |
| --- | --- | --- |
| `models/entities.py` | `domain/entities.py` | 保留 |
| `services/experiment_engine.py` | `domain/experiment_engine.py` | 保留，步骤类型改为 `domain/recipe.RecipeStep` |
| `services/recipe_runtime_service.py` + `controllers/recipe_controller.py` 校验 | `domain/recipe.py` | 合并为校验值对象；新增范围校验与导入/导出格式 |
| `core/alarm_rules.py` | `domain/alarm_rules.py` | 保留 |
| `analysis/reduction_kinetics.py` + `ui/analysis_page._to_series` | `domain/kinetics.py` | 保留，序列转换移入领域 |
| — | `domain/control.py` | 新增：配气/温度控制模式与切换确认规则 |
| `controllers/experiment_controller.py` + `services/acquisition_service.py` + `ui/runtime_coordinator.py` | `application/experiment_runner.py` | 重写执行模型（线程 + JSON 快照），业务判定沿用 |
| `controllers/recipe_controller.py` | `application/recipe_service.py` | 用例化 |
| `controllers/history_export_controller.py` + `ui/main_window` 的重命名/删除 | `application/history_service.py` | 用例化，导出改为后台任务 |
| `ui/analysis_page.py` 的计算/保存 + `ui/main_window.export_analysis_report` | `application/analysis_service.py` | 用例化，报告改为后台任务 |
| `ui/multi_device_page.py` 的手动控制 | `application/device_service.py` | 用例化，增加互斥与确认 |
| — | `application/tasks.py`、`application/ports.py` | 新增 |
| `db/database.py`、`db/migrations.py` | `infrastructure/sqlite/` | 保留，补分页、删配方、审计裁剪 |
| `repositories/*.py` | `infrastructure/sqlite/repositories.py` | 合并为端口实现 |
| `comm/`（含 `_vendor/`） | `infrastructure/comm/` | 保留；TAIE 适配器增加程序段写入 |
| `core/modbus_client.py`、`device_map.py`、`registers.py` | `infrastructure/comm/plc/` | 保留 |
| `hardware/device_gateway.py` | `infrastructure/gateways.py` | 扩展为两种 `ExperimentGateway` 实现 |
| `services/export_service.py`（pandas） | `infrastructure/exports/export_service.py` | 改用 csv/openpyxl，列不变 |
| `reporting/report_service.py` | `infrastructure/exports/report_service.py` | 保留 |
| `core/config.py`（pydantic-settings `.env`） | `infrastructure/config.py`（JSON）+ `paths.py` | 重写，支持导入旧 `.env` |
| `core/logging_config.py`（写 `logs/`） | `infrastructure/logging_setup.py` | 重写，写用户数据目录，过滤令牌 |
| `main.py`（QApplication） | `bootstrap.py` + `adapters/api/server.py` + `adapters/cli/main.py` | 替换 |
| `ui/*`（PySide6） | `frontend/src/features/*`（Svelte 5） | 替换；Qt 代码删除 |
| `scripts/packaging/*`（PyInstaller 整包） | `scripts/build_backend.py` + Tauri NSIS + `stage_release.py` | 替换 |
| `.github/workflows/ci.yml`、`release.yml`、`windows-package-smoke.yml` | `checks.yml`、`release.yml` | 替换 |

## 配置兼容

- 旧配置来自工作目录 `.env`（`APP_NAME`、`DB_PATH`、`SERIAL_PORT`、`BAUDRATE`、`MODBUS_UNIT_ID`、
  `MAPPING_PROFILE`、`SIMULATION_MODE`、`POLL_INTERVAL_MS`、`ACQUISITION_BATCH_SIZE`、
  `STEP_HEATUP_GRACE_SECONDS`、`STEP_TOTAL_GRACE_SECONDS`）。
- 新版首次启动（用户数据目录下尚无 `config.json`）时，若工作目录存在 `.env`，自动导入上述键并写入 `config.json`；
  未识别的键记录到日志并忽略（不静默丢弃）。也可用 `--legacy-env <路径>` 指定。
- 导入含 `SERIAL_PORT` 的旧配置时，自动选择 `device_backend = plc_modbus`、`temperature_mode = setpoint`，
  保持迁移前“每步写温度设定”的行为；相对 `DB_PATH` 解析为相对于 `.env` 所在目录的绝对路径。
- 之后 `config.json` 为唯一配置来源；`RKA3000_SIMULATION_MODE`、`RKA3000_DB_PATH`、`RKA3000_DATA_DIR` 环境变量可在开发/CI 中覆盖。

## 数据兼容

- SQLite 表结构（`recipes`、`recipe_steps`、`experiments`、`measurements`、`alarms`、`audit_logs`、`schema_meta`）与
  schema v2 完全一致；`init_schema()` 的增列逻辑保留，v0.3 之前的库仍会被升级。
- 默认数据库位置从工作目录 `data/rka.db` 改为用户数据目录。迁移方式：
  1. `python -m rka_desktop import-legacy-db <旧库路径>`（或冻结包目录下的 `rka3000-backend.exe` 不提供 CLI 子命令时，
     使用源码环境执行）。命令把旧库复制到新位置，若目标已存在则先备份到 `backups/`。
  2. 或在设置页/`config.json` 的 `db_path` 填写旧库的绝对路径继续使用原文件。
- 实验状态值、报警代码、审计动作名保持不变；新增审计动作：`GAS_MODE_SWITCH`、`MANUAL_GAS_SET`、
  `TEMPERATURE_PROGRAM_DOWNLOADED`、`MANUAL_MFC_SET`、`MANUAL_TEMPERATURE_SET`、`BALANCE_TARE`、`RECIPE_DELETE`、`RECIPE_IMPORT`。
- 导出的 CSV/Excel 列名与顺序不变；文件默认写入用户数据目录 `exports/` 而不是工作目录 `exports/`。

## 行为变化（有意为之）

| 变化 | 原因 |
| --- | --- |
| 默认设备通路为“温控仪 + MFC + 天平”（仿真），温度模式 `program` | 符合现场约定：配方自动配气、控温仪一次下发程序后自动执行 |
| 配气模式可切换为手动，运行中切换需二次确认 | 需求明确要求 |
| 设备持续无响应（默认 30 s）导致实验故障停止 | 多设备网关以“保持上次有效值”报告降级，需要上限避免长期使用陈旧数据 |
| 配方步骤增加范围校验（温度 0–1600 ℃、流量 0–50 L/min、步骤 ≤ 32） | 旧版只校验名称与步骤数 |
| 停止实验进入 `stopping`，落库完成后才终态 | 取消不得冒充已停止 |
| 删除配方、配方/配置 JSON 导入导出、设备页写入需确认 | 需求中的导入导出能力与副作用确认 |

## 已迁移 / 仍保留

- 已迁移：全部页面、实验流程、采集、报警联锁处理、历史与导出、分析与报告、设备手动控制、配置、日志、打包与 CI。
- 仍保留且未改动：SQLite 表结构与查询、执行引擎判定、报警/联锁字表、`contract_v1` 寄存器映射、钉定驱动与多设备网关。
- 未保留：PySide6 界面与 Qt 相关测试；`controllers/`、`ui/`、`hardware/`、`repositories/` 包；PyInstaller 整包 spec。

## 回退

- 代码：旧实现完整保留在 `main` 分支 v0.7.0 提交（`a7df933`）及其 `v0.7.0` 变更记录；检出该提交并按旧 README 安装 PySide6 依赖即可运行。
- 数据：新版不修改表结构，旧版可直接打开新版数据库文件（复制回 `data/rka.db` 或设置 `DB_PATH`）。
- 配置：旧 `.env` 不会被删除或修改。

## 剩余风险

- TAIE 程序段时间寄存器的单位（分钟/秒）与段语义（到达目标的时间 vs 保温时间）来自驾驱手册推断，`temp_segment_time_unit`
  需在现场核对；仪表不支持远程启动，程序需在面板上启动。
- 多设备通路没有报警/联锁字（始终为 0），报警联锁流程只在 PLC 通路有效。
- Windows 冻结、NSIS、便携包、安装/卸载与进程残留仅在 GitHub Actions 的 Windows runner 验证，未在真实实验机验证。
- 本次未连接真实串口设备；驱动帧级逻辑沿用钉定版本并保留其测试。
