from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from rka_desktop.core.alarm_rules import alarm_text_from_word
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import DeviceSnapshot, Measurement

logger = logging.getLogger(__name__)


class AcquisitionWorker(QThread):
    snapshot_received = Signal(object)
    error_occurred = Signal(str)

    def __init__(
        self,
        client: ModbusRtuClient,
        db: DatabaseManager,
        experiment_id: int,
        poll_interval_ms: int,
        batch_size: int = 10,
    ) -> None:
        super().__init__()
        self._client = client
        self._db = db
        self._experiment_id = experiment_id
        self._poll_interval_ms = poll_interval_ms
        self._batch_size = max(1, batch_size)
        self._running = False
        self._pending_measurements: list[Measurement] = []

    def run(self) -> None:
        self._running = True
        try:
            while self._running:
                try:
                    snapshot = self._client.read_snapshot()
                    measurement = self._build_measurement(snapshot)
                    self.snapshot_received.emit((snapshot, measurement))
                    self._buffer_measurement(measurement)
                except Exception as exc:  # pragma: no cover
                    logger.exception("Acquisition failed")
                    self.error_occurred.emit(str(exc))

                self.msleep(self._poll_interval_ms)
        finally:
            try:
                self._flush_pending_measurements()
            except Exception as exc:  # pragma: no cover
                logger.exception("Acquisition flush failed")
                self.error_occurred.emit(str(exc))

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    def _build_measurement(self, snapshot: DeviceSnapshot) -> Measurement:
        return Measurement(
            experiment_id=self._experiment_id,
            sampled_at=datetime.now(),
            temperature_c=snapshot.temperature_c,
            weight_g=snapshot.weight_g,
            pressure_mpa=snapshot.pressure_mpa,
            n2_lpm=snapshot.n2_lpm,
            h2_lpm=snapshot.h2_lpm,
            co_lpm=snapshot.co_lpm,
        )

    def _buffer_measurement(self, measurement: Measurement) -> int:
        self._pending_measurements.append(measurement)
        if len(self._pending_measurements) < self._batch_size:
            return 0
        return self._flush_pending_measurements()

    def _flush_pending_measurements(self) -> int:
        if not self._pending_measurements:
            return 0
        pending = self._pending_measurements
        self._pending_measurements = []
        return self._db.insert_measurements(pending)


def alarm_text(snapshot: DeviceSnapshot, profile_name: str = "contract_v1") -> str:
    return alarm_text_from_word(snapshot.alarm_word, profile_name=profile_name)
