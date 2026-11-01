# 现状分析与迁移方案（2026-10-31）

本文记录 Tauri 2 + Svelte 5 迁移开始前对 `RKA-3000-desktop` v0.7.0 的检查结果，是 [docs/migration.md](../migration.md) 的依据。所有结论均以源码为准，行号对应迁移前的 `main` 分支（提交 `a7df933`）。

## 1. 现状问题（含源码依据）

| 问题 | 依据 | 影响 |
| --- | --- | --- |
| UI 与业务耦合 | `controllers/experiment_controller.py:491,528,535` 在业务层拼接 Qt 样式字符串（`color: #b71c1c; font-weight: bold;`），`RuntimeViewState` 直接承载按钮启用状态 | 业务层无法脱离 Qt 复用，无法为 HTTP/CLI 复用同一用例 |
| 采集线程依赖 Qt | `services/acquisition_service.py:6,16` 的 `AcquisitionWorker` 继承 `QThread` 并用 `Signal` 投递数据；`ui/runtime_coordinator.py` 持有线程生命周期 | 后端进程无法脱离 QApplication 运行，无法作为 sidecar |
| 相对路径写入当前目录 | `core/config.py:9`（`data/rka.db`）、`core/logging_config.py:7`（`logs/`）、`ui/main_window.py:298,446`（`exports/`） | 安装到 Program Files 后写入失败；依赖启动目录 |
| 两套设备通路并存 | `main.py` 为实验流程注入 `ModbusRtuClient`（PLC `contract_v1` 寄存器表），`ui/main_window.py:182` 另建 `MultiDeviceGateway`（TAIE/Azbil/天平）仅供「设备状态」子页手动控制 | 实验流程与真实仪表控制分离；手动控制与自动流程无互斥 |
| 温度与配气的控制语义未分离 | `controllers/experiment_controller.py:323-343` 在启动、恢复与每次步切换都重写温度 SP 与升温速率 | 与“控温仪下发程序后自动执行、过程中不调整”的现场约定不一致 |
| 缺少手动/自动配气模式 | 无模式概念；`ui/multi_device_page.py:127` 可在实验运行时直接改写 MFC 设定 | 运行中切换模式无确认，存在误操作风险 |
| 打包复杂、残留风险 | `scripts/packaging/rka_desktop.spec` 打包整套 PySide6（含 QtCharts）；`windows-package-smoke.yml` 仅手动触发且不做启动/退出验证 | 包体大、无发布链路；无进程残留验证 |
| CI 容忍 Qt 崩溃 | `.github/workflows/ci.yml` 使用 `pytest || true` 再解析 JUnit 报告 | 退出码不可信，掩盖真实崩溃 |
| 版本多源 | 版本只在 `rka_desktop.__init__` 与 CHANGELOG 同步，无桌面/前端清单 | 迁移后需要跨 Python/Rust/npm 的版本一致性检查 |

## 2. 可直接保留的模块

| 模块 | 说明 | 新位置 |
| --- | --- | --- |
| `analysis/reduction_kinetics.py` | 纯函数，已有手算回归测试 | `domain/kinetics.py` |
| `services/experiment_engine.py` | 纯状态机，无 I/O | `domain/experiment_engine.py` |
| `services/recipe_runtime_service.py` | 配方步骤值对象 | `domain/recipe.py`（并入校验规则） |
| `core/alarm_rules.py` | 报警/联锁字解码 | `domain/alarm_rules.py` |
| `models/entities.py` | 测量、快照数据类 | `domain/entities.py` |
| `db/database.py`、`db/migrations.py` | SQLite 表结构与查询（schema v2） | `infrastructure/sqlite/` |
| `comm/`（含 `_vendor/`） | 多设备通讯层与钉定驱动 | `infrastructure/comm/` |
| `core/modbus_client.py`、`core/device_map.py`、`core/registers.py` | PLC Modbus 通路与寄存器映射 | `infrastructure/comm/plc/` |
| `reporting/report_service.py` | openpyxl 报告 | `infrastructure/exports/report_service.py` |

## 3. 需要解耦或迁移的模块

| 模块 | 处理 |
| --- | --- |
| `controllers/experiment_controller.py` | 拆为应用层 `ExperimentRunner`（流程、互斥、取消、配气模式）与纯数据的运行快照；删除样式字符串与按钮状态 |
| `services/acquisition_service.py` | 改为标准 `threading.Thread` 采集循环，归应用层任务管理 |
| `controllers/recipe_controller.py`、`history_export_controller.py` | 合并为应用层用例，表单解析由 API 层做类型转换，领域层做最终校验 |
| `services/export_service.py` | 去掉 pandas，改用标准库 `csv` + openpyxl（输出列与顺序保持一致） |
| `core/config.py` | 去掉 pydantic-settings；配置改为用户数据目录下的 JSON（原子写入），兼容读取旧 `.env` |
| `ui/`（全部）、`core/logging_config.py` | Qt 界面由 Svelte 页面替代并删除；日志改写用户数据目录 |
| `main.py` | 替换为组合根 `bootstrap.py` + API/CLI 入口 |

## 4. 目标结构与迁移顺序

1. **Python 分层**：建立 `domain/`、`application/`、`infrastructure/`、`adapters/`，迁移上述模块并保持旧测试通过（回归基线）。
2. **本地 API**：`adapters/api` 提供 loopback + 随机令牌 + 动态端口的 JSON 接口，`bootstrap.py` 组合依赖。
3. **桌面壳**：`src-tauri` 启动/监测/关闭 sidecar，白名单 IPC。
4. **前端**：`frontend/` Svelte 5 页面按业务功能组织：配方、运行监控、设备、数据分析、历史、报警、日志、设置。
5. **构建与 CI**：PyInstaller 冻结、Tauri NSIS/便携包、SHA-256、Windows 冒烟与安装卸载验收。
6. **文档**：README、架构、分层、API、迁移、发布、CHANGELOG。

## 5. 主要兼容性风险与验证

| 风险 | 验证方式 |
| --- | --- |
| 旧数据库路径 `data/rka.db` 不再是默认位置 | 启动时识别旧 `.env`/`DB_PATH` 与工作目录下的旧库，提供迁移命令与文档；`tests/test_legacy_compat.py` 覆盖 |
| schema v2 数据库升级 | 保留原 `init_schema` 增列逻辑，`tests/test_migrations.py` 继续运行 |
| 实验流程判定变化（温度不再逐步下发） | 以配气模式与温度程序模式显式配置；默认保持原 PLC 通路行为，旧引擎测试不改 |
| 报表/导出格式 | 保留列名与顺序，`tests/test_export_service.py` 对比输出内容 |
| Windows 打包、WebView2、进程残留 | GitHub Actions Windows runner 冒烟脚本；本机（macOS）无法验证 Windows 分发 |
