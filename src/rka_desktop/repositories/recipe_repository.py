from __future__ import annotations

from typing import Any

from rka_desktop.db.database import DatabaseManager


class RecipeRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def list_recipes(self) -> list[dict[str, Any]]:
        return self._db.list_recipes()

    def get_recipe(self, recipe_id: int) -> dict[str, Any] | None:
        return self._db.get_recipe(recipe_id)

    def get_recipe_steps(self, recipe_id: int) -> list[dict[str, Any]]:
        return self._db.get_recipe_steps(recipe_id)

    def create_recipe(self, name: str, steps: list[dict[str, Any]]) -> int:
        return self._db.create_recipe(name, steps)

    def update_recipe(self, recipe_id: int, name: str, steps: list[dict[str, Any]]) -> None:
        self._db.update_recipe(recipe_id, name, steps)
