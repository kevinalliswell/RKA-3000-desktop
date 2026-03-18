# RKA Desktop Scaffold

基于 Python3.10+、PySide6、SQLite3、RS-485/Modbus RTU 的桌面端项目脚手架。

## 1. 快速开始

```bash
python3.10 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -e ".[dev]"
cp .env.example .env
python -m rka_desktop.main
```

## 2. 当前能力（v1.1.0）

- 应用主窗口（设备状态、实时采样、最近数据）
- 配方编辑器（多步骤、新建、更新、选择执行）
- 实时曲线（温度/重量）
- 报警入库与确认流
- 实验数据导出（CSV / Excel）
- 实验摘要导出（CSV）
- SQLite 自动建库建表
- 数据层已增加轻量迁移入口、历史实验查询、报警历史查询和审计日志查询
- Modbus RTU 客户端封装（支持模拟模式）
- 通信层已开始拆分寄存器定义与设备映射，便于后续对接正式寄存器表
- UI 已拆分为配方、监控、报警、设置四个页面，主窗口只负责流程编排
- 后台采集线程与实时 UI 刷新
- 数据持久化与基础实验记录

## 3. 目录

- `docs/`：PRD、硬件规格、技术栈文档
- `docs/多Agent并行开发清单_v1.0.md`：多 agent 并行开发任务拆解
- `docs/Sprint1_任务分解与验收_v1.0.md`：Sprint 1 并行任务包与 Alex 验收标准
- `docs/Sprint1_并行Checklist_v1.0.md`：Sprint 1 各 agent 可直接执行的 checklist
- `docs/Sprint1_阶段验收报告_v1.0.md`：Sprint 1 阶段验收结果与下一阶段建议
- `docs/安装部署手册_v1.0.md`：环境安装与首次启动说明
- `docs/环境依赖与串口配置_v1.0.md`：依赖与串口配置说明
- `docs/联调SOP_v1.0.md`：现场联调标准流程
- `docs/打包发布说明_v1.0.md`：PyInstaller 打包与发布流程
- `docs/发布说明模板_v1.0.md`：版本发布说明模板
- `scripts/packaging/build_pyinstaller.sh`：桌面端打包脚本
- `src/rka_desktop/`：应用源码
- `tests/`：测试代码

## 4. 说明

- 设备参数冲突项已按合同附件冻结，详见 `docs/硬件规格书_v1.0.md`。
- 默认开启 `SIMULATION_MODE=true`，便于离线开发。
- 现场部署、串口配置、联调和打包流程已补充到 `docs/` 与 `scripts/packaging/`。

## 5. Release 工作流

- 仓库已配置 GitHub Actions 自动 release：`.github/workflows/release.yml`
- 当推送形如 `v0.1.0`、`v1.0.0` 的 tag 时，工作流会安装依赖、执行 `pytest`，然后自动创建 GitHub Release
- 也支持在 GitHub Actions 页面手动触发

## 6. 协作约束

- 任何分支合并都必须同步更新 README
- README 需要反映最新的功能、工作流、开发与发布方式

## 7. 多 Agent 协作

- 主控 Agent：`Alex`，由 Codex 负责任务分解、集成协调和验收
- 模块 Agent：`Leo`（通信）、`Emma`（执行引擎）、`Mia`（UI）、`Ryan`（数据）、`Lily`（测试 CI）、`Owen`（文档交付）
- 详细拆分见 `docs/多Agent并行开发清单_v1.0.md`

## 8. 许可

- 本项目为商业项目，采用保留所有权利的专有许可，详见 `LICENSE`
