"""Recipe use cases: list, load, create, update, delete, import/export."""

from __future__ import annotations

from typing import Any

from rka_desktop.application.ports import AuditStore, RecipeStore
from rka_desktop.domain.recipe import Recipe, RecipeValidationError, recipe_from_file, recipe_to_file


class RecipeNotFound(LookupError):
    pass


class RecipeInUse(ValueError):
    pass


class RecipeService:
    def __init__(self, recipes: RecipeStore, audit: AuditStore, *, is_recipe_running: Any = None) -> None:
        self._recipes = recipes
        self._audit = audit
        self._is_recipe_running = is_recipe_running or (lambda recipe_id: False)

    def list_recipes(self) -> list[dict[str, Any]]:
        return self._recipes.list_recipes()

    def get_recipe(self, recipe_id: int) -> dict[str, Any]:
        recipe = self._recipes.get_recipe(recipe_id)
        if recipe is None:
            raise RecipeNotFound("配方不存在")
        return {**recipe, "steps": self._recipes.get_recipe_steps(recipe_id)}

    def create_recipe(self, name: Any, steps: Any) -> dict[str, Any]:
        recipe = Recipe.from_payload(name, steps)
        recipe_id = self._recipes.create_recipe(recipe.name, [step.to_dict() for step in recipe.steps])
        self._audit.log_action("operator", "RECIPE_CREATE", f"recipe_id={recipe_id},name={recipe.name}")
        return self.get_recipe(recipe_id)

    def update_recipe(self, recipe_id: int, name: Any, steps: Any) -> dict[str, Any]:
        if self._recipes.get_recipe(recipe_id) is None:
            raise RecipeNotFound("配方不存在")
        if self._is_recipe_running(recipe_id):
            raise RecipeInUse("该配方正在被运行中的实验使用，不能修改")
        recipe = Recipe.from_payload(name, steps, recipe_id=recipe_id)
        self._recipes.update_recipe(recipe_id, recipe.name, [step.to_dict() for step in recipe.steps])
        self._audit.log_action("operator", "RECIPE_UPDATE", f"recipe_id={recipe_id},name={recipe.name}")
        return self.get_recipe(recipe_id)

    def delete_recipe(self, recipe_id: int) -> None:
        if self._recipes.get_recipe(recipe_id) is None:
            raise RecipeNotFound("配方不存在")
        if self._is_recipe_running(recipe_id):
            raise RecipeInUse("该配方正在被运行中的实验使用，不能删除")
        self._recipes.delete_recipe(recipe_id)
        self._audit.log_action("operator", "RECIPE_DELETE", f"recipe_id={recipe_id}")

    def export_recipe(self, recipe_id: int) -> dict[str, Any]:
        data = self.get_recipe(recipe_id)
        recipe = Recipe.from_payload(data["name"], data["steps"], recipe_id=recipe_id)
        return recipe_to_file(recipe)

    def import_recipe(self, document: Any, *, name_override: str | None = None) -> dict[str, Any]:
        try:
            recipe = recipe_from_file(document)
        except RecipeValidationError:
            raise
        name = name_override or recipe.name
        created = self.create_recipe(name, [step.to_dict() for step in recipe.steps])
        self._audit.log_action("operator", "RECIPE_IMPORT", f"recipe_id={created['id']},name={name}")
        return created
