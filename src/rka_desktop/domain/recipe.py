"""Recipe value objects and validation rules.

A recipe is an ordered list of steps. Each step describes the furnace target, the ramp
rate, the hold time at target and the gas mixture (N2/H2/CO in L/min) that the software
applies while the step is active. Validation here is the final authority; UI constraints
only give early feedback.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any

MAX_STEPS = 32
MAX_TARGET_TEMP_C = 1600.0  # furnace rating from the hardware specification
MAX_RAMP_RATE_CPM = 100.0
MAX_HOLD_SECONDS = 7 * 24 * 3600
MAX_FLOW_LPM = 50.0
MAX_NAME_LENGTH = 100
MAX_NOTES_LENGTH = 500


class RecipeValidationError(ValueError):
    """Raised when a recipe or step violates a business constraint."""


def _number(value: Any, label: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise RecipeValidationError(f"{label}必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RecipeValidationError(f"{label}必须是数字") from exc
    if not math.isfinite(number):
        raise RecipeValidationError(f"{label}必须是有限数值")
    if not minimum <= number <= maximum:
        raise RecipeValidationError(f"{label}须在 {minimum:g} 到 {maximum:g} 之间")
    return number


@dataclass(frozen=True)
class RecipeStep:
    step_no: int
    target_temp_c: float
    ramp_rate_cpm: float
    hold_seconds: int
    n2_lpm: float
    h2_lpm: float
    co_lpm: float
    notes: str = ""

    def __post_init__(self) -> None:
        if type(self.step_no) is not int or self.step_no < 1:
            raise RecipeValidationError("步骤号必须是正整数")
        _number(self.target_temp_c, "目标温度", minimum=0, maximum=MAX_TARGET_TEMP_C)
        _number(self.ramp_rate_cpm, "升温速率", minimum=0, maximum=MAX_RAMP_RATE_CPM)
        if type(self.hold_seconds) is not int or not 0 <= self.hold_seconds <= MAX_HOLD_SECONDS:
            raise RecipeValidationError(f"保温时间须为 0 到 {MAX_HOLD_SECONDS} 秒的整数")
        for label, value in (("N2 流量", self.n2_lpm), ("H2 流量", self.h2_lpm), ("CO 流量", self.co_lpm)):
            _number(value, label, minimum=0, maximum=MAX_FLOW_LPM)
        if not isinstance(self.notes, str) or len(self.notes) > MAX_NOTES_LENGTH:
            raise RecipeValidationError(f"备注须为不超过 {MAX_NOTES_LENGTH} 字的文本")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_step(raw: dict[str, Any], default_step_no: int) -> RecipeStep:
    """Coerce a loosely typed step (form input, JSON, DB row) into a validated RecipeStep."""
    if not isinstance(raw, dict):
        raise RecipeValidationError("步骤必须是对象")
    try:
        step_no = int(raw.get("step_no", default_step_no) or default_step_no)
        hold_seconds = int(float(_number(raw.get("hold_seconds", 0), "保温时间", minimum=0, maximum=MAX_HOLD_SECONDS)))
        return RecipeStep(
            step_no=step_no,
            target_temp_c=_number(raw.get("target_temp_c"), "目标温度", minimum=0, maximum=MAX_TARGET_TEMP_C),
            ramp_rate_cpm=_number(raw.get("ramp_rate_cpm", 0), "升温速率", minimum=0, maximum=MAX_RAMP_RATE_CPM),
            hold_seconds=hold_seconds,
            n2_lpm=_number(raw.get("n2_lpm", 0), "N2 流量", minimum=0, maximum=MAX_FLOW_LPM),
            h2_lpm=_number(raw.get("h2_lpm", 0), "H2 流量", minimum=0, maximum=MAX_FLOW_LPM),
            co_lpm=_number(raw.get("co_lpm", 0), "CO 流量", minimum=0, maximum=MAX_FLOW_LPM),
            notes=str(raw.get("notes") or ""),
        )
    except RecipeValidationError as exc:
        raise RecipeValidationError(f"第 {default_step_no} 步: {exc}") from exc
    except (TypeError, ValueError) as exc:
        raise RecipeValidationError(f"第 {default_step_no} 步: 存在非法数字 ({exc})") from exc


def parse_steps(raw_steps: Any) -> list[RecipeStep]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise RecipeValidationError("请至少配置一个步骤")
    if len(raw_steps) > MAX_STEPS:
        raise RecipeValidationError(f"步骤数不能超过 {MAX_STEPS}")
    steps = [parse_step(raw, index) for index, raw in enumerate(raw_steps, start=1)]
    # Steps execute in list order; renumber so persisted step_no is always 1..n.
    return [RecipeStep(**{**step.to_dict(), "step_no": index}) for index, step in enumerate(steps, start=1)]


def validate_recipe_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise RecipeValidationError("请填写配方名称")
    cleaned = name.strip()
    if len(cleaned) > MAX_NAME_LENGTH:
        raise RecipeValidationError(f"配方名称不能超过 {MAX_NAME_LENGTH} 字")
    return cleaned


@dataclass(frozen=True)
class Recipe:
    name: str
    steps: tuple[RecipeStep, ...]
    recipe_id: int | None = None

    @classmethod
    def from_payload(cls, name: Any, raw_steps: Any, recipe_id: int | None = None) -> "Recipe":
        return cls(name=validate_recipe_name(name), steps=tuple(parse_steps(raw_steps)), recipe_id=recipe_id)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.recipe_id, "name": self.name, "steps": [step.to_dict() for step in self.steps]}


# Portable exchange format for recipe import/export files.
RECIPE_FILE_FORMAT = "rka3000-recipe"
RECIPE_FILE_VERSION = 1


def recipe_to_file(recipe: Recipe) -> dict[str, Any]:
    return {
        "format": RECIPE_FILE_FORMAT,
        "version": RECIPE_FILE_VERSION,
        "name": recipe.name,
        "steps": [step.to_dict() for step in recipe.steps],
    }


def recipe_from_file(document: Any) -> Recipe:
    if not isinstance(document, dict):
        raise RecipeValidationError("配方文件必须是 JSON 对象")
    if document.get("format") != RECIPE_FILE_FORMAT:
        raise RecipeValidationError("不是 RKA-3000 配方文件")
    if document.get("version") != RECIPE_FILE_VERSION:
        raise RecipeValidationError(f"不支持的配方文件版本: {document.get('version')!r}")
    return Recipe.from_payload(document.get("name"), document.get("steps"))
