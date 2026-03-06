from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.models.entities import DeviceSnapshot, Measurement

logger = logging.getLogger(__name__)


class AcquisitionWorker(QThread):
    snapshot_received = Signal(object)
    error_occurred = Signal(str)

    def __init__(self, client: ModbusRtuClient, experiment_id: int, poll_interval_ms: int) -> None:
        super().__init__()
        self._client = client
        self._experiment_id = experiment_id
        self._poll_interval_ms = poll_interval_ms
        self._running = False

    def run(self) -> None:
        self._running = True
        while self._running:
            try:
                snapshot = self._client.read_snapshot()
                measurement = Measurement(
                    experiment_id=self._experiment_id,
                    sampled_at=datetime.now(),
                    temperature_c=snapshot.temperature_c,
                    weight_g=snapshot.weight_g,
                    pressure_mpa=snapshot.pressure_mpa,
                    n2_lpm=snapshot.n2_lpm,
                    h2_lpm=snapshot.h2_lpm,
                    co_lpm=snapshot.co_lpm,
                )
                self.snapshot_received.emit((snapshot, measurement))
            except Exception as exc:  # pragma: no cover
                logger.exception("Acquisition failed")
                self.error_occurred.emit(str(exc))

            self.msleep(self._poll_interval_ms)

    def stop(self) -> None:
        self._running = False
        self.wait(2000)


def alarm_text(snapshot: DeviceSnapshot) -> str:
    if snapshot.alarm_word == 0:
        return "正常"
    return f"报警字: {snapshot.alarm_word}"
