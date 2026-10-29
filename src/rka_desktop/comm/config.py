from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MfcChannelConfig:
    address: int
    gas: str           # e.g. "H2", "N2", "CO", "CO2", "AR", "AIR"
    full_scale_lpm: float

    def __post_init__(self) -> None:
        if not 1 <= self.address <= 127 or not self.gas.strip():
            raise ValueError("MFC address must be 1..127 and gas must be non-empty")
        if not math.isfinite(self.full_scale_lpm) or self.full_scale_lpm <= 0:
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
    temp_parity: str = "N"
    temp_stopbits: float = 1
    temp_timeout_s: float = 1.0
    # Azbil MFC RS-485 bus (CPL)
    mfc_port: str = "/dev/tty.usbserial-mfc"
    mfc_baudrate: int = 19200
    mfc_format: str = "8E1"
    mfc_timeout_s: float = 1.0
    mfc_channels: tuple[MfcChannelConfig, ...] = field(default_factory=default_mfc_channels)
    # Electronic balance (serial ASCII)
    balance_port: str = "/dev/tty.usbserial-bal"
    balance_protocol: str = "gs_cpa"
    balance_baudrate: int = 9600
    balance_parity: str = "N"
    balance_stopbits: float = 1
    balance_timeout_s: float = 1.0
    profile_loaded: bool = False

    def __post_init__(self) -> None:
        if not self.simulation_mode and not self.profile_loaded:
            raise ValueError("real-device diagnostics require an explicit device profile")
        if len(self.mfc_channels) != 6 or len({c.address for c in self.mfc_channels}) != 6:
            raise ValueError("exactly six unique MFC addresses are required")
        if self.temp_slave_id < 1 or self.temp_slave_id > 247:
            raise ValueError("temperature slave ID must be 1..247")
        if self.mfc_format not in {"8E1", "8N2"}:
            raise ValueError("MFC format must be 8E1 or 8N2")
        if self.balance_protocol not in {"gs_cpa", "longteng"}:
            raise ValueError("unsupported balance protocol")
        for value in (self.temp_baudrate, self.mfc_baudrate, self.balance_baudrate):
            if value <= 0:
                raise ValueError("serial baudrate must be positive")
        for value in (self.temp_timeout_s, self.mfc_timeout_s, self.balance_timeout_s):
            if not math.isfinite(value) or value <= 0 or value > 10:
                raise ValueError("serial timeout must be in (0, 10] seconds")
        for parity, stopbits in ((self.temp_parity, self.temp_stopbits), (self.balance_parity, self.balance_stopbits)):
            if parity not in {"N", "E", "O"} or stopbits not in {1, 2}:
                raise ValueError("unsupported serial parity or stop bits")
        if not self.simulation_mode:
            ports = (self.temp_port, self.mfc_port, self.balance_port)
            if any(not port.strip() for port in ports) or len(set(ports)) != 3:
                raise ValueError("three distinct, non-empty serial ports are required")

    @classmethod
    def from_profile(cls, path: str | Path) -> CommConfig:
        """Load an explicit field profile. It authorizes read-only diagnostics only."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        temp, mfc, balance = (data[key] for key in ("temperature", "mfc", "balance"))
        channels = tuple(MfcChannelConfig(**channel) for channel in mfc["channels"])
        return cls(
            simulation_mode=False, profile_loaded=True,
            temp_port=temp["port"], temp_slave_id=temp["slave_id"],
            temp_baudrate=temp["baudrate"], temp_parity=temp["parity"],
            temp_stopbits=temp["stopbits"], temp_timeout_s=temp["timeout_s"],
            mfc_port=mfc["port"], mfc_baudrate=mfc["baudrate"],
            mfc_format=mfc["format"], mfc_timeout_s=mfc["timeout_s"],
            mfc_channels=channels,
            balance_port=balance["port"], balance_protocol=balance["protocol"],
            balance_baudrate=balance["baudrate"], balance_parity=balance["parity"],
            balance_stopbits=balance["stopbits"], balance_timeout_s=balance["timeout_s"],
        )
