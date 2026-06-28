import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from rka_desktop.ui.components import Card, MetricTile


def _app():
    return QApplication.instance() or QApplication([])


def test_metric_tile_renders_and_updates():
    _app()
    tile = MetricTile("终态还原度", "--", "%", icon="mdi.check-decagram-outline")
    assert tile.objectName() == "metricTile"
    assert tile.value() == "--"
    tile.set_value("96.31")
    assert tile.value() == "96.31"


def test_metric_tile_without_icon():
    _app()
    tile = MetricTile("温度", "900.0", "℃")
    assert tile.value() == "900.0"


def test_card_holds_title_and_body_widgets():
    _app()
    card = Card("关键指标")
    assert card.objectName() == "card"
    card.add_widget(MetricTile("a", "1"))
    card.add_widget(QLabel("note"))
    assert card.body.count() == 2


def test_card_header_widget():
    _app()
    card = Card("历史")
    card.add_header_widget(QPushButton("刷新"))
    # header row exists with title + stretch + button
    assert card._header_row is not None
