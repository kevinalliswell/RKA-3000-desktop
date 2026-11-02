"""Composition root: builds configuration, stores, gateways and use cases in one place."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from rka_desktop import API_VERSION, __version__
from rka_desktop.application.analysis_service import AnalysisService
from rka_desktop.application.device_service import DeviceService
from rka_desktop.application.experiment_runner import ExperimentRunner, RunnerSettings
from rka_desktop.application.history_service import HistoryService
from rka_desktop.application.limits_service import LimitsService
from rka_desktop.application.ports import ExperimentGateway
from rka_desktop.application.recipe_service import RecipeService
from rka_desktop.application.review_service import ReviewService
from rka_desktop.application.tasks import TaskRegistry
from rka_desktop.domain.control import GasControlMode, TemperatureControlMode
from rka_desktop.domain.gases import INERT_GASES, PROCESS_GASES
from rka_desktop.domain.preflight import SITE_CHECKLIST
from rka_desktop.domain.safety import ALARM_RULES
from rka_desktop.infrastructure.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.infrastructure.comm.plc.device_map import get_device_map
from rka_desktop.infrastructure.comm.plc.modbus_client import ModbusRtuClient
from rka_desktop.infrastructure.config import AppConfig, ConfigError, JsonConfigStore, apply_env_overrides, import_legacy_env
from rka_desktop.infrastructure.exports import export_service
from rka_desktop.infrastructure.exports.report_service import ReportService
from rka_desktop.infrastructure.gateways import MultiDeviceExperimentGateway, PlcModbusGateway, comm_config_from_settings
from rka_desktop.infrastructure.paths import AppPaths
from rka_desktop.infrastructure.sqlite.database import DatabaseManager
from rka_desktop.infrastructure.sqlite.repositories import (
    SqliteAlarmStore,
    SqliteAuditStore,
    SqliteExperimentStore,
    SqliteLimitStore,
    SqliteRecipeStore,
    SqliteReportStore,
)

logger = logging.getLogger(__name__)

# Settings that only take effect after the backend restarts (device wiring, storage, timings).
RESTART_REQUIRED_KEYS = {
    "db_path", "simulation_mode", "device_backend", "mapping_profile", "temperature_mode", "poll_interval_ms",
    "acquisition_batch_size", "step_heatup_grace_seconds", "step_total_grace_seconds", "degraded_fault_seconds",
    "purge_exit_temperature_c",
    "plc_serial_port", "plc_baudrate", "plc_unit_id", "temp_port", "temp_slave_id", "temp_baudrate",
    "temp_program_group", "temp_segment_time_unit", "mfc_port", "mfc_baudrate", "mfc_channels",
    "balance_port", "balance_protocol", "balance_baudrate", "log_max_bytes", "log_backup_count",
}


def resolve_database_path(config: AppConfig, paths: AppPaths) -> Path:
    if config.db_path:
        return Path(config.db_path).expanduser()
    return paths.database_file


def load_config(paths: AppPaths, *, legacy_env: Path | None = None) -> tuple[AppConfig, list[str]]:
    """Load the JSON config, importing a legacy ``.env`` once when no JSON config exists yet."""
    store = JsonConfigStore(paths.config_file)
    notes: list[str] = []
    config = store.load()
    if config is None:
        candidate = legacy_env if legacy_env is not None else Path.cwd() / ".env"
        if candidate.is_file():
            config, unknown = import_legacy_env(candidate)
            if config.db_path and not Path(config.db_path).is_absolute():
                config = config.with_updates({"db_path": str((candidate.parent / config.db_path).resolve())})
            notes.append(f"已导入旧配置 {candidate}")
            if unknown:
                notes.append(f"旧配置中未识别的键已忽略: {', '.join(unknown)}")
        else:
            config = AppConfig()
        store.save(config)
        notes.append(f"已写入配置文件 {paths.config_file}")
    return apply_env_overrides(config), notes


def import_legacy_database(paths: AppPaths, legacy_db: Path) -> dict[str, Any]:
    """Copy a pre-migration SQLite file into the user data directory, backing up any existing file."""
    legacy_db = legacy_db.expanduser().resolve()
    if not legacy_db.is_file():
        raise FileNotFoundError(f"旧数据库不存在: {legacy_db}")
    target = paths.database_file
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    if target.exists():
        paths.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = paths.backup_dir / f"{target.stem}-{stamp}.db"
        shutil.copy2(target, backup)
    temp = target.with_name(target.name + ".importing")
    shutil.copy2(legacy_db, temp)
    temp.replace(target)
    DatabaseManager(target).init_schema()
    return {"source": str(legacy_db), "target": str(target), "backup": str(backup) if backup else None}


def build_gateway(config: AppConfig) -> ExperimentGateway:
    if config.device_backend == "plc_modbus":
        client = ModbusRtuClient(
            serial_port=config.plc_serial_port or "simulation", baudrate=config.plc_baudrate, unit_id=config.plc_unit_id,
            device_map=get_device_map(config.mapping_profile), simulation_mode=config.simulation_mode,
        )
        return PlcModbusGateway(client)
    comm = comm_config_from_settings(
        simulation=config.simulation_mode, temp_port=config.temp_port or "simulation", temp_slave_id=config.temp_slave_id,
        temp_baudrate=config.temp_baudrate, mfc_port=config.mfc_port or "simulation", mfc_baudrate=config.mfc_baudrate,
        mfc_channels=[(c.address, c.gas, c.full_scale_lpm) for c in config.mfc_channels],
        balance_port=config.balance_port or "simulation", balance_protocol=config.balance_protocol,
        balance_baudrate=config.balance_baudrate,
        temp_segment_seconds=60.0 if config.temp_segment_time_unit == "min" else 1.0,
    )
    description = {"devices": [
        {"name": "temp", "label": "TAIE 温控仪", "port": config.temp_port, "slave_id": config.temp_slave_id},
        {"name": "mfc", "label": "Azbil MFC 总线", "port": config.mfc_port},
        {"name": "balance", "label": "电子天平", "port": config.balance_port, "protocol": config.balance_protocol},
    ]}
    return MultiDeviceExperimentGateway(
        MultiDeviceGateway.from_config(comm), program_group=config.temp_program_group,
        time_unit=config.temp_segment_time_unit, simulation=config.simulation_mode, description=description,
    )


@dataclass
class AppContainer:
    config: AppConfig
    paths: AppPaths
    config_store: JsonConfigStore
    db: DatabaseManager
    database_path: Path
    gateway: ExperimentGateway
    tasks: TaskRegistry
    runner: ExperimentRunner
    recipes: RecipeService
    history: HistoryService
    analysis: AnalysisService
    devices: DeviceService
    limits: LimitsService
    review: ReviewService
    log_file: Path
    notes: list[str]
    restart_required: bool = False

    def health(self) -> dict[str, Any]:
        return {
            "ok": True, "service": "rka3000-backend", "version": __version__, "api_version": API_VERSION,
            "simulation_mode": self.config.simulation_mode, "device_backend": self.config.device_backend,
            "run_active": self.runner.is_active, "data_dir": str(self.paths.root), "export_dir": str(self.paths.export_dir),
            "database": str(self.database_path), "log_path": str(self.log_file), "restart_required": self.restart_required,
            "notes": list(self.notes),
        }

    def overview(self) -> dict[str, Any]:
        """Home page summary: current run, what blocks the next experiment, and to-dos."""
        run = self.runner.snapshot()
        pending = self.history.list_experiments(limit=10, category="pending")
        recipes = self.recipes.list_recipes()
        version, _ = self.limits.effective()
        recent = self.history.list_experiments(limit=5)
        return {
            "run": {key: run.get(key) for key in ("status", "experiment", "status_text", "current_step_no", "total_steps",
                                                   "elapsed_s", "live", "purge", "end_reason", "end_reason_text", "steps",
                                                   "stale_devices", "emergency")},
            "events": run.get("events", [])[:6],
            "pending_review": pending["experiments"],
            "pending_alarms": run.get("pending_alarms", []),
            "blocked_recipes": [{"id": r["id"], "name": r["name"], "version": r["version"], "summary": r["summary"]}
                                for r in recipes if not r["runnable"]],
            "recipe_count": len(recipes),
            "limits_version": version,
            "counts": pending["counts"],
            "recent": recent["experiments"],
            "simulation_mode": self.config.simulation_mode,
        }

    def rules(self) -> dict[str, Any]:
        return {"alarm_rules": list(ALARM_RULES),
                "process_gases": {kind.value: list(gases) for kind, gases in PROCESS_GASES.items()},
                "inert_gases": list(INERT_GASES),
                "checklist": [{"key": i.key, "label": i.label, "detail": i.detail} for i in SITE_CHECKLIST],
                "safe_temperature_c": self.config.purge_exit_temperature_c,
                "stale_warning_seconds": self.config.degraded_fault_seconds,
                "poll_interval_ms": self.config.poll_interval_ms}

    def update_config(self, updates: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updates, dict):
            raise ConfigError("设置必须是 JSON 对象")
        if self.runner.is_active and (set(updates) & RESTART_REQUIRED_KEYS):
            raise ConfigError("实验运行中不能修改设备或存储设置")
        updated = self.config.with_updates(updates)
        changed = {key for key in updates if getattr(updated, key) != getattr(self.config, key)}
        self.config_store.save(updated)
        self.config = updated
        if changed & RESTART_REQUIRED_KEYS:
            self.restart_required = True
        return {"config": updated.to_dict(), "restart_required": self.restart_required, "changed": sorted(changed)}

    def close(self) -> None:
        try:
            self.runner.close()
        finally:
            self.tasks.close()


def build_container(config: AppConfig, paths: AppPaths, *, gateway: ExperimentGateway | None = None,
                    log_file: Path | None = None, notes: list[str] | None = None) -> AppContainer:
    paths.ensure()
    database_path = resolve_database_path(config, paths)
    db = DatabaseManager(database_path)
    db.init_schema(backup_dir=paths.backup_dir)
    notes = list(notes or [])
    if db.last_backup is not None:
        notes.append(f"数据库已升级，升级前备份：{db.last_backup}")
    recipes_store = SqliteRecipeStore(db)
    experiments_store = SqliteExperimentStore(db)
    alarms_store = SqliteAlarmStore(db)
    audit_store = SqliteAuditStore(db, retain=config.audit_log_limit)
    gateway = gateway or build_gateway(config)
    tasks = TaskRegistry()
    program_mode = config.temperature_mode == TemperatureControlMode.PROGRAM.value
    holder: dict[str, ExperimentRunner] = {}

    def run_snapshot_recipe(recipe_id: int) -> bool:
        runner_ = holder.get("runner")
        return bool(runner_ and runner_.is_active and runner_.snapshot().get("recipe_id") == recipe_id)

    def limits_lock_reason() -> str | None:
        runner_ = holder.get("runner")
        if runner_ is not None and runner_.is_active:
            return "实验运行中，使用上限已锁定"
        pending = experiments_store.list_experiments(limit=3, category="pending")
        if pending:
            return "实验 " + "、".join(p["code"] for p in pending) + " 未归档，使用上限已锁定；归档后可修改"
        return None

    limits_ref: dict[str, LimitsService] = {}
    recipes = RecipeService(
        recipes_store, audit_store, limits=lambda: limits_ref["limits"].effective(), device_limits=gateway.gas_device_limits,
        max_program_steps=(gateway.max_program_steps if program_mode else (lambda: None)), is_recipe_running=run_snapshot_recipe,
    )
    limits = LimitsService(SqliteLimitStore(db), audit_store, device_limits=gateway.gas_device_limits,
                           lock_reason=limits_lock_reason, assess_all=recipes.assess_all)
    limits_ref["limits"] = limits
    runner = ExperimentRunner(
        settings=RunnerSettings(
            poll_interval_ms=config.poll_interval_ms, acquisition_batch_size=config.acquisition_batch_size,
            step_heatup_grace_seconds=config.step_heatup_grace_seconds, step_total_grace_seconds=config.step_total_grace_seconds,
            degraded_fault_seconds=config.degraded_fault_seconds, mapping_profile=config.mapping_profile,
            temperature_mode=TemperatureControlMode(config.temperature_mode), default_gas_mode=GasControlMode(config.default_gas_mode),
            purge_exit_temperature_c=float(config.purge_exit_temperature_c),
        ),
        recipe_loader=recipes.load_for_run, limits_provider=limits.effective,
        experiments=experiments_store, alarms=alarms_store, audit=audit_store, gateway=gateway,
    )
    holder["runner"] = runner
    analysis = AnalysisService(experiments_store, audit_store, tasks, paths.export_dir, ReportService(), SqliteReportStore(db),
                               alarms_store)
    review = ReviewService(experiments_store, alarms_store, audit_store, analysis, poll_interval_s=config.poll_interval_ms / 1000.0,
                           safe_temperature_c=float(config.purge_exit_temperature_c),
                           is_active=lambda experiment_id: runner.active_experiment_id == experiment_id)

    return AppContainer(
        config=config, paths=paths, config_store=JsonConfigStore(paths.config_file), db=db, database_path=database_path,
        gateway=gateway, tasks=tasks, runner=runner, recipes=recipes,
        history=HistoryService(experiments_store, alarms_store, audit_store, tasks, paths.export_dir, export_service,
                               active_experiment_id=lambda: runner.active_experiment_id),
        analysis=analysis,
        devices=DeviceService(gateway, audit_store, run_active=lambda: runner.is_active, ensure_connected=runner.connect_devices),
        limits=limits, review=review,
        log_file=log_file or paths.backend_log_file, notes=notes,
    )
