# 设备通路与协议边界

两条设备通路由配置 `device_backend` 选择，均实现应用层 `ExperimentGateway` 端口；仿真模式下使用
`infrastructure/comm/adapters/sim_adapters.py` 与 `ModbusRtuClient(simulation_mode=True)`。

## multi_device：TAIE 温控仪 + Azbil MFC 总线 + 电子天平（默认）

| 设备 | 传输 | 实现 | 用途 |
| --- | --- | --- | --- |
| TAIE 温控仪 | Modbus RTU（默认 19200 bps） | `_vendor/taie_temp`、`adapters/taie_temp_adapter.py` | 读 PV/SV；写 SV（`setpoint` 模式或设备页）；写程序段 `write_program_curve_segment`、选择程序组 `PTN` |
| Azbil MFC ×N | CPL over RS-485（8E1/8N2） | `_vendor/azbil_mfc`、`adapters/azbil_mfc_adapter.py` | 读全部 PV/SP（原始计数 0..50000 换算 L/min）；写 SP1 |
| 电子天平 | ASCII 行（GS-CPA / 龙腾） | `_vendor/balance_serial`、`adapters/balance_adapter.py` | 读稳定重量；去皮 |

- 配方的 N₂/H₂/CO 下发到 `mfc_channels` 中气体名为 `N2`、`H2`、`CO` 的第一个通道（`infrastructure/gateways.py`）；
  未配置的气体若设定 > 0 则报错。
- 温度程序：每个配方步骤映射为两段——升温段（SV=目标温度，时间=|ΔT|/升温速率）与保温段（SV=目标温度，时间=保温）；
  最多 8 段即 4 步；未用段写 0。段时间寄存器单位由 `temp_segment_time_unit`（默认分钟）决定，**需现场核对**。
  驾驱手册未给出远程启动寄存器（`supports_remote_run_control() == False`），程序需在仪表面板启动。
- 读失败在 `MultiDeviceGateway` 内捕获为 `DeviceCommError`，网关保持上次有效值并在 `degraded_devices` 报告；
  运行中同一设备持续降级超过 `degraded_fault_seconds` 则实验故障停止。
- 该通路没有 PLC 报警/联锁/运行控制字，`alarm_word`、`interlock_word` 恒为 0。

## plc_modbus：PLC contract_v1 寄存器映射

`infrastructure/comm/plc/device_map.py`（`contract_v1`）：

| 地址 | 名称 | 访问 |
| --- | --- | --- |
| 0x0001 | 炉温 PV（0.1 ℃） | R |
| 0x0002 / 0x0003 | 炉温 SP / 升温速率 SP | W |
| 0x0010 | 重量 PV（int32，0.001 g） | R |
| 0x0020–0x0022 | N₂/H₂/CO 流量 PV（0.01 L/min） | R |
| 0x0030–0x0032 | N₂/H₂/CO 流量 SP | W |
| 0x0040 | 炉压 PV（0.001 MPa） | R |
| 0x0050 / 0x0051 | 报警字 / 联锁状态字 | R |
| 0x0060 | 运行控制字（start 0x0001、stop 0x0002、pause 0x0004、resume 0x0008、reset 0x0010，脉冲写入后写 0） | R/W |
| 0x0061 | 急停状态 | R |

- 报警位与联锁位定义见 `domain/alarm_rules.py`（`contract_v1`、`legacy_default`）；未定义位按“未定义报警位/联锁位”处理并视为联锁。
- 设定写入失败时回滚到上一组值（`ModbusRtuClient.apply_setpoints`）；运行控制命令写入后读回反馈字做一致性校核。
- 该通路不支持温度程序段，`temperature_mode` 必须为 `setpoint`；也不支持按通道设定 MFC 与天平去皮。

## 副作用边界

| 操作 | 触发方式 | 接口 |
| --- | --- | --- |
| 启动/暂停/恢复/停止实验 | 操作员点击 + 启动/停止确认 | `/api/run/*` |
| 配气模式切换、手动配气 | 操作员 + 二次确认（`confirm: true`） | `/api/run/gas-mode`、`/api/run/manual-gas` |
| 联锁复位 | 操作员 + 确认，且报警已解除、已确认、联锁可软件复位 | `/api/run/reset-interlock` |
| 设备页 MFC/温度/去皮 | 操作员 + 确认；实验运行中拒绝 | `/api/devices/*` |
| 自动轮询 | 只读 | `GET /api/run`、`/api/run/measurements`、`/api/devices/status` |

页面永不自动重放写请求；后端重启或连接恢复后不会补发任何设备命令。
