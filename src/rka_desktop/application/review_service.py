"""Review and archive: the last step of an experiment; afterwards it is read-only."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from rka_desktop.application.analysis_service import AnalysisService
from rka_desktop.application.ports import AlarmStore, AuditStore, ExperimentStore
from rka_desktop.domain.review import assess_review, sampling_stats


class ArchiveRefused(ValueError):
    pass


class ReviewService:
    def __init__(self, experiments: ExperimentStore, alarms: AlarmStore, audit: AuditStore, analysis: AnalysisService, *,
                 poll_interval_s: float, safe_temperature_c: float, is_active: Callable[[int], bool]) -> None:
        self._experiments = experiments
        self._alarms = alarms
        self._audit = audit
        self._analysis = analysis
        self._poll = poll_interval_s
        self._safe = safe_temperature_c
        self._is_active = is_active

    def review(self, experiment_id: int) -> dict[str, Any]:
        detail = self._experiments.get_experiment_detail(experiment_id)
        if detail is None:
            raise LookupError("实验不存在")
        stats = sampling_stats(self._experiments.fetch_measurement_timestamps(experiment_id), self._poll)
        alarms = self._alarms.list_alarm_history(experiment_id=experiment_id, limit=200)
        unacked = sum(1 for alarm in alarms if not alarm.get("acknowledged_at"))
        assessment = assess_review(
            review_state=detail.get("review_state"), active=self._is_active(experiment_id), stats=stats,
            alarms_total=len(alarms), alarms_unacknowledged=unacked, recipe_version=detail.get("recipe_version"),
            has_recipe_snapshot=bool(detail.get("recipe_snapshot")),
            audit_count=self._audit.count_audit(experiment_id),
            manual_gas_count=self._audit.count_audit(experiment_id, "MANUAL_GAS_SET"),
            purge_required_s=detail.get("purge_required_s"), purge_done_s=detail.get("purge_done_s"),
            final_temperature_c=detail.get("final_temperature_c"), safe_temperature_c=self._safe,
            initial_mass_g=detail.get("initial_mass_g"), final_mass_g=detail.get("final_mass_g"),
            end_reason=detail.get("end_reason"),
        )
        return {"experiment": detail, "stats": stats.to_dict(), "alarms": alarms, **assessment.to_dict()}

    def archive(self, experiment_id: int, note: Any, *, actor: Any = None) -> dict[str, Any]:
        review = self.review(experiment_id)
        if not review["can_archive"]:
            blocked = [c["detail"] for c in review["checks"] if c["severity"] == "block"]
            raise ArchiveRefused("不能归档：" + "；".join(blocked))
        text = note.strip()[:500] if isinstance(note, str) else ""
        if review["note_required"] and len(text) < 2:
            raise ArchiveRefused("复核存在需说明的项目，请填写复核备注（至少 2 个字）")
        who = (actor.strip() if isinstance(actor, str) and actor.strip() else "operator")[:40]
        kpi = self._analysis.kpi(experiment_id)
        self._experiments.update_experiment(experiment_id, {
            "review_state": "archived", "archived_at": datetime.now().isoformat(), "archive_note": text,
            "archived_by": who, "kpi": kpi,
        })
        warned = [c["label"] for c in review["checks"] if c["severity"] == "warn"]
        self._audit.log_action(who, "EXPERIMENT_ARCHIVE",
                               "已归档，原始数据、配方快照、事件与报警冻结为只读" + (f" · 说明项：{'、'.join(warned)}" if warned else ""),
                               experiment_id=experiment_id, category="data", reason=text or None, result="applied")
        return self.review(experiment_id)
