# Leo 正式映射接入验收报告 v1.0

## 1. 验收范围

本次验收覆盖 `codex/leo-formal-mapping` 分支新增的正式映射接入能力：

- `contract_v1` 寄存器映射 profile
- `contract_v1` 报警位/等级/联锁 profile
- `mapping_profile` 配置接入
- `ModbusRtuClient` 改为基于 `DeviceMap` 驱动

## 2. 验收结论

验收结果：通过

结论说明：

- 通信层已经从“固定寄存器常量”演进为“profile 驱动”
- 主线默认启用 `contract_v1`
- 报警位定义已经和当前合同版规格对齐到统一 profile
- 后续若现场冻结正式 PLC/控制器表，可在 profile 层扩展而不必改业务流程代码

## 3. 验收项

### 3.1 寄存器映射

- 已支持 `temperature / weight / pressure / flow / alarm / interlock / run_control / estop` 采集映射
- 已支持 `temperature / ramp_rate / gas flow` 设定点映射

### 3.2 配置接入

- `Settings.mapping_profile` 已接入
- `.env.example` 已提供 `MAPPING_PROFILE=contract_v1`
- 设置页可显示当前生效的 profile

### 3.3 报警定义

- 已支持按 profile 解码报警位
- 已支持按 profile 判断是否联锁
- 已支持未知报警位兜底

### 3.4 测试覆盖

- 新增 `device_map` 测试
- 更新 `alarm_rules` 测试
- 更新 `modbus_client` 读写测试

## 4. 验证结果

- `python3 -m pytest -q`：`25 passed, 1 skipped`
- `python3 -m compileall src tests`：通过

## 5. 主要风险

- 当前 `contract_v1` 仍基于合同规格和硬件规格书整理，不是现场 PLC 最终冻结表
- `0x0051` 联锁状态字和 `0x0060` 运行控制字目前仅接入寄存器层，位语义尚未落成完整动作
- 额外气路 `0x0023~0x0025 / 0x0033~0x0035` 仍待正式定义

## 6. 下一步建议

- 冻结 `0x0051` 和 `0x0060` 的位语义
- 补运行控制字下发与复位动作
- 增加正式 profile 的联调测试矩阵
