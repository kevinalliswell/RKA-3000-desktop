from rka_desktop.controllers.recipe_controller import RecipeController
from rka_desktop.core.config import Settings
from rka_desktop.db.database import DatabaseManager


def _build_recipe_controller(tmp_path, db_name: str = "recipe_controller.db"):
    settings = Settings(
        db_path=str(tmp_path / db_name),
        simulation_mode=True,
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    controller = RecipeController(db)
    return db, controller


def _recipe_steps():
    return [
        {
            "step_no": 1,
            "target_temp_c": 900.0,
            "ramp_rate_cpm": 10.0,
            "hold_seconds": 600,
            "n2_lpm": 8.0,
            "h2_lpm": 1.0,
            "co_lpm": 0.8,
            "notes": "",
        }
    ]


def test_recipe_controller_saves_recipe_and_returns_view_state(tmp_path):
    db, controller = _build_recipe_controller(tmp_path, "recipe_save.db")

    transition = controller.save_recipe("标准流程", _recipe_steps())

    assert transition.success is True
    assert transition.recipe_id is not None
    assert transition.view_state is not None
    assert transition.view_state.selected_recipe_id == transition.recipe_id
    assert transition.view_state.recipe_name == "标准流程"
    assert len(transition.view_state.options) == 1

    recipe = db.get_recipe(transition.recipe_id)
    assert recipe is not None
    assert recipe["name"] == "标准流程"


def test_recipe_controller_rejects_empty_name(tmp_path):
    _db, controller = _build_recipe_controller(tmp_path, "recipe_validation.db")

    transition = controller.save_recipe("", _recipe_steps())

    assert transition.success is False
    assert transition.user_message == "请填写配方名称"


def test_recipe_controller_updates_recipe(tmp_path):
    db, controller = _build_recipe_controller(tmp_path, "recipe_update.db")
    recipe_id = db.create_recipe("旧配方", _recipe_steps())

    updated_steps = _recipe_steps()
    updated_steps[0]["target_temp_c"] = 950.0
    transition = controller.update_recipe(recipe_id, "新配方", updated_steps)

    assert transition.success is True
    assert transition.view_state is not None
    assert transition.view_state.recipe_name == "新配方"
    assert float(transition.view_state.steps[0]["target_temp_c"]) == 950.0

    recipe = db.get_recipe(recipe_id)
    assert recipe is not None
    assert recipe["name"] == "新配方"


def test_recipe_controller_parses_raw_step_inputs(tmp_path):
    db, controller = _build_recipe_controller(tmp_path, "recipe_raw_input.db")

    transition = controller.save_recipe_input(
        "原始输入配方",
        [
            {
                "step_no": "1",
                "target_temp_c": "900",
                "ramp_rate_cpm": "10",
                "hold_seconds": "600",
                "n2_lpm": "8.0",
                "h2_lpm": "1.0",
                "co_lpm": "0.8",
                "notes": "",
            }
        ],
    )

    assert transition.success is True
    assert transition.recipe_id is not None
    steps = db.get_recipe_steps(transition.recipe_id)
    assert float(steps[0]["target_temp_c"]) == 900.0


def test_recipe_controller_rejects_invalid_raw_number(tmp_path):
    _db, controller = _build_recipe_controller(tmp_path, "recipe_invalid_input.db")

    transition = controller.save_recipe_input(
        "非法输入配方",
        [
            {
                "step_no": "1",
                "target_temp_c": "abc",
                "ramp_rate_cpm": "10",
                "hold_seconds": "600",
                "n2_lpm": "8.0",
                "h2_lpm": "1.0",
                "co_lpm": "0.8",
                "notes": "",
            }
        ],
    )

    assert transition.success is False
    assert transition.user_message is not None
    assert "存在非法数字" in transition.user_message
