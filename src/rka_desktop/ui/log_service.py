from __future__ import annotations

import logging

from rka_desktop.ui.monitor_page import MonitorPage


class LogService:
    def __init__(self, monitor_page: MonitorPage, logger_name: str) -> None:
        self._monitor_page = monitor_page
        self._logger = logging.getLogger(logger_name)

    def append(self, message: str) -> None:
        self._logger.info(message)
        self._monitor_page.append_log(message)
