import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.ui.main_window import MainWindow


def test_main_window_smoke(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings(
        db_path=str(tmp_path / "ui.db"),
        simulation_mode=True,
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)

    window = MainWindow(settings=settings, db=db, client=client)

    assert window.tabs.count() == 4
    assert window.recipe_page.recipe_table.columnCount() == 8
    assert window.alarm_page.btn_ack_alarm.isEnabled() is False

    window.close()
    app.quit()

