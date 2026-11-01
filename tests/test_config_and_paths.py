import json

import pytest

from rka_desktop.infrastructure.config import AppConfig, ConfigError, JsonConfigStore, import_legacy_env, parse_legacy_env
from rka_desktop.infrastructure.paths import AppPaths


def test_default_config_round_trips_through_store(tmp_path):
    store = JsonConfigStore(tmp_path / "config.json")
    assert store.load() is None
    store.save(AppConfig())
    loaded = store.load()
    assert loaded == AppConfig()
    document = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert document["format"] == "rka3000-config" and document["version"] == 1
    assert not list(tmp_path.glob("*.tmp"))


def test_unknown_fields_and_bad_types_are_rejected_not_dropped(tmp_path):
    with pytest.raises(ConfigError, match="未知字段"):
        AppConfig.from_dict({"nonsense": 1})
    with pytest.raises(ConfigError):
        AppConfig.from_dict({"poll_interval_ms": "500"})
    with pytest.raises(ConfigError):
        AppConfig.from_dict({"poll_interval_ms": 10})
    with pytest.raises(ConfigError):
        AppConfig.from_dict({"device_backend": "plc_modbus", "simulation_mode": False})
    with pytest.raises(ConfigError):
        AppConfig.from_dict({"mfc_channels": [{"address": 1, "gas": "H2", "full_scale_lpm": 5}, {"address": 1, "gas": "N2", "full_scale_lpm": 5}]})


def test_damaged_config_file_is_reported_and_preserved(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError):
        JsonConfigStore(path).load()
    assert path.read_text(encoding="utf-8") == "{not json"


def test_legacy_env_import_maps_keys_and_switches_backend(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "APP_ENV=dev\nAPP_NAME=RKA Desktop\nDB_PATH=data/rka.db\nSERIAL_PORT=COM3\nBAUDRATE=19200\n"
        "MODBUS_UNIT_ID=2\nMAPPING_PROFILE=contract_v1\nSIMULATION_MODE=false\nPOLL_INTERVAL_MS=250\n"
        "ACQUISITION_BATCH_SIZE=5\nSTEP_HEATUP_GRACE_SECONDS=60\nSTEP_TOTAL_GRACE_SECONDS=90\nFOO=bar\n",
        encoding="utf-8",
    )
    config, unknown = import_legacy_env(env)
    assert unknown == ["FOO"]
    assert config.device_backend == "plc_modbus" and config.temperature_mode == "setpoint"
    assert config.plc_serial_port == "COM3" and config.plc_baudrate == 19200 and config.plc_unit_id == 2
    assert config.simulation_mode is False and config.poll_interval_ms == 250
    assert config.acquisition_batch_size == 5 and config.step_heatup_grace_seconds == 60
    assert config.db_path == "data/rka.db"
    assert parse_legacy_env("SIMULATION_MODE=true")["simulation_mode"] is True


def test_paths_use_override_and_ensure_creates_directories(tmp_path, monkeypatch):
    monkeypatch.setenv("RKA3000_DATA_DIR", str(tmp_path / "data-root"))
    paths = AppPaths().ensure()
    assert paths.root == (tmp_path / "data-root").resolve()
    assert paths.database_file.parent.is_dir() and paths.log_dir.is_dir() and paths.export_dir.is_dir()
