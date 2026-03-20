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
- measurements 已补充批量写入入口，迁移测试与历史查询测试已拆分
- 数据层已增加轻量迁移入口、历史实验查询、报警历史查询和审计日志查询
- Modbus RTU 客户端封装（支持模拟模式）
- 通信层已开始拆分寄存器定义与设备映射，便于后续对接正式寄存器表
- UI 已拆分为配方、监控、报警、设置四个页面，主窗口只负责流程编排
- 执行引擎已接入基础状态机，支持步骤上下文、暂停、恢复、终止和完成判定骨架
- 执行步骤已接入控制下发骨架，启动、恢复和步切换时会触发设定点下发
- 执行链路已补充报警联锁中断/确认后恢复，以及设定点下发失败时的回退与故障停机
- 执行保护已补充步骤升温超时、步骤总超时、采集异常故障停机，以及报警字典/等级/联锁配置
- 已接入 `contract_v1` 映射 profile，寄存器表和报警位定义可按 profile 切换
- `0x0060` 运行控制字 MVP 已接通，支持 start/stop/pause/resume/reset 脉冲下发
- 已保留 `0x0051` 联锁状态字展示、联锁复位按钮和恢复前置条件相关基础实现，当前冻结版本不以联锁闭环作为交付承诺
- 已完成执行引擎与运行控制字联动、采集链路批量落库、控制字与设备反馈字一致性校核的基础实现
- Sprint 2 已引入 `controllers/` 和 `hardware/` 最小骨架，主流程正从 UI 层向控制层迁移
- 当前主流程已开始按 MVC 收敛：`MainWindow` 负责交互与展示，`ExperimentController` 负责实验流程编排，`RecipeController` 负责配方加载与 CRUD 业务，`DeviceGateway` 负责设备访问入口
- 后台采集线程与实时 UI 刷新
- 数据持久化与基础实验记录

## 3. 目录

- `docs/`：PRD、硬件规格、技术栈文档
- `docs/需求确认清单_v1.0.md`：可直接逐项填写的需求确认清单
- `docs/需求冻结记录_v1.0.md`：根据已确认口径整理出的正式需求冻结记录
- `docs/功能边界表_v1.0.md`：当前版本必须做、后续做、不做的功能边界表
- `docs/RKA架构重整建议_v1.0.md`：从当前代码平滑过渡到控制层/硬件层分离架构的建议
- `docs/多Agent组织与职责_v2.0.md`：按产品经理主导与架构先行重写的多 agent 组织基线
- `docs/多Agent任务拆解_v2.0.md`：按冻结需求和新组织方式重写的当前执行任务拆解
- `docs/Sprint2后续路线图_v1.0.md`：结构收敛、最小闭环稳定与 Windows 准备的后续路线图
- `docs/Sprint2_阶段收口报告_v1.0.md`：按冻结口径完成 Sprint 2 的阶段收口结果
- `docs/Windows交付准备清单_v1.0.md`：Windows 打包前置检查、风险与最小交付验证清单
- `docs/多Agent并行开发清单_v1.0.md`：多 agent 并行开发任务拆解
- `docs/Sprint1_任务分解与验收_v1.0.md`：Sprint 1 并行任务包与 Alex 验收标准
- `docs/Sprint1_并行Checklist_v1.0.md`：Sprint 1 各 agent 可直接执行的 checklist
- `docs/Sprint1_阶段验收报告_v1.0.md`：Sprint 1 阶段验收结果与下一阶段建议
- `docs/Sprint1_尾项闭环报告_v1.0.md`：Sprint 1 尾项收口结果
- `docs/Sprint2_联锁流程MVP验收报告_v1.0.md`：Sprint 2 联锁流程 MVP 验收结果
- `docs/Sprint2_执行引擎控制联动验收报告_v1.0.md`：Sprint 2 执行引擎与运行控制字联动验收结果
- `docs/Sprint2_采集批量落库验收报告_v1.0.md`：Sprint 2 采集线程批量落库验收结果
- `docs/Sprint2_控制反馈一致性验收报告_v1.0.md`：Sprint 2 控制字与反馈字一致性验收结果
- `docs/Emma_阶段验收报告_v1.0.md`：Emma 执行引擎阶段验收结果
- `docs/Emma_安全加固阶段验收报告_v1.0.md`：Emma 执行安全加固阶段验收结果
- `docs/正式映射Profile_contract_v1.md`：当前正式寄存器与报警位 profile 定义
- `docs/Leo_正式映射接入验收报告_v1.0.md`：Leo 正式映射接入验收结果
- `docs/Leo_运行控制字MVP验收报告_v1.0.md`：Leo 运行控制字 MVP 验收结果
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

- 仓库已配置 GitHub Actions CI：`.github/workflows/ci.yml`
- 仓库已配置 GitHub Actions 自动 release：`.github/workflows/release.yml`
- PR 和 `main` push 会自动执行测试与编译检查
- 当推送形如 `v0.1.0`、`v1.0.0` 的 tag 时，工作流会安装依赖、执行 `pytest`，然后自动创建 GitHub Release
- release 前会校验 git tag 版本与 `pyproject.toml` 中的版本号一致
- 也支持在 GitHub Actions 页面手动触发

## 6. 协作约束

- 任何分支合并都必须同步更新 README
- README 需要反映最新的功能、工作流、开发与发布方式

## 7. 多 Agent 协作

- 当前建议采用“产品经理主导 + 架构先行 + 领域分工”的组织方式
- 主控 Agent：`Alex`，负责需求拆解、集成协调和阶段验收
- 新增建议角色：`Iris`（架构）、`Nina`（算法）、`Evan`（构建发布）
- 模块 Agent：`Leo`（通信）、`Emma`（控制与业务服务）、`Mia`（UI）、`Ryan`（数据）、`Lily`（测试 CI）、`Owen`（文档交付）
- 当前组织基线见 `docs/多Agent组织与职责_v2.0.md`
- 当前执行任务基线见 `docs/多Agent任务拆解_v2.0.md`
- 当前路线图见 `docs/Sprint2后续路线图_v1.0.md`
- 历史任务拆解仍保留在 `docs/多Agent并行开发清单_v1.0.md`

## 8. 许可

- 本项目为商业项目，采用保留所有权利的专有许可，详见 `LICENSE`
