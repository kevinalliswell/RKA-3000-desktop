from __future__ import annotations

from collections.abc import Callable

from rka_desktop.core.config import Settings
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.services.acquisition_service import AcquisitionWorker


class RuntimeCoordinator:
    def __init__(
        self,
        *,
        settings: Settings,
        db: DatabaseManager,
        gateway: DeviceGateway,
        on_snapshot: Callable[[object], None],
        on_error: Callable[[str], None],
    ) -> None:
        self._settings = settings
        self._db = db
        self._gateway = gateway
        self._on_snapshot = on_snapshot
        self._on_error = on_error
        self._worker: AcquisitionWorker | object | None = None

    @property
    def worker(self):
        return self._worker

    @worker.setter
    def worker(self, value) -> None:
        self._worker = value

    @property
    def is_running(self) -> bool:
        return self._worker is not None

    def start(self, experiment_id: int) -> AcquisitionWorker:
        worker = AcquisitionWorker(
            client=self._gateway,
            db=self._db,
            experiment_id=experiment_id,
            poll_interval_ms=self._settings.poll_interval_ms,
            batch_size=self._settings.acquisition_batch_size,
        )
        worker.snapshot_received.connect(self._on_snapshot)
        worker.error_occurred.connect(self._on_error)
        worker.start()
        self._worker = worker
        return worker

    def stop(self) -> None:
        if self._worker is None:
            return
        stop = getattr(self._worker, "stop", None)
        if callable(stop):
            stop()
        self._worker = None
