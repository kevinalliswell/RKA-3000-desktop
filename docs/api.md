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
| 409 | `conflict` | 已有实验在运行；配方被运行中的实验使用；运行中删除实验或手动控制设备；任务过多 |
| 409 | `invalid_state` | 当前运行状态不允许该转换（如无运行中的实验、报警未解除不能恢复） |
| 409 | `confirmation_required` | 带副作用的操作缺少 `"confirm": true`（模式切换、手动配气、联锁复位、设备写入、删除实验） |
| 409 | `unsupported` | 当前设备通路不支持（如 PLC 通路的温度程序、去皮） |
| 413 | `payload_too_large` | 请求体超过 1 MB |
| 502 | `device_error` | 设备通信失败，`message` 含驱动诊断 |
| 500 | `internal` | 未预期异常，详情在后端日志 |

## 接口一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 服务名、版本、`api_version`、仿真模式、设备通路、`run_active`、数据/导出/日志路径、`restart_required` |
| GET / PUT | `/api/settings` | 读取 / 局部更新配置（返回 `config`、`restart_required`、`changed`）；运行中禁止改设备/存储项 |
| GET / POST | `/api/recipes` | 列表 / 新建 `{name, steps[]}`（201） |
| GET / PUT / DELETE | `/api/recipes/{id}` | 详情（含 steps）/ 更新 / 删除 |
| GET | `/api/recipes/{id}/export` | `{document}`：`rka3000-recipe` v1 文件 |
| POST | `/api/recipes/import` | `{document, name?}` 或直接传文件内容（201） |
| GET | `/api/run` | 运行快照（见下） |
| GET | `/api/run/measurements?since=<seq>&limit=` | 增量采样点 `{seq, items[]}` |
| POST | `/api/run/start` | `{recipe_id, gas_mode?}` → 202 快照 |
| POST | `/api/run/pause` · `/resume` · `/stop` | 暂停 / 恢复 / 停止（停止返回 202，状态为 `stopping`） |
| POST | `/api/run/ack-alarm` | 确认最近一条待处理报警 |
| POST | `/api/run/reset-interlock` | `{confirm: true}`；需报警已解除、已确认、联锁可软件复位 |
| POST | `/api/run/gas-mode` | `{mode: "auto"|"manual", confirm: bool}`；运行中切换必须确认 |
| POST | `/api/run/manual-gas` | `{n2_lpm, h2_lpm, co_lpm, confirm: true}`；仅手动模式 |
| GET | `/api/devices` · `/api/devices/status` | 设备通路描述 / 实时状态（温控 PV、各 MFC 流量与设定、重量、降级设备） |
| POST | `/api/devices/connect` | 连接设备 |
| POST | `/api/devices/mfc` · `/temperature` · `/tare` | 空闲手动写入，均需 `confirm: true`，运行中 409 |
| GET | `/api/experiments?limit=` | 历史实验列表 |
| GET / PATCH / DELETE | `/api/experiments/{id}` | 详情（含 summary、measurement_count）/ 重命名 `{name}` / 删除 `{confirm: true}` |
| GET | `/api/experiments/{id}/measurements?limit=&offset=` | 分页测量 `{items, total, limit, offset}` |
| GET / PUT | `/api/experiments/{id}/sample-params` | 试样参数 m₀ / TFe / FeO |
| POST | `/api/experiments/{id}/kinetics` | 计算还原度；体为空则用已保存参数 |
| POST | `/api/experiments/{id}/report` | 生成 Excel 报告任务（202 `{task}`） |
| POST | `/api/experiments/{id}/export` | `{kind: measurements_csv | measurements_xlsx | summary_csv}` → 202 `{task}` |
| GET | `/api/alarms?experiment_id=&limit=` | 报警历史 |
| GET | `/api/audit?limit=` | 操作审计 |
| GET | `/api/tasks` · `/api/tasks/{id}` | 任务列表 / 单个任务 |
| POST | `/api/tasks/{id}/cancel` | 请求取消 |
| GET | `/api/log` | `{filename, path, content}` 后端日志尾部 |
| POST | `/api/shutdown` | 202，开始关闭；**仅桌面壳使用，不在 IPC 白名单** |

## 运行快照 `GET /api/run`

```json
{
  "seq": 128, "status": "running", "pending_terminal": null, "engine_state": "RUNNING",
  "run_id": "12-1793500000", "experiment_id": 12, "recipe_id": 3, "recipe_name": "标准流程",
  "started_at": "2026-10-31T20:00:00", "finished_at": null, "error": null,
  "current_step_no": 1, "total_steps": 2, "current_step": { "step_no": 1, "target_temp_c": 900.0, "...": "..." },
  "status_text": "第 1 步保温中，剩余 540s", "setpoints_text": "目标温度 900.0℃ | 升温速率 10.0℃/min | N2/H2/CO 8.0/1.0/0.8",
  "gas_mode": "auto", "temperature_mode": "program",
  "temperature_program": { "group": 0, "segments": 4, "time_unit": "min", "remote_start": false, "message": "…" },
  "manual_gas": null,
  "alarm": { "word": 0, "text": "正常", "active": [] },
  "interlock": { "word": 0, "text": "无联锁", "estop": false, "resettable": false, "active": [] },
  "control_feedback": { "word": 0, "estop_status": 0, "consistent": true, "message": "控制反馈: 不适用" },
  "pending_alarms": [], "degraded_devices": [],
  "latest": { "temperature_c": 899.6, "weight_g": 98.12, "n2_lpm": 8.0, "h2_lpm": 1.0, "co_lpm": 0.8, "...": "..." },
  "allowed": { "start": false, "pause": true, "resume": false, "stop": true, "ack_alarm": false,
               "reset_interlock": false, "set_gas_mode": true, "manual_gas": false },
  "connected": true, "messages": [ { "at": "…", "text": "实验开始，ID=12，配方=标准流程" } ]
}
```

### 运行状态

`idle → starting → running ⇄ paused`，`running → interrupted → running`，
`running | paused | interrupted → stopping → stopped | completed | faulted`。

- `stopping`：终态已决定（`pending_terminal`），采集线程正在刷写缓冲测量；只有刷写完成才进入终态。
- 终态不会被迟到的 `stop`/`pause` 改写；此时这些请求返回 `409 invalid_state`。
- `allowed` 由 Python 按业务规则计算，页面据此启用按钮，不自行判定。
- `engine_state` 保留迁移前的执行引擎状态值（`RUNNING/PAUSED/INTERRUPTED/STOPPED/COMPLETED/FAULTED`），与数据库 `experiments.status` 一致。

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
- 配方文件 `rka3000-recipe` v1、配置文件 `rka3000-config` v1 带版本号，版本不符时报错而不是猜测。
