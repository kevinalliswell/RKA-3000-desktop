"""Whether a saved recipe may be started, with a reason per rule.

Rules (all must pass for a recipe to be *runnable*):

1. structure — at least three steps: inert purge, at least one reaction step, inert finish;
2. inert ends — the first and the last step only flow the recipe's inert gas (> 0) and each
   lasts at least the purge time;
3. gas type — every non-zero gas belongs to the experiment type or is the recipe's inert gas;
4. channels — every non-zero gas has an MFC channel and stays within the device limit;
5. usage limits — every step and the purge flow stay within the current usage limits;
6. purge — the purge flow is set (> 0) for the inert gas;
7. program — the temperature program fits the controller (program mode only).

A recipe that fails can still be saved and edited; it just cannot be selected in preflight.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rka_desktop.domain.gases import EXPERIMENT_TYPE_LABELS, GAS_BY_KEY, allowed_gases, label
from rka_desktop.domain.recipe import Recipe, RecipeStep

FLOW_EPSILON = 1e-9


@dataclass(frozen=True)
class RuleCheck:
    key: str
    label: str
    ok: bool
    detail: str
    step_issues: dict[int, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "ok": self.ok, "detail": self.detail,
                "step_issues": {str(k): v for k, v in self.step_issues.items()}}


@dataclass(frozen=True)
class RecipeAssessment:
    runnable: bool
    checks: tuple[RuleCheck, ...]

    @property
    def failures(self) -> tuple[RuleCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def summary(self) -> str:
        failures = self.failures
        if not failures:
            return "校验全部通过"
        return "；".join(f"{check.label}：{check.detail}" for check in failures)

    def step_issues(self) -> dict[int, list[str]]:
        merged: dict[int, list[str]] = {}
        for check in self.checks:
            for step_no, text in check.step_issues.items():
                merged.setdefault(step_no, []).append(text)
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {"runnable": self.runnable, "summary": self.summary(), "checks": [c.to_dict() for c in self.checks],
                "step_issues": {str(k): v for k, v in self.step_issues().items()}}


def is_pure_inert(step: RecipeStep, inert_gas: str) -> bool:
    flows = step.flows()
    return flows[inert_gas] > FLOW_EPSILON and all(value <= FLOW_EPSILON for gas, value in flows.items() if gas != inert_gas)


def is_reaction_step(step: RecipeStep, inert_gas: str) -> bool:
    return any(value > FLOW_EPSILON for gas, value in step.flows().items() if gas != inert_gas)


def assess_recipe(
    recipe: Recipe,
    *,
    usage_limits: dict[str, float],
    device_limits: dict[str, float],
    max_program_steps: int | None = None,
) -> RecipeAssessment:
    steps = recipe.steps
    inert = recipe.inert_gas
    checks: list[RuleCheck] = []

    # 1. structure
    reaction_steps = [s.step_no for s in steps[1:-1] if is_reaction_step(s, inert)] if len(steps) >= 3 else []
    if len(steps) < 3:
        checks.append(RuleCheck("structure", "至少 3 段", False, f"当前 {len(steps)} 段；需要 惰性置换 · 反应 · 惰性收尾"))
    elif not reaction_steps:
        checks.append(RuleCheck("structure", "至少 3 段", False, "中间段没有工艺气，无法形成反应段"))
    else:
        checks.append(RuleCheck("structure", "至少 3 段", True, f"{len(steps)} 段，反应段 {', '.join(map(str, reaction_steps))}"))

    # 2. inert ends
    issues: dict[int, str] = {}
    for step in (steps[0], steps[-1]) if steps else ():
        if not is_pure_inert(step, inert):
            issues[step.step_no] = f"只能开 {label(inert)}"
        elif step.hold_seconds < recipe.purge_seconds:
            issues[step.step_no] = f"时长 {step.hold_seconds} s < 置换 {recipe.purge_seconds} s"
    checks.append(RuleCheck("inert_ends", "首尾纯惰性", not issues,
                            "通过" if not issues else "；".join(f"第 {k} 段{v}" for k, v in issues.items()), issues))

    # 3. gas type
    allowed = set(allowed_gases(recipe.experiment_type, inert))
    issues = {}
    for step in steps:
        bad = [gas for gas in step.active_gases() if gas not in allowed]
        if bad:
            issues[step.step_no] = "不允许 " + "/".join(label(g) for g in bad)
    type_label = EXPERIMENT_TYPE_LABELS[recipe.experiment_type]
    checks.append(RuleCheck("gas_type", "气体符合实验类型", not issues,
                            f"{type_label}允许 {'/'.join(label(g) for g in sorted(allowed - {inert}))} 与 {label(inert)}"
                            if not issues else "；".join(f"第 {k} 段{v}" for k, v in issues.items()), issues))

    # 4. channels / device limits
    issues = {}
    for step in steps:
        problems = []
        for gas in step.active_gases():
            device = device_limits.get(gas)
            value = step.flows()[gas]
            if device is None:
                problems.append(f"{label(gas)} 无 MFC 通道")
            elif value > device + FLOW_EPSILON:
                problems.append(f"{label(gas)} {value:.2f} > 设备上限 {device:.2f}")
        if problems:
            issues[step.step_no] = "，".join(problems)
    if inert not in device_limits:
        issues.setdefault(0, f"{label(inert)} 无 MFC 通道")
    checks.append(RuleCheck("channels", "设备通道与设备上限", not issues,
                            "通过" if not issues else "；".join(f"第 {k} 段 {v}" if k else v for k, v in issues.items()),
                            {k: v for k, v in issues.items() if k}))

    # 5. usage limits
    issues = {}
    for step in steps:
        over = []
        for gas in step.active_gases():
            limit = usage_limits.get(gas)
            value = step.flows()[gas]
            if limit is not None and value > limit + FLOW_EPSILON:
                over.append(f"{label(gas)} {value:.2f} > {limit:.2f}")
        if over:
            issues[step.step_no] = "，".join(over)
    purge_limit = usage_limits.get(inert)
    purge_over = purge_limit is not None and recipe.purge_lpm > purge_limit + FLOW_EPSILON
    detail = "通过" if not issues and not purge_over else "；".join(
        [f"第 {k} 段 {v}" for k, v in issues.items()]
        + ([f"吹扫 {recipe.purge_lpm:.2f} > {purge_limit:.2f}"] if purge_over else []))
    checks.append(RuleCheck("usage_limits", "每段 ≤ 使用上限", not issues and not purge_over, detail, issues))

    # 6. purge
    purge_ok = recipe.purge_lpm > FLOW_EPSILON
    checks.append(RuleCheck("purge", "吹扫参数", purge_ok,
                            f"{label(inert)} {recipe.purge_lpm:.2f} L/min × {recipe.purge_seconds} s" if purge_ok
                            else "未设置吹扫流量；异常结束时需要用它充惰性气"))

    # 7. temperature program size
    if max_program_steps is not None:
        fits = len(steps) <= max_program_steps
        checks.append(RuleCheck("program", "温控程序段数", fits,
                                f"{len(steps)} / {max_program_steps} 段" if fits
                                else f"温控仪最多 {max_program_steps} 个配方段，当前 {len(steps)} 段"))

    return RecipeAssessment(runnable=all(check.ok for check in checks), checks=tuple(checks))


def gas_rows(recipe: Recipe) -> list[dict[str, Any]]:
    """Gas keys that appear anywhere in the recipe, for compact tables."""
    used = {gas for step in recipe.steps for gas in step.active_gases()} | {recipe.inert_gas}
    return [{"gas": key, "label": GAS_BY_KEY[key].label} for key in GAS_BY_KEY if key in used]
