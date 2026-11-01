"""Recipe use cases: list, load, create, update (new version each save), delete, import/export, runnability."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rka_desktop.application.ports import AuditStore, RecipeStore
from rka_desktop.domain.recipe import Recipe, RecipeValidationError, recipe_from_file, recipe_to_file
from rka_desktop.domain.recipe_rules import RecipeAssessment, assess_recipe


class RecipeNotFound(LookupError):
    pass


class RecipeInUse(ValueError):
    pass


def _actor(value: Any) -> str:
    return (value.strip() if isinstance(value, str) and value.strip() else "operator")[:40]


class RecipeService:
    def __init__(
        self,
        recipes: RecipeStore,
        audit: AuditStore,
        *,
        limits: Callable[[], tuple[int, dict[str, float]]],
        device_limits: Callable[[], dict[str, float]],
        max_program_steps: Callable[[], int | None] = lambda: None,
        is_recipe_running: Callable[[int], bool] | None = None,
    ) -> None:
        self._recipes = recipes
        self._audit = audit
        self._limits = limits
        self._device_limits = device_limits
        self._max_program_steps = max_program_steps
        self._is_recipe_running = is_recipe_running or (lambda recipe_id: False)

    # ---------------------------------------------------------------- reads
    def _domain(self, row: dict[str, Any], steps: list[dict[str, Any]]) -> Recipe:
        return Recipe.from_payload(row["name"], steps, recipe_id=int(row["id"]), experiment_type=row.get("experiment_type"),
                                   inert_gas=row.get("inert_gas"), purge_lpm=row.get("purge_lpm"),
                                   purge_seconds=row.get("purge_seconds"), description=row.get("description"),
                                   version=row.get("version"))

    def assess(self, recipe: Recipe, usage_limits: dict[str, float] | None = None) -> RecipeAssessment:
        if usage_limits is None:
            _, usage_limits = self._limits()
        return assess_recipe(recipe, usage_limits=usage_limits, device_limits=self._device_limits(),
                             max_program_steps=self._max_program_steps())

    def _load(self, recipe_id: int) -> Recipe:
        row = self._recipes.get_recipe(recipe_id)
        if row is None:
            raise RecipeNotFound("配方不存在")
        return self._domain(row, self._recipes.get_recipe_steps(recipe_id))

    def load_for_run(self, recipe_id: int) -> tuple[Recipe, RecipeAssessment]:
        recipe = self._load(recipe_id)
        return recipe, self.assess(recipe)

    def list_recipes(self) -> list[dict[str, Any]]:
        version, usage = self._limits()
        items = []
        for row in self._recipes.list_recipes():
            try:
                recipe = self._domain(row, self._recipes.get_recipe_steps(int(row["id"])))
                assessment = self.assess(recipe, usage)
                runnable, summary = assessment.runnable, assessment.summary()
                step_count = len(recipe.steps)
            except RecipeValidationError as exc:  # stored data no longer valid: show, never crash the list
                runnable, summary, step_count = False, f"配方数据无效：{exc}", 0
            items.append({**row, "runnable": runnable, "summary": summary, "step_count": step_count,
                          "limits_version": version, "experiment_count": self._recipes.count_experiments_for_recipe(int(row["id"]))})
        return items

    def get_recipe(self, recipe_id: int) -> dict[str, Any]:
        row = self._recipes.get_recipe(recipe_id)
        if row is None:
            raise RecipeNotFound("配方不存在")
        steps = self._recipes.get_recipe_steps(recipe_id)
        version, usage = self._limits()
        try:
            assessment = self.assess(self._domain(row, steps), usage).to_dict()
        except RecipeValidationError as exc:
            assessment = {"runnable": False, "summary": f"配方数据无效：{exc}", "checks": [], "step_issues": {}}
        versions = [{k: v for k, v in item.items() if k != "snapshot"} for item in self._recipes.list_recipe_versions(recipe_id)]
        return {**row, "steps": steps, "assessment": assessment, "limits_version": version, "versions": versions,
                "experiment_count": self._recipes.count_experiments_for_recipe(recipe_id),
                "running": self._is_recipe_running(recipe_id)}

    def versions(self, recipe_id: int) -> list[dict[str, Any]]:
        if self._recipes.get_recipe(recipe_id) is None:
            raise RecipeNotFound("配方不存在")
        return self._recipes.list_recipe_versions(recipe_id)

    def assess_all(self, usage_limits: dict[str, float]) -> list[dict[str, Any]]:
        results = []
        for row in self._recipes.list_recipes():
            try:
                recipe = self._domain(row, self._recipes.get_recipe_steps(int(row["id"])))
            except RecipeValidationError:
                continue
            results.append({"recipe": recipe, "assessment": self.assess(recipe, usage_limits)})
        return results

    # ---------------------------------------------------------------- writes
    def create_recipe(self, payload: Any, *, actor: Any = None) -> dict[str, Any]:
        recipe = Recipe.from_document(payload)
        recipe_id = self._recipes.create_recipe(recipe.name, [step.to_dict() for step in recipe.steps], recipe.meta_dict(),
                                                reason=str((payload or {}).get("reason") or "新建配方")[:200], actor=_actor(actor))
        self._audit.log_action(_actor(actor), "RECIPE_CREATE", f"#{recipe_id} {recipe.name} v1", category="config",
                               reason=str((payload or {}).get("reason") or "")[:200] or None, result="applied")
        return self.get_recipe(recipe_id)

    def update_recipe(self, recipe_id: int, payload: Any, *, actor: Any = None) -> dict[str, Any]:
        if self._recipes.get_recipe(recipe_id) is None:
            raise RecipeNotFound("配方不存在")
        if self._is_recipe_running(recipe_id):
            raise RecipeInUse("该配方正在被运行中的实验使用，不能修改")
        recipe = Recipe.from_document(payload, recipe_id=recipe_id)
        reason = str((payload or {}).get("reason") or "").strip()[:200]
        if len(reason) < 2:
            raise RecipeValidationError("请填写本次修改原因（至少 2 个字），会记入版本历史")
        version = self._recipes.update_recipe(recipe_id, recipe.name, [step.to_dict() for step in recipe.steps],
                                              recipe.meta_dict(), reason=reason, actor=_actor(actor))
        self._audit.log_action(_actor(actor), "RECIPE_UPDATE", f"#{recipe_id} {recipe.name} → v{version}", category="config",
                               reason=reason, result="applied")
        return self.get_recipe(recipe_id)

    def delete_recipe(self, recipe_id: int, *, actor: Any = None) -> None:
        if self._recipes.get_recipe(recipe_id) is None:
            raise RecipeNotFound("配方不存在")
        if self._is_recipe_running(recipe_id):
            raise RecipeInUse("该配方正在被运行中的实验使用，不能删除")
        self._recipes.delete_recipe(recipe_id)
        self._audit.log_action(_actor(actor), "RECIPE_DELETE", f"#{recipe_id}", category="config", result="applied")

    def export_recipe(self, recipe_id: int) -> dict[str, Any]:
        return recipe_to_file(self._load(recipe_id))

    def import_recipe(self, document: Any, *, name_override: str | None = None, actor: Any = None) -> dict[str, Any]:
        recipe = recipe_from_file(document)
        payload = {**recipe.to_dict(), "name": name_override or recipe.name, "reason": "导入配方文件"}
        created = self.create_recipe(payload, actor=actor)
        self._audit.log_action(_actor(actor), "RECIPE_IMPORT", f"#{created['id']} {payload['name']}", category="config",
                               result="applied")
        return created
