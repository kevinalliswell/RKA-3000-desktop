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
- SQLite 自动建库建表
- Modbus RTU 客户端封装（支持模拟模式）
- 后台采集线程与实时 UI 刷新
- 数据持久化与基础实验记录

## 3. 目录

- `docs/`：PRD、硬件规格、技术栈文档
- `src/rka_desktop/`：应用源码
- `tests/`：测试代码

## 4. 说明

- 设备参数冲突项已按合同附件冻结，详见 `docs/硬件规格书_v1.0.md`。
- 默认开启 `SIMULATION_MODE=true`，便于离线开发。

## 5. Release 工作流

- 仓库已配置 GitHub Actions 自动 release：`.github/workflows/release.yml`
- 当推送形如 `v0.1.0`、`v1.0.0` 的 tag 时，工作流会安装依赖、执行 `pytest`，然后自动创建 GitHub Release
- 也支持在 GitHub Actions 页面手动触发

## 6. 协作约束

- 任何分支合并都必须同步更新 README
- README 需要反映最新的功能、工作流、开发与发布方式
