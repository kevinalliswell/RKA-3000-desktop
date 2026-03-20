from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QComboBox, QPushButton

from rka_desktop.controllers.experiment_controller import ControllerTransition, RuntimeViewState
from rka_desktop.controllers.history_export_controller import HistoryTransition, HistoryViewState
from rka_desktop.controllers.recipe_controller import RecipeTransition, RecipeViewState
from rka_desktop.ui.alarm_page import AlarmPage
from rka_desktop.ui.history_page import HistoryPage
from rka_desktop.ui.monitor_page import MonitorPage
from rka_desktop.ui.recipe_page import RecipePage


class MainWindowPresenter:
    def __init__(
        self,
        *,
        recipe_combo: QComboBox,
        recipe_page: RecipePage,
        monitor_page: MonitorPage,
        history_page: HistoryPage,
        alarm_page: AlarmPage,
        btn_start: QPushButton,
        btn_pause: QPushButton,
        btn_resume: QPushButton,
        btn_stop: QPushButton,
        btn_export_csv: QPushButton,
        btn_export_excel: QPushButton,
        log_sink: Callable[[str], None],
        stop_worker: Callable[[], None],
        active_experiment_id_provider: Callable[[], int | None],
    ) -> None:
        self.recipe_combo = recipe_combo
        self.recipe_page = recipe_page
        self.monitor_page = monitor_page
        self.history_page = history_page
        self.alarm_page = alarm_page
        self.btn_start = btn_start
        self.btn_pause = btn_pause
        self.btn_resume = btn_resume
        self.btn_stop = btn_stop
        self.btn_export_csv = btn_export_csv
        self.btn_export_excel = btn_export_excel
        self._log_sink = log_sink
        self._stop_worker = stop_worker
        self._active_experiment_id_provider = active_experiment_id_provider

    def show_connected(self) -> None:
        self.monitor_page.show_connected()

    def reset_monitor_runtime(self) -> None:
        self.monitor_page.reset_runtime()

    def apply_experiment_transition(self, transition: ControllerTransition) -> None:
        if transition.final_status is not None:
            self.reset_runtime_ui()
        if transition.view_state is None and transition.update is not None:
            self.monitor_page.update_execution_state(transition.update.status_text, transition.update.active_setpoints_text)
        if transition.view_state is not None:
            self._apply_runtime_view_state(transition.view_state)
        for log in transition.logs:
            self._log_sink(log)

    def apply_recipe_transition(self, transition: RecipeTransition) -> None:
        if transition.view_state is not None:
            self._apply_recipe_view_state(transition.view_state)
        for log in transition.logs:
            self._log_sink(log)

    def apply_history_transition(self, transition: HistoryTransition) -> None:
        if transition.view_state is not None:
            self._apply_history_view_state(transition.view_state)
        for log in transition.logs:
            self._log_sink(log)

    def reset_runtime_ui(self) -> None:
        self._stop_worker()
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.alarm_page.btn_ack_alarm.setEnabled(False)
        self.alarm_page.btn_reset_interlock.setEnabled(False)
        self.alarm_page.set_current_interlock("当前联锁: 无联锁")

    def _apply_runtime_view_state(self, view_state: RuntimeViewState) -> None:
        if view_state.execution_text is not None and view_state.setpoints_text is not None:
            self.monitor_page.update_execution_state(view_state.execution_text, view_state.setpoints_text)
        if view_state.current_alarm_text is not None:
            self.alarm_page.set_current_alarm(view_state.current_alarm_text)
        if view_state.current_interlock_text is not None:
            self.alarm_page.set_current_interlock(view_state.current_interlock_text)
        if view_state.monitor_alarm_text is not None and view_state.monitor_alarm_style is not None:
            self.monitor_page.update_alarm_text(view_state.monitor_alarm_text, view_state.monitor_alarm_style)
        if view_state.monitor_interlock_text is not None and view_state.monitor_interlock_style is not None:
            self.monitor_page.update_interlock_text(view_state.monitor_interlock_text, view_state.monitor_interlock_style)
        if (
            view_state.run_control_word is not None
            and view_state.estop_status is not None
            and view_state.control_feedback_text is not None
            and view_state.control_feedback_style is not None
        ):
            self.monitor_page.update_control_state(
                view_state.run_control_word,
                view_state.estop_status,
                view_state.control_feedback_text,
                view_state.control_feedback_style,
            )
        self.alarm_page.set_pending_alarms(view_state.pending_alarms)
        if view_state.ack_alarm_enabled is not None:
            self.alarm_page.btn_ack_alarm.setEnabled(view_state.ack_alarm_enabled)
        if view_state.reset_interlock_enabled is not None:
            self.alarm_page.btn_reset_interlock.setEnabled(view_state.reset_interlock_enabled)
        if view_state.start_enabled is not None:
            self.btn_start.setEnabled(view_state.start_enabled)
        if view_state.pause_enabled is not None:
            self.btn_pause.setEnabled(view_state.pause_enabled)
        if view_state.resume_enabled is not None:
            self.btn_resume.setEnabled(view_state.resume_enabled)
        if view_state.stop_enabled is not None:
            self.btn_stop.setEnabled(view_state.stop_enabled)

    def _apply_recipe_view_state(self, view_state: RecipeViewState) -> None:
        current_id = self.recipe_combo.currentData()
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.recipe_combo.addItem("请选择配方", 0)
        for option in view_state.options:
            self.recipe_combo.addItem(option.label, option.recipe_id)
        selected_id = view_state.selected_recipe_id or current_id or 0
        index = self.recipe_combo.findData(selected_id)
        if index >= 0:
            self.recipe_combo.setCurrentIndex(index)
        else:
            self.recipe_combo.setCurrentIndex(0)
        self.recipe_combo.blockSignals(False)

        if selected_id in (None, 0):
            self.recipe_page.load_recipe("", [])
            return
        self.recipe_page.load_recipe(view_state.recipe_name, view_state.steps)

    def _apply_history_view_state(self, view_state: HistoryViewState) -> None:
        self.history_page.set_experiments(view_state.experiments, view_state.selected_experiment_id)
        self.history_page.set_summary(view_state.summary_text)
        export_enabled = view_state.export_enabled or self._active_experiment_id_provider() is not None
        self.btn_export_csv.setEnabled(export_enabled)
        self.btn_export_excel.setEnabled(export_enabled)
