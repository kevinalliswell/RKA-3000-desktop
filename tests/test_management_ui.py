import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QInputDialog

from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.ui.main_window import MainWindow


def _window(tmp_path, db_name):
    app = QApplication.instance() or QApplication([])
    settings = Settings(db_path=str(tmp_path / db_name), simulation_mode=True)
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    exp_id = db.create_experiment("redox-exp")
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    win = MainWindow(settings=settings, db=db, client=client)
    win._refresh_history()
    win.history_page.table.selectRow(0)
    return app, db, win, exp_id


def test_log_tab_shows_audit_actions(tmp_path):
    app, db, win, _exp = _window(tmp_path, "log.db")
    db.log_action("operator", "DEVICE_CONNECT", "sim")
    win._refresh_logs()
    rows = win.log_page.table.rowCount()
    actions = {win.log_page.table.item(r, 2).text() for r in range(rows)}
    assert "DEVICE_CONNECT" in actions
    win.close()
    app.quit()


def test_delete_experiment_via_ui(tmp_path, monkeypatch):
    app, db, win, exp_id = _window(tmp_path, "del.db")
    monkeypatch.setattr(win.dialogs, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(win.dialogs, "info", lambda *a, **k: None)
    win.delete_experiment()
    assert db.get_experiment_detail(exp_id) is None
    # the deletion is audited and visible in the 日志 tab
    actions = {win.log_page.table.item(r, 2).text() for r in range(win.log_page.table.rowCount())}
    assert "EXPERIMENT_DELETE" in actions
    win.close()
    app.quit()


def test_rename_experiment_via_ui(tmp_path, monkeypatch):
    app, db, win, exp_id = _window(tmp_path, "ren.db")
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("renamed-exp", True)))
    monkeypatch.setattr(win.dialogs, "info", lambda *a, **k: None)
    win.rename_experiment()
    assert db.get_experiment_detail(exp_id)["name"] == "renamed-exp"
    win.close()
    app.quit()
