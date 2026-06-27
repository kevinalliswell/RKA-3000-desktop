# RKA 多设备通讯层 + 发布自动化 — 设计文档

- 日期：2026-06-27
- 状态：已确认（待实现）
- 分支：`feat/multi-device-comm-layer`
- 目标仓库：`kevinalliswell/RKA-3000-desktop`（PR 入 `main`）

## 1. 背景

RKA 当前把被测对象建模为**单一集成 Modbus 设备**：一个 `core/modbus_client.ModbusRtuClient`
读出单个 `DeviceSnapshot`（温度 + 重量 + 压力 + N2/H2/CO 流量）。它没有「多台独立设备」的概念。

姊妹项目 TMH-desktop 已经把通讯做成真正的多设备运行时（`device_manager` / `base_device` /
`multi_mfc_client` / `temp_client` / `balance_client` / `data_handler`）。本次工作把这一思路引入 RKA，
但**协议实现改为复用三个独立的、已在真机联调过的协议库**：

| 设备 | 数量 | 参考仓库 | 协议 | 依赖 | License | 钉定 commit |
|------|------|----------|------|------|---------|-------------|
| MFC（质量流量计） | 6 | `kevinalliswell/azbil-mfc`（`azbil_mfc`） | Azbil CPL over RS-485（非 Modbus），单总线多地址 | pyserial | MIT | `83ddc491` |
| 温控仪 | 1 | `kevinalliswell/taie-temp-controller`（`taie_temp_controller`） | Modbus RTU | pyserial | Apache-2.0 | `ab18b921` |
| 电子天平 | 1 | `kevinalliswell/balance-serial`（`balance_serial`） | 串口 ASCII（`gs_cpa` / `longteng`） | pyserial | 无 LICENSE 文件 | `496b7b76` |

三个库的**核心驱动都只依赖 `pyserial`**（RKA 既有依赖），不引入新依赖，也不带入各仓库的
FastAPI/dashboard 等可选组件。

## 2. 范围（contained scope）

**做：**
- 在 RKA 新增**仿真优先**的多设备通讯层（6× MFC + 温控 + 天平）。
- 协议实现采用 **vendoring（按 commit 钉定复制核心模块）** + RKA 侧适配器隔离。
- 作为现有采集/快照流程的**可插拔数据源**接入（不改采集线程逻辑）。
- 落地 CHANGELOG、单一版本源、升级版 release 工作流。

**不做（留待后续 PR）：**
- 重构 DB schema、重画 UI 页面、改造实验引擎。
- 真机联调、TMH 式指数退避重连。
- 现有单设备 `ModbusRtuClient` 流程保持不动。

## 3. 架构

### 3.1 集成缝

`services/acquisition_service.AcquisitionWorker` 仅调用数据源的
`read_snapshot() -> DeviceSnapshot`（外加生命周期 `connect()` / `close()`）。
因此引入一个窄协议 `SnapshotSource`：

```python
class SnapshotSource(Protocol):
    def connect(self) -> bool: ...
    def close(self) -> None: ...
    def read_snapshot(self) -> DeviceSnapshot: ...
```

- 既有 `ModbusRtuClient` 已天然满足该协议（无需改动其行为）。
- 新 `MultiDeviceGateway` 同样实现该协议，从而**零改动**替换数据源。
- `AcquisitionWorker.__init__` 的类型标注由 `ModbusRtuClient` 放宽为 `SnapshotSource`
  （唯一改动；运行行为不变）。

### 3.2 目录结构

```
src/rka_desktop/comm/                     # 新增包，与旧 core/ 并存（不动 core/）
├── __init__.py
├── _vendor/                              # 厂商驱动原样 vendoring（仅核心模块）
│   ├── __init__.py
│   ├── VENDOR.md                         # 来源仓库 + commit SHA + license + 裁剪记录
│   ├── azbil_mfc/                        # bus / client / protocol / constants /
│   │                                     #   registers / exceptions / device_catalog
│   ├── taie_temp/                        # modbus_rtu / controller / register_addresses
│   └── balance_serial/                   # client / factory / models / protocols/*
│
├── ports.py                              # RKA 侧窄接口（隔离上游 API 变化）
├── adapters/
│   ├── __init__.py
│   ├── azbil_mfc_adapter.py              # real：包装 MQVBusManager；sim：6 通道合成
│   ├── taie_temp_adapter.py              # real：包装 TaieTemperatureController；sim
│   └── balance_adapter.py               # real：包装 BalanceClient；sim
├── multi_device_gateway.py               # 聚合三类设备 → DeviceSnapshot (+ MultiDeviceSnapshot)
└── config.py                             # 每设备串口/地址/量程配置（扩展 core/config）
```

### 3.3 组件职责

- **`_vendor/*`**：从三仓库按 commit 钉定复制的核心驱动，**不改逻辑**，仅：
  - 裁剪未使用模块（azbil 的 dashboard/mixer/recipe/scheduler/safety；taie 的 api/polling/acquisition；
    balance 的 examples），并精简各自 `__init__.py` 的导出到核心 API。
  - `VENDOR.md` 记录每个库的源仓库 URL、commit SHA、license、保留/裁剪文件清单，便于日后同步上游。
- **`ports.py`**：RKA 自己的窄接口，隔离上游 API：
  - `TemperaturePort`: `read_pv() -> float`、`read_sv() -> float`、`write_sv(v: float) -> None`
  - `MfcBusPort`: `read_all_pv() -> dict[int, float]`、`read_pv(addr) -> float`、`set_flow(addr, lpm) -> None`
  - `BalancePort`: `read_weight() -> float | None`、`tare() -> bool`
- **adapters（real + sim 两实现）**：
  - `real`：包装对应 vendored 驱动（开串口、轮询、单位换算）。
  - `sim`：产生**确定性合成数据**（温度对 setpoint 一阶逼近、MFC PV 跟随 SP、天平随实验缓变），
    不触串口、可在 CI 跑。通过 `simulation_mode` 标志切换，沿用 RKA 既有约定。
- **`MultiDeviceGateway`**：持有 6 MFC + 1 温控 + 1 天平的 port。`read_snapshot()` 聚合为
  `DeviceSnapshot`（向后兼容映射，见 §4），并可选返回富快照 `MultiDeviceSnapshot`
  （9 温度通道 + 6 流量 + 重量）供未来 UI 使用。报警/联锁字本期置 0 或由简单阈值规则生成。

## 4. 数据模型与映射

`models/entities.py` **新增** `MultiDeviceSnapshot`（dataclass，纯增量，不改 `DeviceSnapshot`）：

```python
@dataclass(frozen=True)
class MultiDeviceSnapshot:
    temperatures_c: tuple[float, ...]      # 温控仪多通道（本期主用 1 路 PV，预留 9 路）
    mfc_flows_lpm: dict[int, float]        # {地址: 流量}，6 路
    mfc_setpoints_lpm: dict[int, float]
    weight_g: float | None
    degraded_devices: tuple[str, ...]      # 读取失败/stale 的设备标识
```

**向 legacy `DeviceSnapshot` 的兼容映射**（保证旧采集/落库/UI 不变）：
- `temperature_c` ← 温控仪 PV
- `weight_g` ← 天平重量
- `n2_lpm` / `h2_lpm` / `co_lpm` ← 6 路 MFC 中按**气体类型自动匹配**的 N2 / H2 / CO 通道
  （依据 azbil `device_catalog` 读到的 gas type；匹配不到时回退到固定地址顺序，并记一条 warning）。
- `pressure_mpa` ← 本期置 0（无压力设备）。
- `alarm_word` / `interlock_word` / `run_control_word` / `estop_status` ← 本期置 0。

## 5. 错误处理

- 每个 real adapter 捕获驱动异常（`CPLTimeoutError` / `ModbusTimeoutError` / 串口断开等），
  统一转为 RKA 的 `comm.DeviceCommError`。
- **单设备读失败不拖垮整帧**：该通道返回上次有效值并标记 stale，`MultiDeviceGateway`
  把该设备记入 `degraded_devices`，整帧仍返回。
- sim adapter **永不抛通讯异常**，保证 CI 稳定。
- 本期不引入指数退避重连（留待真机 PR）；`connect()` 失败给出清晰的设备级报错。

## 6. 测试（仿真优先，全部离线）

- **adapter sim**：单测覆盖 PV 跟随 SP、tare、量程换算。
- **vendored 协议纯逻辑**：移植/保留上游纯协议单测（帧构造、Modbus CRC16、CPL checksum、响应解析），无需硬件。
- **`MultiDeviceGateway`**：单测验证聚合映射、N2/H2/CO 通道选择、degraded 行为。
- **集成**：`AcquisitionWorker` + sim gateway 跑 N 帧并落库（`QT_QPA_PLATFORM=offscreen`）。
- 复用 RKA 现有 pytest 配置（`pythonpath=["src"]`、`testpaths=["tests"]`）。

## 7. 版本与发布自动化

- **单一版本源**：`pyproject.toml` 改为 `dynamic = ["version"]` +
  `[tool.setuptools.dynamic] version = {attr = "rka_desktop.__version__"}`（与 azbil-mfc 同款）。
  `src/rka_desktop/__init__.py` 的 `__version__` 成为唯一真源。
- **CI 一致性校验**：新增步骤断言 `rka_desktop.__version__`、git tag（release 时）、CHANGELOG 顶部版本一致。
- **CHANGELOG.md**：Keep a Changelog 格式，含 `[Unreleased]` 与本次 `0.2.0` 条目。
- **`scripts/release.py`**：bump `__version__` → 将 `[Unreleased]` 收口为新版本段（带日期）→ 创建 git tag。
- **升级 `.github/workflows/release.yml`**：tag 触发时从 CHANGELOG 抽取对应版本段作为 release notes，
  构建并附带产物（沿用现有 Windows 打包 spec/脚本）。
- **版本号**：现状不一致（pyproject `0.1.0` vs README `v1.1.0`）。本 PR **统一到单一真源并定为 `0.2.0`**
  （新增向后兼容通讯层 = minor）。README 中的版本表述同步更正为以 `__version__` 为准。

## 8. 分支与 PR 计划

- 分支：`feat/multi-device-comm-layer`（基于 `main`）。
- 提交分组（Conventional Commits）：
  1. `chore(comm): vendor azbil-mfc/taie/balance core drivers (+ VENDOR.md)`
  2. `feat(comm): add device ports and real/sim adapters`
  3. `feat(comm): add MultiDeviceGateway + MultiDeviceSnapshot and acquisition seam`
  4. `test(comm): sim adapters, protocol units, gateway integration`
  5. `build(release): single-source version, CHANGELOG, upgraded release workflow`
- PR 目标：`kevinalliswell/RKA-3000-desktop:main`，正文含设计摘要、scope/non-scope、测试说明、
  provenance/licensing 说明。

## 9. 既定默认（section-9 开放项的处置）

1. **balance-serial 无 LICENSE** — 仓库与 RKA 同属一个所有者，按「同所有者授权」vendoring，并在
   `_vendor/VENDOR.md` 注明；建议后续给 balance-serial 仓库补 LICENSE。
2. **版本号 `0.2.0`**（已采纳）。
3. **MFC → legacy 字段映射**：默认依据 azbil `device_catalog` 的气体类型自动匹配 N2/H2/CO 通道；
   匹配不到时回退固定地址顺序并告警。如后续提供固定 6 路气体编排，再行调整。

## 10. 非目标 / 风险

- 不保证真机行为（本期仅仿真 + 纯协议单测验证）。
- vendored 代码与上游可能漂移；以 `VENDOR.md` 的 commit 钉定 + provenance 记录缓解。
- legacy 三气体字段对 6 路 MFC 是有损映射；富数据通过 `MultiDeviceSnapshot` 保留，待后续 UI/DB PR 完整呈现。
