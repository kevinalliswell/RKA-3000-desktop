from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from rka_desktop.core.config import Settings
from rka_desktop.core.device_map import get_device_map
from rka_desktop.core.logging_config import setup_logging
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.ui.main_window import MainWindow
from rka_desktop.ui.theme import apply_theme


def main() -> int:
    setup_logging()
    settings = Settings()

    db = DatabaseManager(settings.db_file)
    db.init_schema()

    client = ModbusRtuClient(
        serial_port=settings.serial_port,
        baudrate=settings.baudrate,
        unit_id=settings.modbus_unit_id,
        device_map=get_device_map(settings.mapping_profile),
        simulation_mode=settings.simulation_mode,
    )

    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow(settings=settings, db=db, client=client)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
