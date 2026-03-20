from __future__ import annotations

from rka_desktop.core.modbus_client import ModbusRtuClient, RunControlFeedbackStatus
from rka_desktop.models.entities import DeviceSnapshot


class DeviceGateway:
    def __init__(self, client: ModbusRtuClient) -> None:
        self._client = client

    @property
    def client(self) -> ModbusRtuClient:
        return self._client

    def connect(self) -> bool:
        return self._client.connect()

    def close(self) -> None:
        self._client.close()

    def read_snapshot(self) -> DeviceSnapshot:
        return self._client.read_snapshot()

    def apply_setpoints(
        self,
        *,
        temperature_c: float,
        ramp_rate_cpm: float,
        n2_lpm: float,
        h2_lpm: float,
        co_lpm: float,
    ) -> dict[str, float]:
        return self._client.apply_setpoints(
            temperature_c=temperature_c,
            ramp_rate_cpm=ramp_rate_cpm,
            n2_lpm=n2_lpm,
            h2_lpm=h2_lpm,
            co_lpm=co_lpm,
        )

    def issue_run_control(self, command: str) -> int:
        return self._client.issue_run_control(command)

    def evaluate_run_control_feedback(self, feedback_word: int) -> RunControlFeedbackStatus:
        return self._client.evaluate_run_control_feedback(feedback_word)
