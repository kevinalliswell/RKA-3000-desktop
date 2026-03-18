# RKA-3000 Sprint 1 任务分解与验收 v1.0

- 文档版本：v1.0
- 日期：2026-03-18
- 主控 Agent：`Alex`
- 当前目标：启动第一批并行开发任务，形成稳定的接口、页面、数据和交付基线

## 1. Sprint 1 总目标

- 冻结通信层接口边界
- 让 UI 从单页主窗口走向模块化结构
- 让数据层具备迁移和历史查询能力
- 让部署和交付文档具备客户现场可执行性

## 2. Sprint 1 参与 Agent

- `Leo`：通信与设备抽象
- `Mia`：UI 与交互体验
- `Ryan`：数据库、日志与导出
- `Owen`：文档、安装包与交付

## 3. 分支安排

- `Leo`：`codex/leo-comm-core`
- `Mia`：`codex/mia-ui-refactor`
- `Ryan`：`codex/ryan-data-export`
- `Owen`：`codex/owen-docs-packaging`

## 4. 公共接口冻结原则

- 本 Sprint 不允许随意修改数据库核心表名
- 本 Sprint 不允许删除模拟模式
- 本 Sprint 不允许把所有逻辑继续堆回 `main_window.py`
- 本 Sprint 所有分支合并前必须更新 `README.md`
- 所有公共接口变更必须先由 `Alex` 审核

## 5. Leo 任务包

- 目标
  - 把当前 `modbus_client.py` 的寄存器读取从示例实现演进为可配置、可扩展的设备抽象
- 负责文件
  - `src/rka_desktop/core/modbus_client.py`
  - 新增 `src/rka_desktop/core/registers.py`
  - 新增 `src/rka_desktop/core/device_map.py`
- 可新增文件
  - `tests/test_modbus_client.py`
- 本 Sprint 必做
  - 定义寄存器描述结构
  - 抽象温度、重量、压力、流量读取接口
  - 将硬编码地址迁移到寄存器定义层
  - 保留模拟模式，并让模拟模式走统一读取接口
  - 补通信层测试
- 禁止事项
  - 不要直接改 UI 页面逻辑
  - 不要引入与具体品牌设备强绑定的命名
- 输出给其他 Agent 的接口
  - 标准快照对象
  - 统一读写接口
  - 常见错误分类
- 完成定义
  - 不再在业务代码中直接写寄存器地址
  - 模拟模式可继续运行
  - 测试通过

## 6. Mia 任务包

- 目标
  - 将当前主窗口拆为多区域或多页面结构，但不回退现有功能
- 负责文件
  - `src/rka_desktop/ui/main_window.py`
  - 新增 `src/rka_desktop/ui/recipe_page.py`
  - 新增 `src/rka_desktop/ui/monitor_page.py`
  - 新增 `src/rka_desktop/ui/alarm_page.py`
  - 新增 `src/rka_desktop/ui/settings_page.py`
- 可新增文件
  - `tests/test_ui_smoke.py`
- 本 Sprint 必做
  - 把配方编辑、监控、报警、设置拆到独立页面组件
  - 保持现有连接、启动、停止、导出功能仍可用
  - 增加危险操作二次确认
  - 为后续实验执行引擎预留页面状态入口
- 禁止事项
  - 不要改数据库 schema
  - 不要引入大量业务逻辑到 UI 组件
- 输出给其他 Agent 的接口
  - 页面组件结构
  - 页面切换入口
  - UI 事件信号定义
- 完成定义
  - `main_window.py` 明显瘦身
  - 页面结构清晰
  - 现有功能冒烟可走通

## 7. Ryan 任务包

- 目标
  - 给数据层补上迁移、历史查询和更可持续的写入能力
- 负责文件
  - `src/rka_desktop/db/database.py`
  - `src/rka_desktop/services/export_service.py`
  - 新增 `src/rka_desktop/db/migrations.py`
- 可新增文件
  - `tests/test_migrations.py`
  - `tests/test_history_queries.py`
- 本 Sprint 必做
  - 增加数据库版本或迁移入口
  - 增加历史实验列表查询
  - 增加实验详情查询
  - 增加报警历史查询
  - 梳理 measurements 写入路径，为后续批量写保留入口
- 禁止事项
  - 不要破坏现有表结构兼容
  - 不要把 SQL 到处散落在 UI 层
- 输出给其他 Agent 的接口
  - 历史实验查询 API
  - 报警历史查询 API
  - 导出所需的摘要查询接口
- 完成定义
  - 老库初始化和新库初始化都可工作
  - 历史查询测试通过
  - 导出功能不回退

## 8. Owen 任务包

- 目标
  - 让项目交付文档和打包方向可直接支持内部试装和客户部署
- 负责文件
  - `README.md`
  - `docs/`
  - 新增 `scripts/packaging/` 下脚本
- 本 Sprint 必做
  - 增加安装部署手册
  - 增加串口与依赖环境说明
  - 增加联调 SOP 初稿
  - 增加打包方案说明
  - 增加 release 使用说明
- 禁止事项
  - 不要修改核心业务代码
  - 不要遗漏 README 更新
- 输出给其他 Agent 的接口
  - 环境准备标准文档
  - 打包步骤文档
  - 发布说明模板
- 完成定义
  - 新人可按文档把环境跑起来
  - README 与 docs 一致

## 9. Alex 验收规则

- Leo 验收
  - 是否完成寄存器定义抽象
  - 是否保留模拟模式
  - 是否有通信层测试
- Mia 验收
  - 页面是否完成拆分
  - 现有功能是否回归正常
  - 是否把业务逻辑继续塞进 UI
- Ryan 验收
  - 是否具备迁移入口
  - 是否提供历史查询能力
  - 是否保证现有导出不回退
- Owen 验收
  - 文档是否可执行
  - README 是否同步
  - 打包与发布步骤是否可复用

## 10. 合并门槛

- 分支通过本地测试
- 变更范围与任务包一致
- README 已更新
- 无明显跨模块污染
- 通过 Alex 验收

## 11. 合并顺序建议

1. `Leo`
2. `Ryan`
3. `Mia`
4. `Owen`

原因：
- `Leo` 定义通信接口后，其他模块后续接入更稳
- `Ryan` 的数据查询接口可以尽早稳定
- `Mia` 需要参考 Leo 和 Ryan 的输出形态
- `Owen` 持续跟进，最终在本 Sprint 末尾收口

## 12. Sprint 1 结束标志

- 通信层不再依赖散落的硬编码地址
- UI 形成模块化结构
- 数据层可查询历史实验
- 文档足以支持内部安装与联调
- README 与仓库现状一致
