from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rka_desktop.repositories.audit_repository import AuditLogRepository
from rka_desktop.repositories.recipe_repository import RecipeRepository


@dataclass
class RecipeOption:
    recipe_id: int
    label: str


@dataclass
class RecipeViewState:
    options: list[RecipeOption] = field(default_factory=list)
    selected_recipe_id: int = 0
    recipe_name: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RecipeTransition:
    success: bool = True
    logs: list[str] = field(default_factory=list)
    recipe_id: int | None = None
    user_message: str | None = None
    user_message_level: str | None = None
    view_state: RecipeViewState | None = None


class RecipeController:
    def __init__(self, recipe_repository: RecipeRepository, audit_repository: AuditLogRepository) -> None:
        self.recipe_repository = recipe_repository
        self.audit_repository = audit_repository

    def refresh_recipe_list(self, selected_recipe_id: int | None = None) -> RecipeTransition:
        options = self._list_options()
        active_id = self._resolve_selected_recipe_id(selected_recipe_id, options)
        view_state = RecipeViewState(options=options, selected_recipe_id=active_id)
        if active_id:
            recipe = self.recipe_repository.get_recipe(active_id)
            steps = self.recipe_repository.get_recipe_steps(active_id)
            view_state.recipe_name = recipe["name"] if recipe else ""
            view_state.steps = steps
        return RecipeTransition(view_state=view_state)

    def load_recipe(self, recipe_id: int | None) -> RecipeTransition:
        if recipe_id in (None, 0):
            return RecipeTransition(
                view_state=RecipeViewState(
                    options=self._list_options(),
                    selected_recipe_id=0,
                    recipe_name="",
                    steps=[],
                )
            )

        recipe = self.recipe_repository.get_recipe(int(recipe_id))
        steps = self.recipe_repository.get_recipe_steps(int(recipe_id))
        return RecipeTransition(
            view_state=RecipeViewState(
                options=self._list_options(),
                selected_recipe_id=int(recipe_id),
                recipe_name=recipe["name"] if recipe else "",
                steps=steps,
            )
        )

    def save_recipe(self, name: str, steps: list[dict[str, Any]]) -> RecipeTransition:
        validation_error = self._validate_recipe_payload(name, steps)
        if validation_error is not None:
            return RecipeTransition(success=False, user_message=validation_error, user_message_level="warning")

        recipe_id = self.recipe_repository.create_recipe(name, steps)
        self.audit_repository.log_action("operator", "RECIPE_CREATE", f"recipe_id={recipe_id},name={name}")
        transition = self.refresh_recipe_list(recipe_id)
        transition.recipe_id = recipe_id
        transition.logs.append(f"配方已保存，ID={recipe_id}")
        return transition

    def update_recipe(self, recipe_id: int | None, name: str, steps: list[dict[str, Any]]) -> RecipeTransition:
        if recipe_id in (None, 0):
            return RecipeTransition(success=False, user_message="请先选择一个已存在的配方", user_message_level="warning")

        validation_error = self._validate_recipe_payload(name, steps)
        if validation_error is not None:
            return RecipeTransition(success=False, user_message=validation_error, user_message_level="warning")

        resolved_id = int(recipe_id)
        self.recipe_repository.update_recipe(resolved_id, name, steps)
        self.audit_repository.log_action("operator", "RECIPE_UPDATE", f"recipe_id={resolved_id},name={name}")
        transition = self.refresh_recipe_list(resolved_id)
        transition.recipe_id = resolved_id
        transition.logs.append(f"配方已更新，ID={resolved_id}")
        return transition

    def save_recipe_input(self, name: str, step_inputs: list[dict[str, str]]) -> RecipeTransition:
        parsed = self._parse_step_inputs(step_inputs)
        if isinstance(parsed, str):
            return RecipeTransition(success=False, user_message=parsed, user_message_level="warning")
        return self.save_recipe(name, parsed)

    def update_recipe_input(
        self,
        recipe_id: int | None,
        name: str,
        step_inputs: list[dict[str, str]],
    ) -> RecipeTransition:
        parsed = self._parse_step_inputs(step_inputs)
        if isinstance(parsed, str):
            return RecipeTransition(success=False, user_message=parsed, user_message_level="warning")
        return self.update_recipe(recipe_id, name, parsed)

    def _validate_recipe_payload(self, name: str, steps: list[dict[str, Any]]) -> str | None:
        if not name.strip():
            return "请填写配方名称"
        if not steps:
            return "请至少配置一个步骤"
        return None

    def _parse_step_inputs(self, step_inputs: list[dict[str, str]]) -> list[dict[str, Any]] | str:
        steps: list[dict[str, Any]] = []
        for row, step in enumerate(step_inputs, start=1):
            try:
                steps.append(
                    {
                        "step_no": int(step.get("step_no", str(row))),
                        "target_temp_c": float(step.get("target_temp_c", "0")),
                        "ramp_rate_cpm": float(step.get("ramp_rate_cpm", "0")),
                        "hold_seconds": int(float(step.get("hold_seconds", "0"))),
                        "n2_lpm": float(step.get("n2_lpm", "0")),
                        "h2_lpm": float(step.get("h2_lpm", "0")),
                        "co_lpm": float(step.get("co_lpm", "0")),
                        "notes": step.get("notes", ""),
                    }
                )
            except ValueError as exc:
                return f"存在非法数字: 第 {row} 行 {exc}"
        return steps

    def _list_options(self) -> list[RecipeOption]:
        return [
            RecipeOption(recipe_id=int(recipe["id"]), label=f"#{recipe['id']} {recipe['name']}")
            for recipe in self.recipe_repository.list_recipes()
        ]

    def _resolve_selected_recipe_id(self, selected_recipe_id: int | None, options: list[RecipeOption]) -> int:
        if selected_recipe_id and any(option.recipe_id == selected_recipe_id for option in options):
            return selected_recipe_id
        return options[0].recipe_id if options else 0
