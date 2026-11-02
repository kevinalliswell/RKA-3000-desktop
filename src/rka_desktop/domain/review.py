"""Review before archiving: what an operator must see before an experiment becomes read-only.

Each check has a severity:

* ``ok``    — nothing to do;
* ``warn``  — archiving is allowed but the reviewer must write a note explaining it;
* ``block`` — archiving is refused until the cause is resolved (for example an unacknowledged
  alarm, or the experiment is still running).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

GAP_PERIODS = 3


@dataclass(frozen=True)
class SamplingStats:
    count: int
    gaps: int
    gap_seconds: float
    reversals: int
    duration_seconds: float

    @property
    def complete(self) -> bool:
        return self.count > 0 and self.gaps == 0 and self.reversals == 0

    def to_dict(self) -> dict[str, Any]:
        return {"count": self.count, "gaps": self.gaps, "gap_seconds": round(self.gap_seconds, 1),
                "reversals": self.reversals, "duration_seconds": round(self.duration_seconds, 1), "complete": self.complete}


def sampling_stats(timestamps: list[str], poll_interval_s: float) -> SamplingStats:
    """Gaps are intervals longer than ``GAP_PERIODS`` sampling periods; reversals are time going back."""
    threshold = GAP_PERIODS * poll_interval_s
    parsed: list[datetime] = []
    for value in timestamps:
        try:
            parsed.append(datetime.fromisoformat(str(value)))
        except ValueError:
            continue
    gaps = 0
    gap_seconds = 0.0
    reversals = 0
    for previous, current in zip(parsed, parsed[1:]):
        delta = (current - previous).total_seconds()
        if delta < 0:
            reversals += 1
        elif delta > threshold:
            gaps += 1
            gap_seconds += delta
    duration = (max(parsed) - min(parsed)).total_seconds() if len(parsed) > 1 else 0.0
    return SamplingStats(len(parsed), gaps, gap_seconds, reversals, duration)


@dataclass(frozen=True)
class ReviewCheck:
    key: str
    label: str
    severity: str  # ok | warn | block
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "severity": self.severity, "detail": self.detail}


@dataclass(frozen=True)
class ReviewAssessment:
    checks: tuple[ReviewCheck, ...]

    @property
    def can_archive(self) -> bool:
        return all(check.severity != "block" for check in self.checks)

    @property
    def note_required(self) -> bool:
        return any(check.severity == "warn" for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {"checks": [c.to_dict() for c in self.checks], "can_archive": self.can_archive,
                "note_required": self.note_required}


def assess_review(
    *,
    review_state: str | None,
    active: bool,
    stats: SamplingStats,
    alarms_total: int,
    alarms_unacknowledged: int,
    recipe_version: int | None,
    has_recipe_snapshot: bool,
    audit_count: int,
    manual_gas_count: int,
    purge_required_s: float | None,
    purge_done_s: float | None,
    final_temperature_c: float | None,
    safe_temperature_c: float,
    initial_mass_g: float | None,
    final_mass_g: float | None,
    end_reason: str | None,
) -> ReviewAssessment:
    checks: list[ReviewCheck] = []
    if active:
        checks.append(ReviewCheck("state", "实验状态", "block", "实验仍在运行或处置中，结束后才能归档"))
    elif review_state == "archived":
        checks.append(ReviewCheck("state", "实验状态", "block", "已归档，只读"))
    else:
        checks.append(ReviewCheck("state", "实验状态", "ok", "已结束 · 待核查"))

    if stats.count == 0:
        checks.append(ReviewCheck("sampling", "原始采样完整性", "warn", "没有采样数据"))
    elif stats.complete:
        checks.append(ReviewCheck("sampling", "原始采样完整性", "ok", f"{stats.count} 点 · 无缺口 · 无时间倒退"))
    else:
        parts = []
        if stats.gaps:
            parts.append(f"{stats.gaps} 处缺口共 {stats.gap_seconds:.0f} s")
        if stats.reversals:
            parts.append(f"{stats.reversals} 处时间倒退")
        checks.append(ReviewCheck("sampling", "原始采样完整性", "warn", f"{stats.count} 点 · " + "，".join(parts)))

    if alarms_unacknowledged:
        checks.append(ReviewCheck("alarms", "报警与确认", "block", f"{alarms_unacknowledged} 条报警未确认，请先在报警页确认"))
    elif alarms_total:
        checks.append(ReviewCheck("alarms", "报警与确认", "warn", f"运行期间 {alarms_total} 条报警，均已确认"))
    else:
        checks.append(ReviewCheck("alarms", "报警与确认", "ok", "运行期间无报警"))

    if has_recipe_snapshot:
        checks.append(ReviewCheck("recipe", "配方快照", "ok", f"v{recipe_version} · 启动时冻结，不受后续修改影响"))
    else:
        checks.append(ReviewCheck("recipe", "配方快照", "warn", "旧版本实验没有配方快照"))

    detail = f"{audit_count} 条"
    if manual_gas_count:
        detail += f" · 含 {manual_gas_count} 次手动调气（原因已记录）"
    checks.append(ReviewCheck("audit", "操作记录", "ok", detail))

    if purge_required_s is None:
        checks.append(ReviewCheck("safe_finish", "安全完成依据", "warn", "没有处置记录（旧版本实验或处置未完成）"))
    else:
        done = purge_done_s or 0.0
        temp_ok = final_temperature_c is not None and final_temperature_c < safe_temperature_c
        if done >= purge_required_s and temp_ok:
            checks.append(ReviewCheck("safe_finish", "安全完成依据", "ok",
                                      f"吹扫 {done:.0f} s ≥ {purge_required_s:.0f} s · 处置后炉温 {final_temperature_c:.0f} ℃ < {safe_temperature_c:.0f} ℃"))
        else:
            temp_text = f"{final_temperature_c:.0f} ℃" if final_temperature_c is not None else "未知"
            checks.append(ReviewCheck("safe_finish", "安全完成依据", "warn",
                                      f"处置未按条件完成：吹扫 {done:.0f} / {purge_required_s:.0f} s，炉温 {temp_text}"))

    if initial_mass_g and final_mass_g is not None:
        checks.append(ReviewCheck("mass", "质量基准", "ok", f"初始 {initial_mass_g:.3f} g · 终态 {final_mass_g:.3f} g"))
    else:
        checks.append(ReviewCheck("mass", "质量基准", "warn", "缺少初始质量或终态读数，无法计算指标"))

    if end_reason and end_reason != "completed":
        checks.append(ReviewCheck("ending", "结束方式", "warn", END_REASON_LABELS.get(end_reason, end_reason)))
    return ReviewAssessment(tuple(checks))


END_REASON_LABELS = {
    "completed": "配方最后一段正常完成",
    "operator_stop": "操作者提前结束",
    "emergency": "紧急停气",
    "alarm": "报警自动处置",
    "fault": "设备或执行故障",
    "shutdown": "程序关闭时中止",
    "recovered": "程序异常退出，重启后标记为中止",
}
