# RKA-3000 多 Agent 任务拆解 v2.0

- 文档版本：v2.0
- 日期：2026-03-20
- 适用阶段：需求冻结后的结构收敛阶段
- 依据：
  - [需求冻结记录_v1.0.md](/Users/kevin/CodeWorkSpace/Python%20Projects/RKA/docs/%E9%9C%80%E6%B1%82%E5%86%BB%E7%BB%93%E8%AE%B0%E5%BD%95_v1.0.md)
  - [功能边界表_v1.0.md](/Users/kevin/CodeWorkSpace/Python%20Projects/RKA/docs/%E5%8A%9F%E8%83%BD%E8%BE%B9%E7%95%8C%E8%A1%A8_v1.0.md)
  - [多Agent组织与职责_v2.0.md](/Users/kevin/CodeWorkSpace/Python%20Projects/RKA/docs/%E5%A4%9AA%E6%80%BB%E7%BB%84%E7%BB%87%E4%B8%8E%E8%81%8C%E8%B4%A3_v2.0.md)

## 1. 本版目标

本版任务拆解不再继续按“功能铺开”推进，而是按当前冻结范围做三件事：

1. 把当前代码结构收敛到可维护状态
2. 只保留当前版本必须做的功能面
3. 为后续 Windows 交付和正式联调留出清晰接口

## 2. 当前版本边界

### 当前版本必须做

- 完善 UI 界面和代码框架结构
- 配方编辑与执行
- 实时采集
- 设备状态监控（心跳）
- 设备读数
- 参数写入
- 实验记录保存
- 历史查询
- CSV 导出

### 当前版本明确不做

- 联锁闭环
- 正式控制字闭环
- 压力采集
- 在线判据
- 动力学分析
- Excel / PDF / Word 导出
- 设备诊断页
- 校准维护页
- 气体分析仪接入

## 3. 当前阶段的任务原则

- 不再继续扩大 `ui/main_window.py` 的业务编排职责
- 不再为当前版本新增联锁闭环相关能力
- 不再为当前版本增加分析算法和正式报告链路
- 优先做“结构收敛”，再做“功能补齐”
- 所有任务拆分必须围绕当前最小闭环：
  - 配方
  - 读数
  - 参数写入
  - 记录
  - 查询
  - CSV

## 4. Agent 启用清单

### 当前阶段启用

- `Alex`
- `Iris`
- `Leo`
- `Emma`
- `Ryan`
- `Mia`
- `Lily`
- `Owen`
- `Evan`

### 当前阶段暂缓

- `Nina`

说明：

- 当前版本已明确不做动力学分析和在线判据，因此 `Nina` 暂不进入当前主线

## 5. 各 Agent 任务包

### Alex：项目主控与验收

- 当前职责
  - 维护冻结范围
  - 拒绝超范围需求进入当前版本
  - 控制合并顺序
  - 验收 README 与文档是否同步
- 本阶段交付
  - 冻结文档集
  - 路线图
  - 验收记录

### Iris：架构收敛

- 当前职责
  - 设计并冻结 `controllers/` 引入方案
  - 设计并冻结 `hardware/` 引入方案
  - 给出现有文件迁移边界
- 本阶段必做
  - 定义 `experiment_controller.py` 的职责边界
  - 定义 `device_gateway.py` 的职责边界
  - 规定 UI / controllers / services / db / hardware 之间的调用方向
- 不做
  - 不直接接手 UI 页面实现
  - 不直接承接设备协议细节实现

### Leo：硬件通信与参数写入

- 当前职责
  - 保持现有读数与参数写入能力稳定
  - 将 `ModbusRtuClient` 向 `hardware/` 方向抽象
- 本阶段必做
  - 提炼统一读数接口
  - 提炼统一参数写入接口
  - 为去皮指令、温控参数、流量参数补清晰接口
  - 不再继续扩展联锁闭环逻辑
- 不做
  - 不继续追加控制字正式闭环承诺
  - 不接入压力、气体分析仪

### Emma：控制层与业务服务

- 当前职责
  - 把实验主流程从 UI 层迁到控制层
  - 保留当前版本所需的最小流程：
    - 启动
    - 暂停
    - 恢复
    - 安全终止
    - 记录收口
- 本阶段必做
  - 新建 `controllers/experiment_controller.py`
  - 把实验启停、流程推进、结束收口从 `main_window.py` 抽离
  - 删除或降级当前版本不需要的联锁主流程依赖
- 不做
  - 不再扩展联锁闭环
  - 不实现在线判据

### Ryan：数据与历史

- 当前职责
  - 围绕“记录、查询、CSV 导出”收敛数据层
- 本阶段必做
  - 固化实验主记录字段
  - 固化历史查询字段：
    - 实验编号
    - 配方名称
    - 时间范围
    - 实验状态
  - 评估并预留：
    - 实验人员
    - 配方编号
  - 保留原始采样点持久化能力
- 不做
  - 不为当前版本扩展 Excel/PDF/Word
  - 不为当前版本引入复杂审计体系

### Mia：UI 收敛与展示

- 当前职责
  - 把界面收敛到当前冻结范围
  - 把 UI 真正压回展示层
- 本阶段必做
  - 明确首页导航结构
  - 稳定配方页、监控页、设置页、历史页
  - 将报警能力收敛到“当前报警提示”
  - 为控制器层接入预留信号/事件点
- 不做
  - 不继续扩大报警页功能
  - 不新增设备诊断页、校准页
  - 不把控制逻辑加回 UI

### Lily：测试与回归基线

- 当前职责
  - 为重整过程建立回归保护
- 本阶段必做
  - 为 `controllers/experiment_controller.py` 补测试
  - 为参数写入和实验记录闭环补集成测试
  - 调整现有测试，使其与冻结范围一致
  - 标记超范围功能的测试策略
- 不做
  - 不继续扩大联锁闭环测试矩阵

### Owen：文档与冻结基线

- 当前职责
  - 把需求冻结、边界冻结、操作说明同步成一套一致文档
- 本阶段必做
  - 整理当前版本用户口径
  - 补一版面向实验员的最小操作说明
  - 维护文档目录和 README 入口
- 不做
  - 不为当前版本编写正式报告模板

### Evan：Windows 交付准备

- 当前职责
  - 为后续 Windows 打包与部署做准备
- 本阶段必做
  - 明确 Windows 打包路径
  - 评估 PyInstaller 依赖与打包风险
  - 形成 Windows 部署前置检查表
- 不做
  - 不在当前阶段追求正式发布包封版

## 6. 当前阶段推荐顺序

### 第一批

1. `Iris`
2. `Emma`
3. `Leo`
4. `Ryan`

说明：

- 先收敛控制层与硬件层边界
- 再稳定读数、写入、记录三条主线

### 第二批

1. `Mia`
2. `Lily`
3. `Owen`

说明：

- UI 应该在控制器边界稳定后接入
- 测试和文档跟随结构冻结同步完善

### 第三批

1. `Evan`

说明：

- Windows 交付准备应基于稳定结构，不宜过早绑定

## 7. 当前阶段的分支建议

- `codex/iris-controller-architecture`
- `codex/emma-controller-extraction`
- `codex/leo-hardware-gateway`
- `codex/ryan-history-csv-scope`
- `codex/mia-ui-scope-freeze`
- `codex/lily-controller-regression`
- `codex/owen-freeze-docs`
- `codex/evan-windows-packaging-prep`

## 8. 合并门槛

- 不超出 [功能边界表_v1.0.md](/Users/kevin/CodeWorkSpace/Python%20Projects/RKA/docs/%E5%8A%9F%E8%83%BD%E8%BE%B9%E7%95%8C%E8%A1%A8_v1.0.md)
- 不继续扩大 `ui/main_window.py`
- README 已更新
- 至少有对应测试或文档说明
- 不破坏模拟模式
- 不对当前版本承诺正式控制字闭环

## 9. 当前阶段验收标准

完成以下条件，才算当前阶段收口：

1. `controllers/` 已落地
2. 实验主流程不再主要依赖 `main_window.py`
3. 读数、参数写入、实验记录、历史查询、CSV 导出链路稳定
4. UI 页面与冻结范围一致
5. 文档与 README 与冻结口径一致

## 10. 与旧版拆解文档的关系

- 旧版文档 [多Agent并行开发清单_v1.0.md](/Users/kevin/CodeWorkSpace/Python%20Projects/RKA/docs/%E5%A4%9AA%E6%80%BB%E5%B9%B6%E8%A1%8C%E5%BC%80%E5%8F%91%E6%B8%85%E5%8D%95_v1.0.md) 保留，用于追溯已完成工作
- 本版文档作为后续执行基线
- 后续 Sprint 路线图和任务验收应以本版为准
