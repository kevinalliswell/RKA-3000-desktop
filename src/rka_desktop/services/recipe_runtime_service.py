from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RecipeStepRuntime:
    step_no: int
    target_temp_c: float
    ramp_rate_cpm: float
    hold_seconds: int
    n2_lpm: float
    h2_lpm: float
    co_lpm: float
    notes: str


def build_recipe_runtime(steps: list[dict[str, Any]]) -> list[RecipeStepRuntime]:
    runtime_steps: list[RecipeStepRuntime] = []
    for index, step in enumerate(steps, start=1):
        runtime_steps.append(
            RecipeStepRuntime(
                step_no=int(step.get("step_no", index)),
                target_temp_c=float(step["target_temp_c"]),
                ramp_rate_cpm=float(step["ramp_rate_cpm"]),
                hold_seconds=int(step["hold_seconds"]),
                n2_lpm=float(step["n2_lpm"]),
                h2_lpm=float(step["h2_lpm"]),
                co_lpm=float(step["co_lpm"]),
                notes=str(step.get("notes", "")),
            )
        )
    return runtime_steps

