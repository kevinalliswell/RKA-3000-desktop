from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class MfcChannelConfig:
    address: int
    gas: str           # e.g. "H2", "N2", "CO", "CO2", "AR", "AIR"
    full_scale_lpm: float

    def __post_init__(self) -> None:
        if self.full_scale_lpm <= 0:
            raise ValueError(
                f"full_scale_lpm must be > 0 for MFC address {self.address}, got {self.full_scale_lpm}"
            )


def default_mfc_channels() -> tuple[MfcChannelConfig, ...]:
    """Six MFCs on one RS-485 bus. N2/H2/CO are unique so legacy mapping is deterministic."""
    return (
        MfcChannelConfig(address=1, gas="H2", full_scale_lpm=2.0),
        MfcChannelConfig(address=2, gas="N2", full_scale_lpm=5.0),
        MfcChannelConfig(address=3, gas="CO", full_scale_lpm=2.0),
        MfcChannelConfig(address=4, gas="CO2", full_scale_lpm=2.0),
        MfcChannelConfig(address=5, gas="AR", full_scale_lpm=5.0),
        MfcChannelConfig(address=6, gas="AIR", full_scale_lpm=5.0),
    )


@dataclass(frozen=True)
class CommConfig:
    simulation_mode: bool = True
    # TAIE temperature controller (Modbus RTU)
    temp_port: str = "/dev/tty.usbserial-temp"
    temp_slave_id: int = 1
    temp_baudrate: int = 19200
    # Azbil MFC RS-485 bus (CPL)
    mfc_port: str = "/dev/tty.usbserial-mfc"
    mfc_baudrate: int = 19200
    mfc_channels: tuple[MfcChannelConfig, ...] = field(default_factory=default_mfc_channels)
    # Electronic balance (serial ASCII)
    balance_port: str = "/dev/tty.usbserial-bal"
    balance_protocol: str = "gs_cpa"
    balance_baudrate: int = 9600
