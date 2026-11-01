"""Gas usage limits: current policy, preview of the impact on recipes, versioned changes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rka_desktop.application.ports import AuditStore, LimitStore
from rka_desktop.domain.gases import GAS_BY_KEY, GAS_KEYS, label
from rka_desktop.domain.limits import GasLimitPolicy, initial_policy, validate_limit_changes, validate_reason


class LimitsLocked(ValueError):
    pass


class LimitsService:
    def __init__(
        self,
        store: LimitStore,
        audit: AuditStore,
        *,
        device_limits: Callable[[], dict[str, float]],
        lock_reason: Callable[[], str | None],
        assess_all: Callable[[dict[str, float]], list[dict[str, Any]]],
    ) -> None:
        self._store = store
        self._audit = audit
        self._device_limits = device_limits
        self._lock_reason = lock_reason
        self._assess_all = assess_all

    def policy(self) -> GasLimitPolicy:
        row = self._store.latest_policy()
        if row is None:
            initial = initial_policy(self._device_limits())
            self._store.save_policy(initial.limits, initial.reason, initial.actor, version=1)
            row = self._store.latest_policy()
            assert row is not None
        return GasLimitPolicy(version=int(row["version"]), limits={k: float(v) for k, v in row["limits"].items()},
                              reason=row.get("reason") or "", actor=row.get("actor") or "", created_at=row.get("created_at") or "")

    def effective(self) -> tuple[int, dict[str, float]]:
        policy = self.policy()
        return policy.version, policy.effective(self._device_limits())

    def describe(self) -> dict[str, Any]:
        policy = self.policy()
        device = self._device_limits()
        effective = policy.effective(device)
        gases = []
        for gas in GAS_KEYS:
            info = GAS_BY_KEY[gas]
            gases.append({"gas": gas, "label": info.label, "hazard": info.hazard, "inert": info.inert,
                          "device_limit": device.get(gas), "usage_limit": effective.get(gas),
                          "policy_value": policy.limits.get(gas), "available": gas in device})
        return {"policy": policy.to_dict(), "gases": gases, "locked": self._lock_reason(),
                "history": self._store.list_policies(10)}

    def _impact(self, new_limits: dict[str, float]) -> list[dict[str, Any]]:
        _, current = self.effective()
        before = {item["recipe"].recipe_id: item["assessment"] for item in self._assess_all(current)}
        affected = []
        for item in self._assess_all(new_limits):
            recipe = item["recipe"]
            after = item["assessment"]
            was = before.get(recipe.recipe_id)
            if was is not None and was.runnable and not after.runnable:
                affected.append({"recipe_id": recipe.recipe_id, "name": recipe.name, "version": recipe.version,
                                 "summary": after.summary()})
        return affected

    def preview(self, changes: Any) -> dict[str, Any]:
        device = self._device_limits()
        parsed = validate_limit_changes(changes, device)
        policy = self.policy()
        merged = {**policy.effective(device), **parsed}
        diff = [{"gas": gas, "label": label(gas), "before": policy.limit_for(gas, device), "after": value}
                for gas, value in parsed.items() if policy.limit_for(gas, device) != value]
        return {"changes": diff, "affected": self._impact(merged), "next_version": policy.version + 1,
                "locked": self._lock_reason()}

    def apply(self, changes: Any, reason: Any, *, actor: Any = None) -> dict[str, Any]:
        locked = self._lock_reason()
        if locked:
            raise LimitsLocked(locked)
        text = validate_reason(reason)
        device = self._device_limits()
        parsed = validate_limit_changes(changes, device)
        policy = self.policy()
        merged = {**policy.effective(device), **parsed}
        preview = self.preview(changes)
        if not preview["changes"]:
            raise LimitsLocked("拟设值与当前生效值相同，没有需要应用的变更")
        who = (actor.strip() if isinstance(actor, str) and actor.strip() else "operator")[:40]
        version = self._store.save_policy(merged, text, who)
        detail = "；".join(f"{c['label']} {c['before']:.2f} → {c['after']:.2f}" for c in preview["changes"])
        if preview["affected"]:
            detail += f" · {len(preview['affected'])} 个配方受影响：" + "、".join(a["name"] for a in preview["affected"])
        self._audit.log_action(who, "LIMITS_UPDATE", f"策略 v{version}：{detail}", category="config", reason=text,
                               result="applied")
        return {**self.describe(), "applied": {"version": version, "affected": preview["affected"]}}
