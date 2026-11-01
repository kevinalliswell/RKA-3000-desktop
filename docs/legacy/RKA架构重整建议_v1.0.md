# RKA 架构重整建议 v1.0

- 文档版本：v1.0
- 日期：2026-03-19
- 编写角色：`Iris` 视角，由 `Alex` 整理
- 目的：在不推翻当前代码的前提下，为 RKA-3000 桌面软件提供一条可渐进落地的架构重整路径

## 1. 文档结论

当前项目不需要“重写”，但需要“止损式重整”。

止损点有三个：

1. 不再继续把控制编排堆进 `ui/main_window.py`
2. 不再让 UI 直接承担业务状态流转责任
3. 不再让设备控制、实验流程、数据持久化在同一层互相穿透

建议路线不是大爆炸重构，而是：

- 先冻结需求与模块边界
- 再引入 `controllers/` 和 `hardware/`
- 最后把现有逻辑按风险最低的顺序迁移出去

## 2. 当前架构现状

### 2.1 当前已有的正向基础

当前代码并非完全无序，已经具备以下可保留基础：

- `core/`
  - 配置、日志、寄存器定义、设备映射、Modbus 客户端
- `db/`
  - SQLite、迁移、查询基础
- `services/`
  - 采集服务、执行引擎、导出服务、配方运行态转换
- `ui/`
  - 页面已经从单体主窗口拆成多个页面
- `tests/`
  - 已形成基本自动化回归

这些基础说明当前项目适合“重整”，不适合“推倒重来”。

### 2.2 当前的主要结构问题

当前最大的问题不在功能，而在责任归属：

- `ui/main_window.py`
  - 同时承担了 UI 容器
  - 页面协调
  - 实验启动与停止
  - 联锁中断与恢复
  - 控制字下发
  - 采样驱动下的状态推进
  - 审计日志触发

这意味着它已经处于“伪控制器”状态，但仍然挂在 UI 层。

直接结果：

- UI 层越来越难维护
- 状态机与设备联动不易单测
- 以后加历史页、诊断页、权限页时会持续放大耦合

## 3. 推荐目标架构

建议收敛为如下分层：

```text
src/rka_desktop/
├── app/                # 应用启动与装配
├── controllers/        # 控制编排层
├── services/           # 业务服务层
├── hardware/           # 硬件抽象层
├── db/                 # 持久化与查询层
├── models/             # 实体、状态、DTO
├── ui/                 # 页面、组件、对话框
├── core/               # 配置、日志、基础设施
└── utils/              # 通用工具
```

## 4. 每层应该负责什么

### 4.1 `app/`

- 负责：
  - 依赖装配
  - 应用启动
  - 主窗口创建
  - 控制器实例注入
- 不负责：
  - 业务判断

### 4.2 `controllers/`

- 负责：
  - UI 事件编排
  - 调度 `services/`、`hardware/`、`db/`
  - 信号发布
  - 将复杂业务流从 `main_window.py` 抽离出来
- 典型对象：
  - `experiment_controller.py`
  - `device_controller.py`
  - `history_controller.py`

### 4.3 `services/`

- 负责：
  - 业务规则
  - 实验执行引擎
  - 报警规则
  - 导出与分析服务
- 典型对象：
  - `experiment_engine.py`
  - `recipe_runtime_service.py`
  - `alarm_evaluator.py`
  - `report_service.py`

### 4.4 `hardware/`

- 负责：
  - 多设备抽象
  - 设备读写
  - 诊断与健康检查
  - 模拟模式与实机模式
- 典型对象：
  - `device_gateway.py`
  - `temperature_controller.py`
  - `flow_controller.py`
  - `weight_sensor.py`

### 4.5 `db/`

- 负责：
  - 数据库 schema
  - 迁移
  - repository / query 接口
  - 审计和历史检索
- 不负责：
  - UI 展示格式
  - 实验状态判断

### 4.6 `models/`

- 负责：
  - 实体
  - 状态枚举
  - 数据传输对象
  - 快照对象

### 4.7 `ui/`

- 负责：
  - 页面和组件
  - 用户输入
  - 信号连接
  - 结果展示
- 不负责：
  - 控制流程决策
  - 设备联动判断

## 5. 现有代码与目标架构的映射关系

### 当前保留不动或轻改

- `src/rka_desktop/core/config.py`
- `src/rka_desktop/core/registers.py`
- `src/rka_desktop/core/device_map.py`
- `src/rka_desktop/db/database.py`
- `src/rka_desktop/db/migrations.py`
- `src/rka_desktop/models/entities.py`
- `src/rka_desktop/services/export_service.py`

### 需要迁移或拆分

- `src/rka_desktop/ui/main_window.py`
  - 需要拆成：
    - UI 容器职责保留在 `ui/`
    - 控制编排迁入 `controllers/`
- `src/rka_desktop/core/modbus_client.py`
  - 当前可继续保留
  - 但后续应成为 `hardware/` 的底层通信客户端，而不是唯一设备抽象
- `src/rka_desktop/services/acquisition_service.py`
  - 后续需要明确：
    - 它是“采样线程”
    - 不是“业务控制器”
- `src/rka_desktop/services/experiment_engine.py`
  - 当前保留为业务内核
  - 但外部编排应迁出 UI

## 6. 当前最值得优先处理的架构债

### 6.1 `main_window.py` 职责过重

建议优先做的不是再拆页面，而是把以下逻辑迁出：

- 启动实验流程
- 暂停 / 恢复 / 停止
- 联锁中断与恢复判断
- 控制字与反馈字校核触发
- 实验收口与状态持久化

这些逻辑应该沉到 `experiment_controller.py`。

### 6.2 缺少明确的控制编排层

当前项目最缺的是 `controllers/`。

如果不尽快补上，后续新增：

- 历史查询页
- 设备诊断页
- 校准页
- 权限页

都会继续在 UI 层堆流程。

### 6.3 `hardware/` 层尚未成型

现在的 `ModbusRtuClient` 已经比早期版本好很多，但它仍然是“协议客户端”，还不是“设备层”。

后续如果确认要做正式联调，建议在它之上补一层：

- 设备网关
- 多设备对象
- 统一状态对象

### 6.4 导出与分析还没有真正分层

当前 `export_service.py` 已经是个好的开端，但：

- 正式报告
- 数据分析
- 动力学计算

不应继续直接往 `export_service.py` 里累加。

后续应拆出：

- `report_service.py`
- `analysis_service.py`

## 7. 分阶段重整建议

### 阶段 1：冻结边界，不继续恶化

- 目标
  - 立即停止在 `main_window.py` 继续堆控制流程
- 动作
  - 规定所有新业务流程优先写到 `controllers/` 预留层
  - `ui/` 只保留界面交互和信号接线
  - 新增模块时先补接口，不急着一次重构完

### 阶段 2：引入 `controllers/`

- 目标
  - 把实验主流程从 UI 层抽出来
- 建议新增
  - `src/rka_desktop/controllers/experiment_controller.py`
- 首批迁移内容
  - 启动实验
  - 暂停/恢复/停止
  - 联锁中断/恢复
  - 完成/故障收口

### 阶段 3：引入 `hardware/`

- 目标
  - 把“协议客户端”升级成“设备抽象层”
- 建议新增
  - `src/rka_desktop/hardware/device_gateway.py`
  - `src/rka_desktop/hardware/device_types.py`
- 首批迁移内容
  - 温度、流量、压力、重量读写封装
  - 联锁状态快照聚合

### 阶段 4：数据与分析分流

- 目标
  - 让数据查询、导出、分析各自稳定
- 建议方向
  - `db/queries.py` 或 `db/repository/`
  - `services/report_service.py`
  - `services/analysis_service.py`

### 阶段 5：UI 回归为展示层

- 目标
  - `main_window.py` 只保留：
    - 页面容器
    - 控制器注入
    - 信号连接
- 验收标准
  - 业务收口不再依赖 UI 层逻辑

## 8. 推荐的首批重整任务

如果需求冻结后开始重整，建议按这个顺序：

1. 新建 `controllers/experiment_controller.py`
2. 把 `main_window.py` 中实验启停和联锁恢复迁过去
3. 为控制器补测试
4. 新建 `hardware/device_gateway.py`
5. 把 `ModbusRtuClient` 作为 `hardware/` 底层能力接入
6. 再考虑历史查询页、设备诊断页、报告服务拆分

## 9. 不建议现在做的事

- 不建议现在整体改目录并一次性大搬家
- 不建议现在引入复杂插件式架构
- 不建议现在同时重构 UI、通信、数据库三条主线
- 不建议在需求未冻结前继续扩大算法和报告范围

## 10. 对后续 Sprint 的影响

如果采用本建议，后续 Sprint 应调整为：

### Sprint A

- 需求冻结
- 架构边界冻结
- 明确 MVP 范围

### Sprint B

- `controllers/` 引入
- 实验流程从 UI 层迁出

### Sprint C

- `hardware/` 引入
- 多设备与正式联调抽象

### Sprint D

- 历史、报告、诊断、交付收口

## 11. 最终建议

当前最正确的动作不是继续铺功能，而是：

1. 先用 [需求澄清清单_v1.0.md](/Users/kevin/CodeWorkSpace/Python%20Projects/RKA/docs/需求澄清清单_v1.0.md) 冻结需求
2. 再以本文件冻结架构方向
3. 然后重写 Sprint 2 后半段和 Sprint 3 的任务拆解

一句话总结：

当前项目已经具备“可运行原型”的基础，但要变成“可联调、可维护、可交付”的工业仪器软件，下一步必须补上控制层和硬件抽象层，不能继续让 UI 层承担系统编排中心。
