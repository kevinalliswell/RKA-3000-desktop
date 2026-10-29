import json

import pytest

from rka_desktop.comm.config import CommConfig, default_mfc_channels


def test_default_channels_have_six_unique_addresses():
    channels = default_mfc_channels()
    addresses = [c.address for c in channels]
    assert len(channels) == 6
    assert len(set(addresses)) == 6


def test_default_channels_cover_legacy_gases():
    gases = {c.gas for c in default_mfc_channels()}
    assert {"N2", "H2", "CO"}.issubset(gases)


def test_commconfig_defaults_to_simulation():
    cfg = CommConfig()
    assert cfg.simulation_mode is True
    assert len(cfg.mfc_channels) == 6


def test_real_profile_requires_explicit_unique_ports_and_addresses(tmp_path):
    profile = {
        "temperature": {"port": "TEMP", "slave_id": 7, "baudrate": 19200,
                        "parity": "N", "stopbits": 1, "timeout_s": 1.0},
        "mfc": {"port": "MFC", "baudrate": 19200, "format": "8E1", "timeout_s": 1.0,
                "channels": [{"address": i, "gas": f"G{i}", "full_scale_lpm": 5.0}
                             for i in range(1, 7)]},
        "balance": {"port": "BAL", "protocol": "gs_cpa", "baudrate": 1200,
                    "parity": "N", "stopbits": 1, "timeout_s": 1.0},
    }
    path = tmp_path / "devices.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    cfg = CommConfig.from_profile(path)
    assert cfg.profile_loaded and not cfg.simulation_mode
    assert cfg.temp_slave_id == 7

    profile["mfc"]["port"] = "TEMP"
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="distinct"):
        CommConfig.from_profile(path)
    profile["mfc"]["port"] = "MFC"
    profile["mfc"]["channels"][1]["address"] = 1
    path.write_text(json.dumps(profile), encoding="utf-8")
    with pytest.raises(ValueError, match="unique"):
        CommConfig.from_profile(path)


def test_real_comm_cannot_use_simulation_defaults():
    with pytest.raises(ValueError, match="explicit device profile"):
        CommConfig(simulation_mode=False)
