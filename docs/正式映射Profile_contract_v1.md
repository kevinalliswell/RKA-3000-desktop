# 正式映射 Profile `contract_v1`

## 1. 说明

本 profile 基于 [硬件规格书_v1.0.md](/Users/kevin/CodeWorkSpace/Python%20Projects/RKA/docs/硬件规格书_v1.0.md) 中 `4.3 建议寄存器映射` 和 `5. I/O 与联锁要求` 整理，用于当前主线的正式映射接入。

当前目标：

- 为 `ModbusRtuClient` 提供可切换的寄存器映射 profile
- 为报警系统提供统一的报警位、等级和联锁属性定义
- 为后续现场正式表冻结保留切换入口

## 2. 寄存器映射

### 2.1 采集寄存器

| 地址(Hex) | 字段 | 类型 | 缩放 |
|---|---|---|---|
| `0x0001` | `temperature_c` | `uint16` | `0.1 ℃` |
| `0x0010~0x0011` | `weight_g` | `int32` | `0.001 g` |
| `0x0020` | `n2_lpm` | `uint16` | `0.01 L/min` |
| `0x0021` | `h2_lpm` | `uint16` | `0.01 L/min` |
| `0x0022` | `co_lpm` | `uint16` | `0.01 L/min` |
| `0x0040` | `pressure_mpa` | `uint16` | `0.001 MPa` |
| `0x0050` | `alarm_word` | `uint16(bit)` | `1` |
| `0x0051` | `interlock_word` | `uint16(bit)` | `1` |
| `0x0060` | `run_control_word` | `uint16(bit)` | `1` |
| `0x0061` | `estop_status` | `uint16` | `1` |

### 2.2 设定寄存器

| 地址(Hex) | 字段 | 类型 | 缩放 |
|---|---|---|---|
| `0x0002` | `temperature_setpoint_c` | `uint16` | `0.1 ℃` |
| `0x0003` | `ramp_rate_setpoint_cpm` | `uint16` | `0.1 ℃/min` |
| `0x0030` | `n2_setpoint_lpm` | `uint16` | `0.01 L/min` |
| `0x0031` | `h2_setpoint_lpm` | `uint16` | `0.01 L/min` |
| `0x0032` | `co_setpoint_lpm` | `uint16` | `0.01 L/min` |

## 3. 报警位定义

| Bit Mask | 代码 | 等级 | 联锁 | 描述 |
|---|---|---|---|---|
| `0x0001` | `ALM-0001` | `CRITICAL` | 是 | 超温报警 |
| `0x0002` | `ALM-0002` | `CRITICAL` | 是 | 超压报警 |
| `0x0004` | `ALM-0004` | `CRITICAL` | 是 | 可燃气体报警 |
| `0x0008` | `ALM-0008` | `HIGH` | 是 | 风冷异常 |
| `0x0010` | `ALM-0010` | `CRITICAL` | 是 | 急停触发 |
| `0x0020` | `ALM-0020` | `HIGH` | 是 | 热电偶/温度采集异常 |
| `0x0040` | `ALM-0040` | `MEDIUM` | 否 | 称重信号异常 |
| `0x0080` | `ALM-0080` | `MEDIUM` | 否 | 通信质量告警 |

未定义位：

- 自动生成 `ALM-XXXX` 代码
- 默认等级为 `HIGH`
- 默认按联锁型报警处理

## 4. 当前接入范围

- `Settings.mapping_profile` 默认使用 `contract_v1`
- `ModbusRtuClient` 通过 `DeviceMap` 读取/写入寄存器
- `MainWindow` 按 `mapping_profile` 解码报警位并判断是否联锁

## 5. 后续待冻结项

- `0x0023~0x0025` 与 `0x0033~0x0035` 的额外气路定义
- `0x0060` 运行控制字的位语义
- `0x0051` 联锁状态字的位语义
- 各报警位与现场 PLC/控制器最终定义的一致性
