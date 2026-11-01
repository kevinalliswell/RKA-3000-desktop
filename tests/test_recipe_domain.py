import pytest

from rka_desktop.domain.recipe import Recipe, RecipeValidationError, parse_steps, recipe_from_file, recipe_to_file


def test_parse_steps_coerces_strings_and_renumbers():
    steps = parse_steps([
        {"step_no": "7", "target_temp_c": "900", "ramp_rate_cpm": "10", "hold_seconds": "600.0", "n2_lpm": "8", "h2_lpm": "1", "co_lpm": "0.8"},
        {"target_temp_c": 950, "hold_seconds": 10},
    ])
    assert [s.step_no for s in steps] == [1, 2]
    assert steps[0].hold_seconds == 600 and steps[0].target_temp_c == 900.0
    assert steps[1].ramp_rate_cpm == 0.0 and steps[1].n2_lpm == 0.0


@pytest.mark.parametrize("bad", [
    [], "x", [{"target_temp_c": "abc", "hold_seconds": 1}], [{"target_temp_c": 2000, "hold_seconds": 1}],
    [{"target_temp_c": 900, "hold_seconds": -1}], [{"target_temp_c": 900, "hold_seconds": 1, "n2_lpm": 99}],
    [{"target_temp_c": float("nan"), "hold_seconds": 1}], [{"target_temp_c": True, "hold_seconds": 1}],
])
def test_invalid_steps_rejected(bad):
    with pytest.raises(RecipeValidationError):
        parse_steps(bad)


def test_recipe_name_and_file_round_trip():
    with pytest.raises(RecipeValidationError, match="配方名称"):
        Recipe.from_payload("  ", [{"target_temp_c": 900, "hold_seconds": 1}])
    recipe = Recipe.from_payload(" 标准流程 ", [{"target_temp_c": 900, "hold_seconds": 1, "n2_lpm": 8}])
    document = recipe_to_file(recipe)
    assert document["format"] == "rka3000-recipe" and document["version"] == 1
    restored = recipe_from_file(document)
    assert restored.name == "标准流程" and restored.steps[0].n2_lpm == 8.0
    with pytest.raises(RecipeValidationError):
        recipe_from_file({"format": "other", "version": 1})
    with pytest.raises(RecipeValidationError):
        recipe_from_file({"format": "rka3000-recipe", "version": 99, "name": "x", "steps": []})
