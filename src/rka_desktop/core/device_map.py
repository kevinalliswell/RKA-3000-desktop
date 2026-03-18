from __future__ import annotations

from rka_desktop.core.registers import RegisterField
from rka_desktop.models.entities import DeviceSnapshot

TEMPERATURE_PV = RegisterField(name="temperature_c", address=0x0001, scale=10.0)
WEIGHT_PV = RegisterField(name="weight_g", address=0x0010, count=2, scale=1000.0, signed=True)
PRESSURE_PV = RegisterField(name="pressure_mpa", address=0x0040, scale=1000.0)
N2_FLOW_PV = RegisterField(name="n2_lpm", address=0x0020, scale=100.0)
H2_FLOW_PV = RegisterField(name="h2_lpm", address=0x0021, scale=100.0)
CO_FLOW_PV = RegisterField(name="co_lpm", address=0x0022, scale=100.0)
ALARM_WORD = RegisterField(name="alarm_word", address=0x0050)

SNAPSHOT_REGISTERS = (
    TEMPERATURE_PV,
    WEIGHT_PV,
    PRESSURE_PV,
    N2_FLOW_PV,
    H2_FLOW_PV,
    CO_FLOW_PV,
    ALARM_WORD,
)


def build_snapshot(values: dict[str, float]) -> DeviceSnapshot:
    return DeviceSnapshot(
        temperature_c=float(values["temperature_c"]),
        weight_g=float(values["weight_g"]),
        pressure_mpa=float(values["pressure_mpa"]),
        n2_lpm=float(values["n2_lpm"]),
        h2_lpm=float(values["h2_lpm"]),
        co_lpm=float(values["co_lpm"]),
        alarm_word=int(values["alarm_word"]),
    )

