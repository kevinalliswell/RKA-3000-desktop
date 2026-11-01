"""Application configuration: JSON file with atomic writes plus legacy ``.env`` import.

The pre-migration application read a pydantic ``.env`` next to the working directory. The
same keys are still understood (upper-case env names) so an existing deployment can be
imported once; afterwards the JSON file in the user data directory is authoritative.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import Any

from rka_desktop.domain.control import GasControlMode, TemperatureControlMode, parse_temperature_mode

CONFIG_FORMAT_VERSION = 1

# Legacy .env key -> config attribute (values are parsed by the attribute's type).
LEGACY_ENV_KEYS = {
    "APP_NAME": "app_name",
    "DB_PATH": "db_path",
    "SERIAL_PORT": "plc_serial_port",
    "BAUDRATE": "plc_baudrate",
    "MODBUS_UNIT_ID": "plc_unit_id",
    "MAPPING_PROFILE": "mapping_profile",
    "SIMULATION_MODE": "simulation_mode",
    "POLL_INTERVAL_MS": "poll_interval_ms",
    "ACQUISITION_BATCH_SIZE": "acquisition_batch_size",
    "STEP_HEATUP_GRACE_SECONDS": "step_heatup_grace_seconds",
    "STEP_TOTAL_GRACE_SECONDS": "step_total_grace_seconds",
}


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class MfcChannelSetting:
    address: int
    gas: str
    full_scale_lpm: float


def default_mfc_channels() -> tuple[MfcChannelSetting, ...]:
    return (
        MfcChannelSetting(1, "H2", 5.0),
        MfcChannelSetting(2, "N2", 20.0),
        MfcChannelSetting(3, "CO", 5.0),
        MfcChannelSetting(4, "CO2", 20.0),
        MfcChannelSetting(5, "CH4", 5.0),
        MfcChannelSetting(6, "AR", 20.0),
    )


@dataclass(frozen=True)
class AppConfig:
    app_name: str = "RKA-3000 上位机"
    # Empty means the default location inside the user data directory.
    db_path: str = ""
    simulation_mode: bool = True
    # "multi_device": TAIE + Azbil MFC bus + balance (recipe-driven gas, instrument program).
    # "plc_modbus": the contract_v1 PLC register map used before the migration.
    device_backend: str = "multi_device"
    mapping_profile: str = "contract_v1"
    temperature_mode: str = TemperatureControlMode.PROGRAM.value
    default_gas_mode: str = GasControlMode.AUTO.value
    poll_interval_ms: int = 500
    acquisition_batch_size: int = 10
    step_heatup_grace_seconds: int = 120
    step_total_grace_seconds: int = 180
    degraded_fault_seconds: int = 30
    # PLC Modbus RTU (device_backend == plc_modbus)
    plc_serial_port: str = ""
    plc_baudrate: int = 9600
    plc_unit_id: int = 1
    # TAIE temperature controller
    temp_port: str = ""
    temp_slave_id: int = 1
    temp_baudrate: int = 19200
    temp_program_group: int = 0
    temp_segment_time_unit: str = "min"
    # Azbil MFC RS-485 bus
    mfc_port: str = ""
    mfc_baudrate: int = 19200
    mfc_channels: tuple[MfcChannelSetting, ...] = field(default_factory=default_mfc_channels)
    # Balance
    balance_port: str = ""
    balance_protocol: str = "gs_cpa"
    balance_baudrate: int = 9600
    # Retention
    audit_log_limit: int = 2000
    log_max_bytes: int = 5_000_000
    log_backup_count: int = 3

    def __post_init__(self) -> None:
        if self.device_backend not in {"multi_device", "plc_modbus"}:
            raise ConfigError("device_backend 只能是 multi_device 或 plc_modbus")
        parse_temperature_mode(self.temperature_mode)
        if self.default_gas_mode not in {mode.value for mode in GasControlMode}:
            raise ConfigError("default_gas_mode 只能是 auto 或 manual")
        for name in ("poll_interval_ms", "acquisition_batch_size", "step_heatup_grace_seconds",
                     "step_total_grace_seconds", "degraded_fault_seconds", "plc_baudrate", "plc_unit_id",
                     "temp_slave_id", "temp_baudrate", "mfc_baudrate", "balance_baudrate",
                     "audit_log_limit", "log_max_bytes", "log_backup_count", "temp_program_group"):
            value = getattr(self, name)
            if type(value) is not int:
                raise ConfigError(f"{name} 必须是整数")
        if not 100 <= self.poll_interval_ms <= 60_000:
            raise ConfigError("poll_interval_ms 须在 100 到 60000 之间")
        if not 1 <= self.acquisition_batch_size <= 1000:
            raise ConfigError("acquisition_batch_size 须在 1 到 1000 之间")
        if not 0 <= self.step_heatup_grace_seconds <= 86_400 or not 0 <= self.step_total_grace_seconds <= 86_400:
            raise ConfigError("超时宽限须在 0 到 86400 秒之间")
        if not 5 <= self.degraded_fault_seconds <= 3600:
            raise ConfigError("degraded_fault_seconds 须在 5 到 3600 秒之间")
        if not 0 <= self.temp_program_group <= 2:
            raise ConfigError("temp_program_group 须在 0 到 2 之间")
        if self.temp_segment_time_unit not in {"min", "s"}:
            raise ConfigError("temp_segment_time_unit 只能是 min 或 s")
        if self.balance_protocol not in {"gs_cpa", "longteng"}:
            raise ConfigError("balance_protocol 只能是 gs_cpa 或 longteng")
        if not self.mfc_channels:
            raise ConfigError("至少需要一个 MFC 通道")
        addresses = [channel.address for channel in self.mfc_channels]
        if len(set(addresses)) != len(addresses):
            raise ConfigError("MFC 通道地址重复")
        for channel in self.mfc_channels:
            if type(channel.address) is not int or not 1 <= channel.address <= 127:
                raise ConfigError("MFC 地址须在 1 到 127 之间")
            if not isinstance(channel.full_scale_lpm, (int, float)) or channel.full_scale_lpm <= 0:
                raise ConfigError("MFC 满量程必须大于 0")
        if not self.simulation_mode:
            if self.device_backend == "plc_modbus" and not self.plc_serial_port:
                raise ConfigError("实机模式下 plc_serial_port 不能为空")
            if self.device_backend == "multi_device" and not (self.temp_port and self.mfc_port and self.balance_port):
                raise ConfigError("实机模式下 temp_port、mfc_port、balance_port 都不能为空")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mfc_channels"] = [asdict(channel) for channel in self.mfc_channels]
        return data

    @classmethod
    def from_dict(cls, data: Any) -> "AppConfig":
        if not isinstance(data, dict):
            raise ConfigError("配置必须是 JSON 对象")
        known = {item.name for item in fields(cls)}
        unknown = sorted(set(data) - known - {"format", "version"})
        if unknown:
            raise ConfigError(f"配置包含未知字段: {', '.join(unknown)}")
        kwargs: dict[str, Any] = {}
        for item in fields(cls):
            if item.name not in data:
                continue
            value = data[item.name]
            if item.name == "mfc_channels":
                if not isinstance(value, list):
                    raise ConfigError("mfc_channels 必须是数组")
                channels = []
                for raw in value:
                    if not isinstance(raw, dict):
                        raise ConfigError("MFC 通道必须是对象")
                    try:
                        channels.append(MfcChannelSetting(int(raw["address"]), str(raw["gas"]).upper(),
                                                          float(raw["full_scale_lpm"])))
                    except (KeyError, TypeError, ValueError) as exc:
                        raise ConfigError(f"MFC 通道格式错误: {exc}") from exc
                kwargs[item.name] = tuple(channels)
            elif item.type == "bool" or isinstance(item.default, bool):
                if not isinstance(value, bool):
                    raise ConfigError(f"{item.name} 必须是布尔值")
                kwargs[item.name] = value
            elif isinstance(item.default, int) and not isinstance(item.default, bool):
                if isinstance(value, bool) or not isinstance(value, int):
                    raise ConfigError(f"{item.name} 必须是整数")
                kwargs[item.name] = value
            else:
                if not isinstance(value, str):
                    raise ConfigError(f"{item.name} 必须是字符串")
                kwargs[item.name] = value
        return cls(**kwargs)

    def with_updates(self, updates: dict[str, Any]) -> "AppConfig":
        merged = self.to_dict()
        merged.update(updates)
        return AppConfig.from_dict(merged)


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(prefix=path.name, suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


class JsonConfigStore:
    """Loads and atomically saves ``AppConfig``. Damaged files are kept, never overwritten silently."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.is_file()

    def load(self) -> AppConfig | None:
        if not self.path.is_file():
            return None
        try:
            document = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(f"配置文件无法读取: {self.path} ({exc})") from exc
        if not isinstance(document, dict) or document.get("format") != "rka3000-config":
            raise ConfigError(f"不是 RKA-3000 配置文件: {self.path}")
        if document.get("version") != CONFIG_FORMAT_VERSION:
            raise ConfigError(f"不支持的配置版本: {document.get('version')!r}")
        return AppConfig.from_dict(document)

    def save(self, config: AppConfig) -> None:
        payload = {"format": "rka3000-config", "version": CONFIG_FORMAT_VERSION, **config.to_dict()}
        _write_atomic(self.path, payload)


def parse_legacy_env(text: str) -> dict[str, Any]:
    """Parse the pre-migration ``.env`` into AppConfig field updates (unknown keys are reported)."""
    updates: dict[str, Any] = {}
    unknown: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().upper()
        value = value.strip().strip('"').strip("'")
        if key in {"APP_ENV"}:
            continue
        attribute = LEGACY_ENV_KEYS.get(key)
        if attribute is None:
            unknown.append(key)
            continue
        default = getattr(AppConfig(), attribute)
        if isinstance(default, bool):
            updates[attribute] = value.lower() in {"1", "true", "yes", "on"}
        elif isinstance(default, int):
            try:
                updates[attribute] = int(value)
            except ValueError as exc:
                raise ConfigError(f"旧配置 {key} 不是整数: {value!r}") from exc
        else:
            updates[attribute] = value
    if "plc_serial_port" in updates:
        updates["device_backend"] = "plc_modbus"
        updates["temperature_mode"] = TemperatureControlMode.SETPOINT.value
    if unknown:
        updates["_unknown_keys"] = unknown
    return updates


def import_legacy_env(path: Path, base: AppConfig | None = None) -> tuple[AppConfig, list[str]]:
    updates = parse_legacy_env(path.read_text(encoding="utf-8"))
    unknown = updates.pop("_unknown_keys", [])
    config = (base or AppConfig()).with_updates(updates)
    return config, list(unknown)


def apply_env_overrides(config: AppConfig) -> AppConfig:
    """Environment overrides for development/CI (RKA3000_SIMULATION_MODE, RKA3000_DB_PATH)."""
    updates: dict[str, Any] = {}
    simulation = os.environ.get("RKA3000_SIMULATION_MODE")
    if simulation is not None:
        updates["simulation_mode"] = simulation.lower() in {"1", "true", "yes", "on"}
    db_path = os.environ.get("RKA3000_DB_PATH")
    if db_path:
        updates["db_path"] = db_path
    return replace(config, **updates) if updates else config
