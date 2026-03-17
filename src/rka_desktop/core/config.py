from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "dev"
    app_name: str = "RKA Desktop"
    db_path: str = "data/rka.db"
    serial_port: str = "/dev/tty.usbserial-0001"
    baudrate: int = 9600
    modbus_unit_id: int = 1
    simulation_mode: bool = True
    poll_interval_ms: int = 500

    # MFC 串口配置（MQV 系列质量流量控制器，6 通道）
    mfc_serial_port: str = "/dev/tty.usbserial-0002"
    mfc_baudrate: int = 9600
    # 各通道满量程（L/min），以逗号分隔，顺序对应 CH1–CH6
    # CH1=H2, CH2=N2, CH3=CO, CH4=CO2, CH5=Ar, CH6=CH4
    mfc_full_scales: str = "1.0,10.0,5.0,5.0,5.0,5.0"
    # 各通道机器地址（2 位十六进制），以逗号分隔
    mfc_machine_addrs: str = "01,02,03,04,05,06"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def db_file(self) -> Path:
        return Path(self.db_path)
