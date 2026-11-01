"""Generic short-lived background tasks (exports, reports) with explicit state transitions.

    queued -> running -> completed | failed
    running -> cancelling -> cancelled

A cancel request never pretends the task stopped: the task reports ``cancelling`` until
its worker observes the request and finishes cleanup. A task already in a terminal state
is never rewritten by a late cancel.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

TERMINAL = frozenset({"completed", "failed", "cancelled"})
MAX_HISTORY = 50


class TaskCancelled(Exception):
    """Raised inside a worker when it observes the cancel request at a safe point."""


class TaskConflict(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskContext:
    cancel_event: threading.Event
    _progress: Callable[[float, str], None]

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise TaskCancelled()

    def progress(self, fraction: float, phase: str) -> None:
        self._progress(max(0.0, min(1.0, fraction)), phase)


@dataclass
class Task:
    task_id: str
    kind: str
    input: dict[str, Any]
    status: str = "queued"
    phase: str = ""
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=_now)
    started_at: str | None = None
    finished_at: str | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    monotonic_started: float | None = field(default=None, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.task_id, "kind": self.kind, "status": self.status, "phase": self.phase,
                "progress": self.progress, "input": dict(self.input), "result": self.result,
                "error": self.error, "created_at": self.created_at, "started_at": self.started_at,
                "finished_at": self.finished_at,
            }


Worker = Callable[[TaskContext, dict[str, Any]], dict[str, Any]]


class TaskRegistry:
    """Runs workers on daemon threads with a bounded concurrency and bounded history."""

    def __init__(self, *, max_concurrent: int = 2, max_history: int = MAX_HISTORY) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.RLock()
        self._slots = threading.BoundedSemaphore(max_concurrent)
        self._threads: list[threading.Thread] = []
        self._max_history = max_history
        self._closing = False

    def submit(self, kind: str, payload: dict[str, Any], worker: Worker, *, dedupe_key: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._closing:
                raise TaskConflict("服务正在关闭，不再接受新任务")
            if dedupe_key is not None:
                for task in self._tasks.values():
                    if task.status not in TERMINAL and task.input.get("_dedupe") == dedupe_key:
                        # Repeated clicks return the task already in flight instead of a duplicate.
                        return task.snapshot()
            while len(self._tasks) >= self._max_history:
                oldest = next((task_id for task_id, task in self._tasks.items() if task.status in TERMINAL), None)
                if oldest is None:
                    raise TaskConflict("后台任务过多，请等待当前任务结束")
                self._tasks.pop(oldest)
            payload = dict(payload)
            if dedupe_key is not None:
                payload["_dedupe"] = dedupe_key
            task = Task(uuid.uuid4().hex, kind, payload)
            self._tasks[task.task_id] = task
            thread = threading.Thread(target=self._run, args=(task, worker), name=f"task-{kind}-{task.task_id[:8]}", daemon=True)
            self._threads.append(thread)
            thread.start()
        return task.snapshot()

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
        return task.snapshot() if task else None

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            tasks = list(self._tasks.values())
        return [task.snapshot() for task in reversed(tasks[-limit:])]

    def cancel(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return None
        with task.lock:
            if task.status in TERMINAL:
                return task.snapshot()
            task.cancel_event.set()
            if task.status == "running":
                task.status = "cancelling"
            else:  # queued: the worker will observe the flag before doing any work
                task.status = "cancelling"
        return task.snapshot()

    def close(self, timeout: float = 30.0) -> None:
        with self._lock:
            self._closing = True
            tasks = list(self._tasks.values())
            threads = list(self._threads)
        for task in tasks:
            task.cancel_event.set()
        deadline = time.monotonic() + timeout
        for thread in threads:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                thread.join(remaining)

    def _run(self, task: Task, worker: Worker) -> None:
        def progress(fraction: float, phase: str) -> None:
            with task.lock:
                if task.status in TERMINAL:
                    return
                task.progress = fraction
                task.phase = phase

        with self._slots:
            with task.lock:
                if task.cancel_event.is_set():
                    task.status = "cancelled"
                    task.finished_at = _now()
                    return
                task.status = "running"
                task.started_at = _now()
                task.monotonic_started = time.monotonic()
            status, result, error = "completed", None, None
            try:
                result = worker(TaskContext(task.cancel_event, progress), dict(task.input))
            except TaskCancelled:
                status = "cancelled"
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller, logged with trace
                logger.exception("task %s (%s) failed", task.task_id, task.kind)
                status, error = "failed", f"{type(exc).__name__}: {exc}"
            with task.lock:
                task.status = status
                task.result = result
                task.error = error
                task.progress = 1.0 if status == "completed" else task.progress
                task.finished_at = _now()
