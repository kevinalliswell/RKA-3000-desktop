"""MfcClient 仿真模式单元测试（无需 serial 依赖）。"""
import math

import pytest

from rka_desktop.core.mfc_client import DEFAULT_CHANNEL_CONFIGS, MfcChannelConfig, MfcClient
from rka_desktop.core.mfc_registers import EepromAddr, sp_eeprom_addr
from rka_desktop.models.entities import MfcSnapshot


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def client() -> MfcClient:
    return MfcClient(serial_port="SIM", simulation_mode=True)


@pytest.fixture
def ch_h2() -> MfcChannelConfig:
    return MfcChannelConfig(channel_id=1, machine_addr="01", gas_label="H2", full_scale_lpm=1.0)


@pytest.fixture
def ch_n2() -> MfcChannelConfig:
    return MfcChannelConfig(channel_id=2, machine_addr="02", gas_label="N2", full_scale_lpm=10.0)


# ===========================================================================
# 连接管理
# ===========================================================================

class TestConnect:
    def test_sim_connect_returns_true(self, client):
        assert client.connect() is True

    def test_sim_close_does_not_raise(self, client):
        client.connect()
        client.close()  # _serial 为 None，应静默通过


# ===========================================================================
# read_snapshot
# ===========================================================================

class TestReadSnapshotSim:
    def test_returns_mfc_snapshot(self, client, ch_h2):
        snap = client.read_snapshot(ch_h2)
        assert isinstance(snap, MfcSnapshot)

    def test_channel_id_and_label(self, client, ch_h2):
        snap = client.read_snapshot(ch_h2)
        assert snap.channel_id == 1
        assert snap.gas_label == "H2"

    def test_end_code_normal(self, client, ch_h2):
        snap = client.read_snapshot(ch_h2)
        assert snap.end_code == "00"

    def test_error_is_none(self, client, ch_h2):
        snap = client.read_snapshot(ch_h2)
        assert snap.error is None

    def test_pv_within_range(self, client, ch_n2):
        for _ in range(20):
            snap = client.read_snapshot(ch_n2)
            assert 0.0 <= snap.pv_lpm <= ch_n2.full_scale_lpm + 0.1

    def test_pv_non_negative(self, client, ch_h2):
        for _ in range(10):
            snap = client.read_snapshot(ch_h2)
            assert snap.pv_lpm >= 0.0

    def test_sp_is_sixty_percent_of_full_scale(self, client, ch_n2):
        snap = client.read_snapshot(ch_n2)
        assert abs(snap.sp_lpm - ch_n2.full_scale_lpm * 0.6) < 0.001


# ===========================================================================
# read_all_snapshots
# ===========================================================================

class TestReadAllSnapshotsSim:
    def test_returns_six_snapshots(self, client):
        snaps = client.read_all_snapshots()
        assert len(snaps) == 6

    def test_channel_ids_sequential(self, client):
        snaps = client.read_all_snapshots()
        ids = [s.channel_id for s in snaps]
        assert ids == [1, 2, 3, 4, 5, 6]

    def test_gas_labels_match_config(self, client):
        snaps = client.read_all_snapshots()
        expected = [ch.gas_label for ch in DEFAULT_CHANNEL_CONFIGS]
        assert [s.gas_label for s in snaps] == expected

    def test_all_end_codes_normal(self, client):
        snaps = client.read_all_snapshots()
        assert all(s.end_code == "00" for s in snaps)

    def test_all_errors_none(self, client):
        snaps = client.read_all_snapshots()
        assert all(s.error is None for s in snaps)

    def test_snapshot_on_channel_error_has_nan(self):
        """当某通道 read_snapshot 抛异常时，read_all_snapshots 应捕获并填充 NaN。"""
        from unittest.mock import patch

        ch = DEFAULT_CHANNEL_CONFIGS[0]
        client = MfcClient(serial_port="SIM", simulation_mode=True, channels=[ch])

        with patch.object(client, "read_snapshot", side_effect=RuntimeError("模拟通信故障")):
            snaps = client.read_all_snapshots()

        assert len(snaps) == 1
        snap = snaps[0]
        assert math.isnan(snap.pv_lpm)
        assert math.isnan(snap.sp_lpm)
        assert snap.error is not None
        assert "模拟通信故障" in snap.error


# ===========================================================================
# write_sp
# ===========================================================================

class TestWriteSpSim:
    def test_normal_returns_00(self, client, ch_n2):
        result = client.write_sp(ch_n2, 5.0)
        assert result == "00"

    def test_zero_setpoint(self, client, ch_h2):
        result = client.write_sp(ch_h2, 0.0)
        assert result == "00"

    def test_full_scale_setpoint(self, client, ch_n2):
        result = client.write_sp(ch_n2, ch_n2.full_scale_lpm)
        assert result == "00"

    def test_negative_raises_value_error(self, client, ch_h2):
        with pytest.raises(ValueError):
            client.write_sp(ch_h2, -0.1)

    def test_over_full_scale_raises_value_error(self, client, ch_h2):
        with pytest.raises(ValueError):
            client.write_sp(ch_h2, ch_h2.full_scale_lpm + 0.001)

    def test_sp_index_default_is_zero(self, client, ch_h2):
        """默认 sp_index=0，应使用 SP-0 地址 0x1131。"""
        result = client.write_sp(ch_h2, 0.5)
        assert result == "00"

    def test_sp_index_range(self, client, ch_n2):
        """sp_index 0–7 均应正常返回 "00"。"""
        for idx in range(8):
            result = client.write_sp(ch_n2, 1.0, sp_index=idx)
            assert result == "00"


# ===========================================================================
# sp_eeprom_addr（来自 mfc_registers）
# ===========================================================================

class TestSpEepromAddr:
    def test_sp0_address(self):
        assert sp_eeprom_addr(0) == int(EepromAddr.SP_0)
        assert sp_eeprom_addr(0) == 0x1131

    def test_sp7_address(self):
        assert sp_eeprom_addr(7) == 0x1138

    def test_sequential(self):
        addrs = [sp_eeprom_addr(i) for i in range(8)]
        for i in range(1, 8):
            assert addrs[i] == addrs[i - 1] + 1

    def test_out_of_range_low(self):
        with pytest.raises(ValueError):
            sp_eeprom_addr(-1)

    def test_out_of_range_high(self):
        with pytest.raises(ValueError):
            sp_eeprom_addr(8)
