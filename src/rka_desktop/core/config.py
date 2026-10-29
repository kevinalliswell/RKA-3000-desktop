from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_name: str = "RKA Desktop"
    db_path: str = "data/rka.db"
    serial_port: str = "/dev/tty.usbserial-0001"
    baudrate: int = 9600
    modbus_unit_id: int = 1
    mapping_profile: str = "contract_v1"
    simulation_mode: bool = True
    device_profile_path: str = ""
    poll_interval_ms: int = 500
    acquisition_batch_size: int = 10
    step_heatup_grace_seconds: int = 120
    step_total_grace_seconds: int = 180

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)
