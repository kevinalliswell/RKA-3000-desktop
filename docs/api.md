# 本地 JSON API（接口版本 1）

Python 后端在 `127.0.0.1:<动态端口>` 提供 HTTP/JSON 接口，只供同机的桌面壳（Tauri）和浏览器开发代理使用。

## 通用约定

- **鉴权**：每个请求必须带 `Authorization: Bearer <令牌>`；令牌由桌面壳每次启动随机生成并通过环境变量
  `RKA3000_API_TOKEN` 传给后端。缺失或错误 → `401 unauthorized`。
- **请求体**：`application/json`，上限 1 MB（超出 `413 payload_too_large`）；必须是 JSON 对象。
- **响应**：JSON，`Cache-Control: no-store`，`X-RKA3000-API-Version: 1`。`GET /api/health` 的 `api_version` 字段同值；
  桌面壳在握手时校验版本不匹配即拒绝启动。
- **握手**：后端启动后在 stdout 输出一行 `{"port": <int>, "api_version": 1, "pid": <int>}`；所有日志走 stderr 与日志文件。
- **超时**：服务端连接 10 s；桌面壳请求 20 s。
- **限制**：测量分页 `limit ≤ 5000`；日志返回最后 256 KB；任务历史 50 条；运行曲线缓存 1800 点。

### 错误语义

```json
{ "error": { "code": "invalid_request", "message": "第 2 步: 目标温度须在 0 到 1600 之间", "detail": null } }
```

| HTTP | `code` | 含义 |
| --- | --- | --- |
| 400 | `invalid_request` | 参数、配方、试样参数或设置不合法；JSON 格式错误 |
| 401 | `unauthorized` | 令牌缺失或错误 |
| 404 | `not_found` | 接口、配方、实验或任务不存在 |
| 405 | `method_not_allowed` | 路径存在但方法不支持 |
| 409 | `conflict` | 已有实验在运行；配方被运行中的实验使用；运行中删除实验或手动控制设备；使用上限已锁定；不能归档；未归档实验生成报告；任务过多 |
| 409 | `invalid_state` | 当前运行状态不允许该转换（如无运行中的实验、处置中调气、报警未解除不能恢复） |
| 409 | `preflight_failed` | 启动条件未满足；`detail` 为完整预检结果（`checks[]`） |
| 409 | `confirmation_required` | 带副作用的操作缺少 `"confirm": true`（模式切换、手动配气、提前结束、联锁复位、设备写入、归档、删除实验）。紧急停气例外，不需要确认 |
| 409 | `unsupported` | 当前设备通路不支持（如 PLC 通路的温度程序、去皮） |
| 413 | `payload_too_large` | 请求体超过 1 MB |
| 502 | `device_error` | 设备通信失败，`message` 含驱动诊断 |
| 500 | `internal` | 未预期异常，详情在后端日志 |

## 接口一览

请求体中可选的 `operator` 字段记录为审计中的操作者（本机未启用账号，未经认证）。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务名、版本、`api_version`、仿真模式、设备通路、`run_active`、数据/导出/日志路径、`restart_required`、启动说明 |
| GET / PUT | `/api/settings` | 读取 / 局部更新配置（返回 `config`、`restart_required`、`changed`）；运行中禁止改设备/存储项 |
| GET | `/api/overview` | 首页汇总：运行摘要、最近事件、待核查实验、待确认报警、不可执行配方、各分类数量、使用上限版本 |
| GET | `/api/rules` | 软件报警规则表、现场检查项、处置结束温度、回读过期延时 |
| GET / PUT | `/api/limits` | 当前使用上限策略（各气体设备上限 / 使用上限、锁定原因、历史）/ 应用 `{limits: {CO: 0.6}, reason}` |
| POST | `/api/limits/preview` | `{limits}` → 变更与受影响配方 `{changes[], affected[], next_version}` |
| GET / POST | `/api/recipes` | 列表（含 `runnable`、`summary`）/ 新建 `{name, experiment_type, inert_gas, purge_lpm, purge_seconds, steps[]}`（201） |
| GET / PUT / DELETE | `/api/recipes/{id}` | 详情（steps、`assessment`、`versions`）/ 保存为新版本（需 `reason`）/ 删除 |
| GET | `/api/recipes/{id}/versions` | 版本历史（含每版快照） |
| GET | `/api/recipes/{id}/export` | `{document}`：`rka3000-recipe` v2 文件（v1 文件仍可导入） |
| POST | `/api/recipes/import` | `{document, name?}` 或直接传文件内容（201） |
| GET | `/api/run` | 运行快照（见下） |
| GET | `/api/run/measurements?since=<seq>&limit=` | 增量采样点 `{seq, items[]}`；过期设备的值为 `null` |
| POST | `/api/run/preflight` | `{recipe_id?, sample?, checklist?}` → 预检结果（不改变状态） |
| POST | `/api/run/start` | `{recipe_id, sample{name, initial_mass_g, tfe_pct, feo_pct, operator, particle_size?}, checklist{6 项}, gas_mode?}` → 202 |
| POST | `/api/run/stop` | `{confirm: true, reason?}` → 202，进入惰性处置 |
| POST | `/api/run/emergency` | 紧急停气：立即执行、不需确认、锁存 → 202 |
| POST | `/api/run/pause` · `/resume` | 暂停（仅 set-point 模式）/ 恢复（含 PLC 联锁中断后） |
| POST | `/api/run/ack-alarm` | `{alarm_id?, note}` 确认报警（兼容旧接口） |
| POST | `/api/alarms/{id}/ack` | `{note, operator?}` 确认指定报警；说明必填 |
| POST | `/api/run/reset-interlock` | `{confirm: true}`；需报警已解除、已确认、联锁可软件复位 |
| POST | `/api/run/gas-mode` | `{mode: "auto"|"manual", confirm: bool}`；运行中切换必须确认 |
| POST | `/api/run/manual-gas` | `{flows: {N2: 3, H2: 1.2}, reason, confirm: true}`；返回快照，`last_command` 为三态结果 |
| GET | `/api/devices` · `/api/devices/status` | 设备通路描述 / 实时状态 |
| POST | `/api/devices/connect` | 连接设备 |
| POST | `/api/devices/mfc` · `/temperature` · `/tare` | 空闲手动写入，均需 `confirm: true`，运行中 409 |
| GET | `/api/experiments?limit=&category=&q=` | `{experiments[], counts}`；分类 `running|pending|archived|aborted`；`q` 匹配编号 / 样品 / 配方 |
| GET / PATCH / DELETE | `/api/experiments/{id}` | 详情（含事件、报警、快照）/ 重命名（已归档 409）/ 删除 `{confirm: true}` |
| GET | `/api/experiments/{id}/measurements?limit=&offset=` | 分页测量 |
| GET / PUT | `/api/experiments/{id}/sample-params` | 试样参数；已归档只读 |
| POST | `/api/experiments/{id}/kinetics` | 还原 / 氧化度、指标、模型拟合 |
| GET | `/api/experiments/{id}/review` | 复核项 `{checks[], can_archive, note_required, stats, alarms}` |
| POST | `/api/experiments/{id}/archive` | `{confirm: true, note?}`；有 `warn` 项时备注必填 |
| GET | `/api/experiments/{id}/compare` | 同配方已归档实验的指标对比 |
| POST | `/api/experiments/{id}/report` | 仅已归档；生成带版本号的 Excel 报告任务（202 `{task}`） |
| GET | `/api/reports` | 最近实验及其报告版本 |
| POST | `/api/experiments/{id}/export` | `{kind: measurements_csv | measurements_xlsx | summary_csv}` → 202 `{task}` |
| GET | `/api/alarms?experiment_id=&state=pending|acked&limit=` | 报警记录（含确认人、处理说明） |
| GET | `/api/audit?limit=&experiment_id=&category=&actor=` | 操作审计；分类 `control|safety|config|data|system` |
| POST | `/api/audit/export` | `{experiment_id?, category?}` → 202 `{task}`（CSV） |
| GET | `/api/tasks` · `/api/tasks/{id}` | 任务列表 / 单个任务 |
| POST | `/api/tasks/{id}/cancel` | 请求取消 |
| GET | `/api/log` | `{filename, path, content}` 后端日志尾部 |
| POST | `/api/shutdown` | 202，开始关闭；**仅桌面壳使用，不在 IPC 白名单** |

桌面壳只转发白名单内的路径（`src-tauri/src/main.rs` 的 `allowed`）；`tests/test_ipc_allow_list.py` 检查每个 Python 路由都在白名单中。

## 运行快照 `GET /api/run`

主要字段（完整结构见 `frontend/src/lib/api/types.ts` 的 `RunState`）：

| 字段 | 说明 |
| --- | --- |
| `status` | 见下方状态 |
| `experiment` | 编号 `code`（RKA-YYYY-MMDD-NNN）、样品、操作者、实验类型、惰性气、配方与版本、使用上限版本、吹扫参数 |
| `steps[]` | 各阶段及其状态 `done|active|pending|interrupted|skipped`、类型 `inert|reaction`、起止时间 |
| `step_progress` | 当前阶段是否到温、保持已用 / 总时长 |
| `program_segment` | 温控仪当前运行段（程序模式，读不到为 `null`） |
| `purge` | 处置所需 / 已用秒数、吹扫流量、安全温度、`heating`（`program_last_step|setpoint_written|manual_required|plc_stop`）与说明 |
| `end_reason` | `completed|operator_stop|emergency|alarm|fault|shutdown` |
| `gases[]` | 每种已配置气体：是否允许、设备上限、使用上限（快照）、实测、设定回读、命令值、配方值、状态 |
| `live` | 炉温 / 目标、重量、Δm、还原或氧化度、总流量；过期设备的值为 `null` |
| `last_command` | 最近一次手动调气：`state` 与步骤 `accepted → verified|verify_na|mismatch → applied|reverted` |
| `pending_alarms` | 全部未确认报警（不限当前实验） |
| `stale_devices` | 持续超过 3 个采样周期无有效回读的设备 |
| `allowed` / `blocked` | 由 Python 计算的可用操作与不可用原因 |
| `events[]` | 阶段、命令、报警、安全事件（最新在前） |

### 运行状态

`idle → starting → running`，`running → purging → stopping → completed | stopped | faulted`；
PLC 通路另有 `running ⇄ paused`（仅 set-point 模式）与 `running → interrupted → running`。

- 任何出口都先进入 `purging`（惰性处置），满足吹扫时长且炉温低于安全温度后才进入 `stopping`。
- `stopping`：终态已决定（`pending_terminal`），采集线程正在刷写缓冲测量；只有刷写完成才进入终态。
- 终态不会被迟到的 `stop` 改写；此时请求返回 `409 invalid_state`。
- 终态后实验处于“待核查”，归档前不能开始下一次实验。完整规则见 [experiment-lifecycle.md](experiment-lifecycle.md)。

## 任务 `GET /api/tasks/{id}`

```json
{ "task": { "id": "3f…", "kind": "export", "status": "running", "phase": "写入文件", "progress": 0.6,
            "input": { "kind": "measurements_csv", "experiment_id": 12 },
            "result": null, "error": null, "created_at": "…", "started_at": "…", "finished_at": null } }
```

状态：`queued → running → completed | failed`，`running → cancelling → cancelled`。取消是请求：任务在工作线程
到达安全点并完成清理后才变为 `cancelled`；已完成任务不受迟到取消影响。相同种类、相同实验的重复提交返回仍在
进行的同一任务。导出结果写入用户数据目录 `exports/`，`result.path` 为绝对路径；桌面壳的 `reveal_export` 只允许打开该目录内的文件。

## 配置 `GET /api/settings`

返回 `AppConfig` 全部字段（见 `src/rka_desktop/infrastructure/config.py`）、`restart_required` 与需要重启才生效的键列表。
`PUT` 接受局部对象；未知字段返回 400；`simulation_mode=false` 时必须填写对应通路的串口。

## 兼容与版本

- 接口版本 `API_VERSION`（`src/rka_desktop/__init__.py`）在请求/响应结构发生不兼容变化时递增；桌面壳要求精确匹配。
- 新增字段视为兼容变化；页面忽略未知字段。
- 配方文件 `rka3000-recipe` v2（v1 可导入）、配置文件 `rka3000-config` v1 带版本号，版本不符时报错而不是猜测。
- 0.9 中 `start`、`manual-gas`、`stop`、`ack-alarm` 的请求体与运行快照字段有变化；接口版本仍为 1，因为桌面壳与页面同版本发布，
  没有其他客户端。
