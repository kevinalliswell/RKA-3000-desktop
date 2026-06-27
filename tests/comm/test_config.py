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
