"""Recipe value objects and validation rules.

A recipe is the input template of an experiment: an experiment type (reduction/oxidation),
the inert gas used for carrier, purge and safe disposal, the purge parameters, and an ordered
list of steps. Each step describes the furnace target, the ramp rate, the hold time at target
and the gas mixture (L/min per gas) that the software applies while the step is active.

Validation here covers *parameter ranges* and is enforced on save. Whether a saved recipe may
actually be started (structure, gas usage limits, available MFC channels) is assessed
separately in ``recipe_rules`` so that a recipe that becomes non-runnable later (for example
after the gas usage limits are lowered) is kept and explained instead of being rejected.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from rka_desktop.domain.gases import (
    GAS_BY_KEY,
    GAS_KEYS,
    ExperimentType,
    GasRuleError,
    parse_experiment_type,
    parse_inert_gas,
)

MAX_STEPS = 32
MAX_TARGET_TEMP_C = 1600.0  # furnace rating from the hardware specification
MAX_RAMP_RATE_CPM = 100.0
MAX_HOLD_SECONDS = 7 * 24 * 3600
MAX_FLOW_LPM = 50.0
MAX_PURGE_SECONDS = 24 * 3600
MAX_NAME_LENGTH = 100
MAX_NOTES_LENGTH = 500
MAX_STEP_NAME_LENGTH = 40
DEFAULT_PURGE_SECONDS = 600


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
    name: str = ""
    ar_lpm: float = 0.0
    co2_lpm: float = 0.0
    ch4_lpm: float = 0.0
    o2_lpm: float = 0.0

    def __post_init__(self) -> None:
        if type(self.step_no) is not int or self.step_no < 1:
            raise RecipeValidationError("步骤号必须是正整数")
        _number(self.target_temp_c, "目标温度", minimum=0, maximum=MAX_TARGET_TEMP_C)
        _number(self.ramp_rate_cpm, "升温速率", minimum=0, maximum=MAX_RAMP_RATE_CPM)
        if type(self.hold_seconds) is not int or not 0 <= self.hold_seconds <= MAX_HOLD_SECONDS:
            raise RecipeValidationError(f"保温时间须为 0 到 {MAX_HOLD_SECONDS} 秒的整数")
        for key in GAS_KEYS:
            info = GAS_BY_KEY[key]
            _number(getattr(self, info.column), f"{info.label} 流量", minimum=0, maximum=MAX_FLOW_LPM)
        if not isinstance(self.notes, str) or len(self.notes) > MAX_NOTES_LENGTH:
            raise RecipeValidationError(f"备注须为不超过 {MAX_NOTES_LENGTH} 字的文本")
        if not isinstance(self.name, str) or len(self.name) > MAX_STEP_NAME_LENGTH:
            raise RecipeValidationError(f"阶段名称须为不超过 {MAX_STEP_NAME_LENGTH} 字的文本")

    def flows(self) -> dict[str, float]:
        """Flow set-point per gas key, in catalogue order."""
        return {key: float(getattr(self, GAS_BY_KEY[key].column)) for key in GAS_KEYS}

    def active_gases(self) -> tuple[str, ...]:
        return tuple(key for key, value in self.flows().items() if value > 0)

    @property
    def display_name(self) -> str:
        return self.name or f"第 {self.step_no} 段"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_step(raw: dict[str, Any], default_step_no: int) -> RecipeStep:
    """Coerce a loosely typed step (form input, JSON, DB row) into a validated RecipeStep.

    Flows may be given flat (``co2_lpm``) or as ``{"flows": {"CO2": 0.5}}``; missing gases are 0.
    """
    if not isinstance(raw, dict):
        raise RecipeValidationError("步骤必须是对象")
    try:
        flows_raw = raw.get("flows")
        if flows_raw is not None and not isinstance(flows_raw, dict):
            raise RecipeValidationError("flows 必须是对象")
        flows: dict[str, float] = {}
        for key in GAS_KEYS:
            info = GAS_BY_KEY[key]
            value: Any = raw.get(info.column)
            if flows_raw is not None and (key in flows_raw or key.lower() in flows_raw):
                value = flows_raw.get(key, flows_raw.get(key.lower()))
            flows[info.column] = _number(0 if value is None else value, f"{info.label} 流量", minimum=0, maximum=MAX_FLOW_LPM)
        if flows_raw is not None:
            unknown = sorted(str(k) for k in flows_raw if str(k).upper() not in GAS_BY_KEY)
            if unknown:
                raise RecipeValidationError(f"未知气体: {', '.join(unknown)}")
        step_no = int(raw.get("step_no", default_step_no) or default_step_no)
        hold_seconds = int(float(_number(raw.get("hold_seconds", 0), "保温时间", minimum=0, maximum=MAX_HOLD_SECONDS)))
        name = raw.get("name") or ""
        return RecipeStep(
            step_no=step_no,
            target_temp_c=_number(raw.get("target_temp_c"), "目标温度", minimum=0, maximum=MAX_TARGET_TEMP_C),
            ramp_rate_cpm=_number(raw.get("ramp_rate_cpm", 0), "升温速率", minimum=0, maximum=MAX_RAMP_RATE_CPM),
            hold_seconds=hold_seconds,
            notes=str(raw.get("notes") or ""),
            name=str(name).strip(),
            **flows,
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
    experiment_type: ExperimentType = ExperimentType.REDUCTION
    inert_gas: str = "N2"
    purge_lpm: float = 0.0
    purge_seconds: int = DEFAULT_PURGE_SECONDS
    version: int = 1
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_payload(cls, name: Any, raw_steps: Any, recipe_id: int | None = None, **meta: Any) -> "Recipe":
        try:
            experiment_type = parse_experiment_type(meta.get("experiment_type") or ExperimentType.REDUCTION.value)
            inert_gas = parse_inert_gas(meta.get("inert_gas") or "N2")
        except GasRuleError as exc:
            raise RecipeValidationError(str(exc)) from exc
        purge_lpm = _number(meta.get("purge_lpm") or 0, "吹扫流量", minimum=0, maximum=MAX_FLOW_LPM)
        purge_raw = meta.get("purge_seconds")
        purge_seconds = DEFAULT_PURGE_SECONDS if purge_raw is None else purge_raw
        purge_seconds = int(_number(purge_seconds, "置换时长", minimum=0, maximum=MAX_PURGE_SECONDS))
        description = meta.get("description") or ""
        if not isinstance(description, str) or len(description) > MAX_NOTES_LENGTH:
            raise RecipeValidationError(f"配方说明须为不超过 {MAX_NOTES_LENGTH} 字的文本")
        version = meta.get("version") or 1
        return cls(
            name=validate_recipe_name(name), steps=tuple(parse_steps(raw_steps)), recipe_id=recipe_id,
            experiment_type=experiment_type, inert_gas=inert_gas, purge_lpm=purge_lpm, purge_seconds=purge_seconds,
            version=int(version), description=description.strip(),
        )

    @classmethod
    def from_document(cls, payload: Any, recipe_id: int | None = None) -> "Recipe":
        if not isinstance(payload, dict):
            raise RecipeValidationError("配方必须是对象")
        return cls.from_payload(payload.get("name"), payload.get("steps"), recipe_id=recipe_id,
                                experiment_type=payload.get("experiment_type"), inert_gas=payload.get("inert_gas"),
                                purge_lpm=payload.get("purge_lpm"), purge_seconds=payload.get("purge_seconds"),
                                description=payload.get("description"), version=payload.get("version"))

    def meta_dict(self) -> dict[str, Any]:
        return {
            "experiment_type": self.experiment_type.value, "inert_gas": self.inert_gas, "purge_lpm": self.purge_lpm,
            "purge_seconds": self.purge_seconds, "description": self.description,
        }

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.recipe_id, "name": self.name, "version": self.version, **self.meta_dict(),
                "steps": [step.to_dict() for step in self.steps]}


# Portable exchange format for recipe import/export files.
RECIPE_FILE_FORMAT = "rka3000-recipe"
RECIPE_FILE_VERSION = 2
SUPPORTED_RECIPE_FILE_VERSIONS = (1, 2)


def recipe_to_file(recipe: Recipe) -> dict[str, Any]:
    return {
        "format": RECIPE_FILE_FORMAT,
        "version": RECIPE_FILE_VERSION,
        "name": recipe.name,
        **recipe.meta_dict(),
        "steps": [step.to_dict() for step in recipe.steps],
    }


def recipe_from_file(document: Any) -> Recipe:
    """Read an exchange file. Version 1 files (N2/H2/CO only, no metadata) import as reduction/N2."""
    if not isinstance(document, dict):
        raise RecipeValidationError("配方文件必须是 JSON 对象")
    if document.get("format") != RECIPE_FILE_FORMAT:
        raise RecipeValidationError("不是 RKA-3000 配方文件")
    if document.get("version") not in SUPPORTED_RECIPE_FILE_VERSIONS:
        raise RecipeValidationError(f"不支持的配方文件版本: {document.get('version')!r}")
    if document.get("version") == 1:
        return Recipe.from_payload(document.get("name"), document.get("steps"))
    return Recipe.from_document({key: value for key, value in document.items() if key != "version"})
