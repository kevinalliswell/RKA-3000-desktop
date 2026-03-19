# Leo 运行控制字 MVP 验收报告 v1.0

## 1. 验收范围

本次验收覆盖 `codex/leo-run-control-mvp` 分支新增的运行控制字 MVP：

- `0x0060` 运行控制字的位语义约定
- `ModbusRtuClient.issue_run_control()` 下发接口
- 主窗口对 `start / stop / pause / resume / reset` 的动作接入

## 2. 验收结论

验收结果：通过

结论说明：

- 上位机已经具备最小可用的运行控制字下发能力
- 当前实现采用脉冲写方式，下发动作后自动回写 `0x0000`
- 运行控制字位定义已在 `contract_v1` profile 内集中管理，后续可按现场最终表调整

## 3. 验收项

### 3.1 通信层

- 已支持 `start / stop / pause / resume / reset`
- 模拟模式与硬件模式均可走统一入口
- 控制字写入失败会反馈为分类错误

### 3.2 UI 链路

- 启动实验触发 `start`
- 暂停实验触发 `pause`
- 恢复实验触发 `resume`
- 停止实验触发 `stop`
- 报警确认后可恢复场景触发 `reset`

### 3.3 文档与测试

- `contract_v1` profile 文档已补充控制字位语义
- 已补控制字模拟测试、硬件脉冲写测试、profile 测试

## 4. 验证结果

- `python3 -m pytest -q`：`27 passed, 1 skipped`
- `python3 -m compileall src tests`：通过

## 5. 当前边界

- 当前位语义仍为 MVP 约定，不是现场最终冻结表
- `0x0060` 已能下发动作，但 `0x0051` 联锁状态字的位级展示与复位闭环仍未完全展开

## 6. 下一步建议

- 冻结 `0x0060 / 0x0051` 最终位定义
- 增加联锁状态字可视化和复位链路
- 增加运行控制字联调测试用例
