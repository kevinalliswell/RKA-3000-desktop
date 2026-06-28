import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton

from rka_desktop.ui import theme


def _app():
    return QApplication.instance() or QApplication([])


def test_apply_theme_runs_and_sets_stylesheet():
    app = _app()
    theme.apply_theme(app)
    assert app.styleSheet()  # non-empty combined stylesheet
    assert "primary" in app.styleSheet()  # brand override present


def test_make_primary_and_danger_set_object_names():
    _app()
    assert theme.make_primary(QPushButton("x")).objectName() == "primary"
    assert theme.make_danger(QPushButton("y")).objectName() == "danger"


def test_accent_pen_returns_styled_pen():
    _app()
    pen = theme.accent_pen(theme.ACCENT, 3)
    assert pen.width() == 3
    assert pen.color().name().lower() == theme.ACCENT.lower()
