# Sprint 2 采集批量落库验收报告 v1.0

## 1. 验收范围

- 分支：`codex/sprint2-batch-acquisition`
- 验收角色：`Alex`
- 验收目标：确认采集线程已切换到批量落库模式，同时保持 UI 实时刷新与执行引擎处理链路不回退

## 2. 本次交付

- 采集线程内部新增测点缓冲区
- 达到 `acquisition_batch_size` 时批量调用 `insert_measurements()`
- 采集线程退出时自动 flush 剩余测点
- 主窗口不再逐点写库，只保留 UI 刷新和状态处理
- 设置项新增 `acquisition_batch_size`

## 3. 验收结论

结论：通过。

当前实现满足 Sprint 2 MVP 对采集链路的目标，已经把数据库写入从主线程逐点同步提交切换为采集线程批量提交，降低了主线程压力。

## 4. 验收要点

- `AcquisitionWorker` 已持有 `DatabaseManager`，不再只做快照转发
- `AcquisitionWorker._buffer_measurement()` 会在达到批量阈值后触发批量落库
- `AcquisitionWorker._flush_pending_measurements()` 可保证停止采集时剩余数据不会遗失
- `MainWindow._on_snapshot()` 不再逐点调用 `db.insert_measurement()`

## 5. 验证结果

- `source .venv/bin/activate && python -m pytest -q`
  - 结果：`40 passed`
- `source .venv/bin/activate && python -m compileall src tests`
  - 结果：通过

## 6. 风险与后续建议

- 当前批量触发条件以“条数阈值”为主，后续可考虑增加“最长滞留时间”策略
- 实机联调阶段建议重点观察：
  - 高采样频率下的 UI 流畅度
  - 停止实验瞬间的尾批 flush 完整性
  - SQLite 文件体积增长与导出性能
