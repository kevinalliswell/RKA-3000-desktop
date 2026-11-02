"""Software alarm rules evaluated on every sample (pure, time injected).

Levels:

* ``warning`` — recorded and must be acknowledged; blocks starting experiments and manual gas
  until acknowledged; the run continues;
* ``alarm`` — recorded and the run is ended into safe disposal (inert purge).

Readback staleness never ends a run by itself: a stale value is not trustworthy enough to act
on, and stopping acquisition would only lose data. The operator is told to check on site.
Hardware alarms (combustible gas, over-pressure, E-stop) come from the PLC alarm word when that
backend is used and are handled by the PLC interlock flow.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rka_desktop.domain.gases import label

OVER_TEMP_MARGIN_C = 30.0
ABSOLUTE_MAX_TEMP_C = 1600.0
MFC_DEVIATION_RATIO = 0.10
MFC_DEVIATION_MIN_LPM = 0.05  # absolute floor so tiny set-points do not alarm on noise
MFC_WARNING_SECONDS = 10.0
MFC_ALARM_SECONDS = 60.0
BALANCE_JUMP_G_PER_S = 1.0
DEVICE_LABELS = {"temp": "温控器", "mfc": "MFC 总线", "balance": "电子天平", "plc": "PLC"}

ALARM_RULES: tuple[dict[str, str], ...] = (
    {"code": "SW-OVERTEMP", "name": "炉温超限", "condition": f"PV > 段目标 + {OVER_TEMP_MARGIN_C:g} ℃，或 PV > {ABSOLUTE_MAX_TEMP_C:g} ℃",
     "level": "alarm", "action": "进入惰性处置：工艺气归零、惰性气吹扫、停止加热"},
    {"code": "SW-MFC-DEV", "name": "MFC 流量偏差",
     "condition": f"|PV − SP| > {MFC_DEVIATION_RATIO:.0%} SP（且 > {MFC_DEVIATION_MIN_LPM:g} L/min）",
     "level": "warning→alarm", "action": f"持续 {MFC_WARNING_SECONDS:g} s 警告；持续 {MFC_ALARM_SECONDS:g} s 升级为报警并处置"},
    {"code": "SW-BALANCE-JUMP", "name": "天平读数跳变", "condition": f"|Δm| > {BALANCE_JUMP_G_PER_S:g} g/s",
     "level": "warning", "action": "记录警告，标记该段数据需复核；禁止手动调气直至确认"},
    {"code": "SW-STALE", "name": "回读过期", "condition": "任一设备超过 3 个采样周期无有效回读（持续超过设定延时时记录警告）",
     "level": "warning", "action": "数值显示 —，该段不入库；禁止启动与手动调气；不自动停机"},
)


@dataclass(frozen=True)
class AlarmEvent:
    code: str
    level: str  # "warning" | "alarm"
    message: str

    @property
    def disposes(self) -> bool:
        return self.level == "alarm"


@dataclass
class SafetyMonitor:
    stale_warning_seconds: float = 30.0
    _deviation_since: dict[str, float] = field(default_factory=dict)
    _deviation_level: dict[str, str] = field(default_factory=dict)
    _last_sp: dict[str, float] = field(default_factory=dict)
    _over_temp: bool = False
    _last_weight: tuple[float, float] | None = None
    _balance_jump: bool = False
    _stale_since: dict[str, float] = field(default_factory=dict)
    _stale_reported: set[str] = field(default_factory=set)

    def observe(
        self,
        t: float,
        *,
        temperature_c: float,
        target_temp_c: float | None,
        gas_pv: dict[str, float],
        gas_sp: dict[str, float],
        weight_g: float,
        stale: set[str] | frozenset[str] = frozenset(),
    ) -> list[AlarmEvent]:
        events: list[AlarmEvent] = []
        events += self._stale(t, set(stale))
        if "temp" not in stale:
            events += self._temperature(temperature_c, target_temp_c)
        if "mfc" not in stale:
            events += self._mfc(t, gas_pv, gas_sp)
        if "balance" not in stale:
            events += self._balance(t, weight_g)
        else:
            self._last_weight = None
        return events

    def _temperature(self, pv: float, target: float | None) -> list[AlarmEvent]:
        over = pv > ABSOLUTE_MAX_TEMP_C or (target is not None and pv > target + OVER_TEMP_MARGIN_C)
        if over and not self._over_temp:
            self._over_temp = True
            limit = f"段目标 {target:.1f} + {OVER_TEMP_MARGIN_C:g}" if target is not None else f"{ABSOLUTE_MAX_TEMP_C:g}"
            return [AlarmEvent("SW-OVERTEMP", "alarm", f"炉温超限：PV {pv:.1f} ℃ > {limit} ℃")]
        if not over:
            self._over_temp = False
        return []

    def _mfc(self, t: float, pv: dict[str, float], sp: dict[str, float]) -> list[AlarmEvent]:
        events: list[AlarmEvent] = []
        for gas, setpoint in sp.items():
            if self._last_sp.get(gas) != setpoint:
                # A new set-point restarts the settling window.
                self._last_sp[gas] = setpoint
                self._deviation_since.pop(gas, None)
                self._deviation_level.pop(gas, None)
            actual = pv.get(gas)
            if actual is None:
                continue
            deviation = abs(actual - setpoint)
            deviating = deviation > max(MFC_DEVIATION_RATIO * setpoint, MFC_DEVIATION_MIN_LPM)
            if not deviating:
                self._deviation_since.pop(gas, None)
                self._deviation_level.pop(gas, None)
                continue
            since = self._deviation_since.setdefault(gas, t)
            held = t - since
            level = self._deviation_level.get(gas)
            ratio = deviation / setpoint if setpoint > 0 else 1.0
            text = f"{label(gas)} 流量偏差 {ratio:.0%}（SP {setpoint:.2f} / PV {actual:.2f} L/min）"
            if held >= MFC_ALARM_SECONDS and level != "alarm":
                self._deviation_level[gas] = "alarm"
                events.append(AlarmEvent(f"SW-MFC-DEV-{gas}", "alarm", f"{text} 持续 {held:.0f} s"))
            elif held >= MFC_WARNING_SECONDS and level is None:
                self._deviation_level[gas] = "warning"
                events.append(AlarmEvent(f"SW-MFC-DEV-{gas}", "warning", f"{text} 持续 {held:.0f} s"))
        return events

    def _balance(self, t: float, weight: float) -> list[AlarmEvent]:
        previous, self._last_weight = self._last_weight, (t, weight)
        if previous is None or t <= previous[0]:
            return []
        rate = abs(weight - previous[1]) / (t - previous[0])
        if rate > BALANCE_JUMP_G_PER_S and not self._balance_jump:
            self._balance_jump = True
            return [AlarmEvent("SW-BALANCE-JUMP", "warning", f"天平读数跳变 {rate:.2f} g/s（{previous[1]:.3f} → {weight:.3f} g）")]
        if rate <= BALANCE_JUMP_G_PER_S:
            self._balance_jump = False
        return []

    def _stale(self, t: float, stale: set[str]) -> list[AlarmEvent]:
        events: list[AlarmEvent] = []
        for device in list(self._stale_since):
            if device not in stale:
                self._stale_since.pop(device)
                self._stale_reported.discard(device)
        for device in stale:
            since = self._stale_since.setdefault(device, t)
            if device not in self._stale_reported and t - since >= self.stale_warning_seconds:
                self._stale_reported.add(device)
                events.append(AlarmEvent(f"SW-STALE-{device.upper()}", "warning",
                                         f"{DEVICE_LABELS.get(device, device)}回读过期 {t - since:.0f} s，请现场核实连接"))
        return events

    def stale_seconds(self, t: float) -> dict[str, float]:
        return {device: t - since for device, since in self._stale_since.items()}

    def describe(self) -> dict[str, Any]:
        return {"rules": list(ALARM_RULES)}
