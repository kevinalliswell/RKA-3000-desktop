# RKA MVC 分层说明 v1.0

- 文档版本：v1.0
- 日期：2026-03-20
- 负责人：`Iris / Alex`
- 适用范围：当前冻结需求下的桌面端架构分层说明

## 1. 当前目标

当前目标不是重写项目，而是在现有代码基础上，把主流程逐步收敛到更清晰的 MVC 结构。

当前重点：

1. 不再继续把业务流程堆进 `MainWindow`
2. 让界面层只负责展示和交互触发
3. 让控制层负责流程编排和状态决策
4. 让数据与设备访问留在服务层、数据库层、硬件层

## 2. 当前分层

### 2.1 View

职责：

- 展示界面
- 收集用户输入
- 弹出确认框、文件对话框
- 接收 Controller 输出并刷新页面

当前主要文件：

1. `src/rka_desktop/ui/main_window.py`
2. `src/rka_desktop/ui/recipe_page.py`
3. `src/rka_desktop/ui/monitor_page.py`
4. `src/rka_desktop/ui/history_page.py`
5. `src/rka_desktop/ui/alarm_page.py`
6. `src/rka_desktop/ui/settings_page.py`

### 2.2 Controller

职责：

- 编排业务流程
- 决定状态流转
- 把数据库、设备访问、服务输出整理成 View 可消费的状态
- 不直接操作控件

当前主要文件：

1. `src/rka_desktop/controllers/experiment_controller.py`
2. `src/rka_desktop/controllers/recipe_controller.py`
3. `src/rka_desktop/controllers/history_export_controller.py`

### 2.3 Model / Service / Repository / Hardware

职责：

- 数据持久化
- 设备访问
- 实验规则执行
- 采集、导出等通用服务

当前主要文件：

1. `src/rka_desktop/db/database.py`
2. `src/rka_desktop/hardware/device_gateway.py`
3. `src/rka_desktop/services/experiment_engine.py`
4. `src/rka_desktop/services/acquisition_service.py`
5. `src/rka_desktop/services/export_service.py`
6. `src/rka_desktop/services/recipe_runtime_service.py`

## 3. 当前 Controller 边界

### 3.1 ExperimentController

负责：

1. 实验启动、暂停、恢复、停止
2. 步骤推进与状态机衔接
3. 报警确认后的恢复条件判断
4. 联锁/报警快照驱动下的实验状态收口
5. 控制反馈一致性判断
6. 输出运行态 ViewState

### 3.2 RecipeController

负责：

1. 配方列表加载
2. 配方详情加载
3. 配方保存
4. 配方更新
5. 配方基础校验
6. 输出配方 ViewState

### 3.3 HistoryExportController

负责：

1. 历史实验列表加载
2. 历史实验摘要生成
3. 导出目标实验解析
4. CSV / Excel 导出编排
5. 输出历史页 ViewState

## 4. MainWindow 当前允许保留的职责

当前 `MainWindow` 允许保留：

1. Qt 信号绑定
2. 页面切换
3. 确认弹窗
4. 文件保存对话框
5. Controller 结果分发到各页面
6. 采集线程启动与停止

当前 `MainWindow` 不应再继续扩大的职责：

1. 实验业务规则判断
2. 配方 CRUD 业务
3. 历史查询与导出业务
4. 设备控制语义判断
5. 报警恢复条件决策

## 5. 当前目录理解

建议按下面方式理解当前项目：

1. `ui/`
   - View
2. `controllers/`
   - MVC 中的 Controller
3. `db/`
   - 数据访问层
4. `hardware/`
   - 设备接入层
5. `services/`
   - 通用业务服务和执行引擎
6. `models/`
   - 数据结构定义

## 6. 当前不是最终形态的地方

虽然已经明显收敛，但当前还不是最终理想结构。

还存在这些可继续优化点：

1. `MainWindow` 仍承担 Controller 结果分发职责
2. 配方页面输入解析还在 `RecipePage`
3. 历史页当前是最小查询页，还没有更细的筛选条件
4. `DatabaseManager` 仍是直接数据库访问入口，后续可继续细化 repository 边界

## 7. 后续建议

后续建议按这个顺序继续：

1. 继续减少 `MainWindow` 中的结果分发代码
2. 把页面输入校验逐步收敛到 Controller
3. 视需要引入更细的 repository 层
4. Windows 交付前冻结目录与分层口径

## 8. 当前结论

当前项目已经进入“可演进的 MVC 收敛阶段”。

这意味着：

1. 可以继续开发
2. 但必须守住 Controller 边界
3. 任何新功能都不应再绕过 Controller 直接写进 UI
