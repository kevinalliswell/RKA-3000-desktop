"""Two-level gas flow limits.

* **Device limit** (设备上限): what the hardware can do — the full scale of the MFC channel
  configured for that gas. A gas without a channel is not available at all.
* **Usage limit** (使用上限): the operating limit for this machine, ``0 < usage <= device``.
  It is versioned: every change creates a new policy version with a mandatory reason, and an
  experiment freezes the version it started with.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from rka_desktop.domain.gases import GAS_BY_KEY, GAS_KEYS


class LimitError(ValueError):
    pass


@dataclass(frozen=True)
class GasLimitPolicy:
    version: int
    limits: dict[str, float]  # gas key -> usage limit (L/min)
    reason: str = ""
    actor: str = ""
    created_at: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    def limit_for(self, gas: str, device_limits: dict[str, float]) -> float | None:
        """Effective usage limit: the policy value capped by the device, or None if unavailable."""
        device = device_limits.get(gas)
        if device is None:
            return None
        usage = self.limits.get(gas, device)
        return min(usage, device)

    def effective(self, device_limits: dict[str, float]) -> dict[str, float]:
        return {gas: value for gas in GAS_KEYS if (value := self.limit_for(gas, device_limits)) is not None}

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "limits": dict(self.limits), "reason": self.reason, "actor": self.actor,
                "created_at": self.created_at}


def initial_policy(device_limits: dict[str, float]) -> GasLimitPolicy:
    return GasLimitPolicy(version=1, limits=dict(device_limits), reason="初始策略：使用上限等于设备上限", actor="system")


def validate_limit_changes(changes: Any, device_limits: dict[str, float]) -> dict[str, float]:
    """Parse ``{"H2": 4.0, ...}``; each value must satisfy 0 < value <= device limit."""
    if not isinstance(changes, dict) or not changes:
        raise LimitError("请至少修改一种气体的使用上限")
    parsed: dict[str, float] = {}
    for raw_key, raw_value in changes.items():
        gas = str(raw_key).upper()
        if gas not in GAS_BY_KEY:
            raise LimitError(f"未知气体: {raw_key}")
        device = device_limits.get(gas)
        if device is None:
            raise LimitError(f"{GAS_BY_KEY[gas].label} 没有配置 MFC 通道，不能设置使用上限")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or not math.isfinite(raw_value):
            raise LimitError(f"{GAS_BY_KEY[gas].label} 使用上限必须是数字")
        value = round(float(raw_value), 2)
        if not 0 < value <= device:
            raise LimitError(f"{GAS_BY_KEY[gas].label} 使用上限须大于 0 且不超过设备上限 {device:.2f} L/min")
        parsed[gas] = value
    return parsed


def validate_reason(reason: Any) -> str:
    if not isinstance(reason, str) or len(reason.strip()) < 2:
        raise LimitError("请填写变更原因（至少 2 个字），原因会写入操作审计")
    if len(reason.strip()) > 200:
        raise LimitError("变更原因不能超过 200 字")
    return reason.strip()
