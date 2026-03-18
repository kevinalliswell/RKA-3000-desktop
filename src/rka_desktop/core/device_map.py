from __future__ import annotations

from dataclasses import dataclass

from rka_desktop.core.registers import RegisterField
from rka_desktop.models.entities import DeviceSnapshot


@dataclass(frozen=True)
class DeviceMap:
    name: str
    snapshot_registers: tuple[RegisterField, ...]
    setpoint_fields: dict[str, RegisterField]
    run_control_word_field: RegisterField

    def build_snapshot(self, values: dict[str, float]) -> DeviceSnapshot:
        return DeviceSnapshot(
            temperature_c=float(values["temperature_c"]),
            weight_g=float(values["weight_g"]),
            pressure_mpa=float(values["pressure_mpa"]),
            n2_lpm=float(values["n2_lpm"]),
            h2_lpm=float(values["h2_lpm"]),
            co_lpm=float(values["co_lpm"]),
            alarm_word=int(values["alarm_word"]),
            interlock_word=int(values.get("interlock_word", 0)),
            run_control_word=int(values.get("run_control_word", 0)),
            estop_status=int(values.get("estop_status", 0)),
        )


def _contract_v1_device_map() -> DeviceMap:
    temperature_pv = RegisterField(name="temperature_c", address=0x0001, scale=10.0)
    temperature_sp = RegisterField(name="temperature_setpoint_c", address=0x0002, scale=10.0)
    ramp_rate_sp = RegisterField(name="ramp_rate_setpoint_cpm", address=0x0003, scale=10.0)
    weight_pv = RegisterField(name="weight_g", address=0x0010, count=2, scale=1000.0, signed=True)
    pressure_pv = RegisterField(name="pressure_mpa", address=0x0040, scale=1000.0)
    n2_flow_pv = RegisterField(name="n2_lpm", address=0x0020, scale=100.0)
    h2_flow_pv = RegisterField(name="h2_lpm", address=0x0021, scale=100.0)
    co_flow_pv = RegisterField(name="co_lpm", address=0x0022, scale=100.0)
    n2_flow_sp = RegisterField(name="n2_setpoint_lpm", address=0x0030, scale=100.0)
    h2_flow_sp = RegisterField(name="h2_setpoint_lpm", address=0x0031, scale=100.0)
    co_flow_sp = RegisterField(name="co_setpoint_lpm", address=0x0032, scale=100.0)
    alarm_word = RegisterField(name="alarm_word", address=0x0050)
    interlock_word = RegisterField(name="interlock_word", address=0x0051)
    run_control_word = RegisterField(name="run_control_word", address=0x0060)
    estop_status = RegisterField(name="estop_status", address=0x0061)

    return DeviceMap(
        name="contract_v1",
        snapshot_registers=(
            temperature_pv,
            weight_pv,
            pressure_pv,
            n2_flow_pv,
            h2_flow_pv,
            co_flow_pv,
            alarm_word,
            interlock_word,
            run_control_word,
            estop_status,
        ),
        setpoint_fields={
            "temperature_setpoint_c": temperature_sp,
            "ramp_rate_setpoint_cpm": ramp_rate_sp,
            "n2_setpoint_lpm": n2_flow_sp,
            "h2_setpoint_lpm": h2_flow_sp,
            "co_setpoint_lpm": co_flow_sp,
        },
        run_control_word_field=run_control_word,
    )


DEVICE_MAP_PROFILES: dict[str, DeviceMap] = {
    "contract_v1": _contract_v1_device_map(),
}


def get_device_map(profile_name: str = "contract_v1") -> DeviceMap:
    return DEVICE_MAP_PROFILES.get(profile_name, DEVICE_MAP_PROFILES["contract_v1"])
