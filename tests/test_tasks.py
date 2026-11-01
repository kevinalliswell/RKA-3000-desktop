import threading
import time

import pytest

from rka_desktop.application.tasks import TaskCancelled, TaskConflict, TaskRegistry


def wait(registry, task_id, status, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = registry.get(task_id)
        if task["status"] == status:
            return task
        time.sleep(0.005)
    pytest.fail(f"task did not reach {status}: {registry.get(task_id)['status']}")


def test_task_completes_with_result_and_progress():
    registry = TaskRegistry()

    def worker(context, payload):
        context.progress(0.5, "half")
        return {"value": payload["x"] * 2}

    task = registry.submit("double", {"x": 21}, worker)
    assert task["status"] in {"queued", "running", "completed"}
    done = wait(registry, task["id"], "completed")
    assert done["result"] == {"value": 42} and done["progress"] == 1.0 and done["finished_at"]
    # a late cancel must not rewrite a terminal task
    assert registry.cancel(task["id"])["status"] == "completed"
    registry.close()


def test_cancel_is_a_request_until_worker_cleans_up():
    registry = TaskRegistry()
    started, release = threading.Event(), threading.Event()
    cleaned = threading.Event()

    def worker(context, payload):
        started.set()
        try:
            release.wait(2)
            context.check_cancelled()
            return {"ok": True}
        finally:
            cleaned.set()

    task = registry.submit("slow", {}, worker)
    assert started.wait(1)
    assert registry.cancel(task["id"])["status"] == "cancelling"
    assert not cleaned.is_set()
    release.set()
    final = wait(registry, task["id"], "cancelled")
    assert cleaned.is_set() and final["result"] is None
    registry.close()


def test_failure_is_reported_and_dedupe_returns_in_flight_task():
    registry = TaskRegistry(max_concurrent=1)
    gate = threading.Event()

    def blocked(context, payload):
        gate.wait(2)
        return {}

    def failing(context, payload):
        raise RuntimeError("disk full")

    first = registry.submit("export", {"k": 1}, blocked, dedupe_key="export:1")
    again = registry.submit("export", {"k": 1}, blocked, dedupe_key="export:1")
    assert again["id"] == first["id"]
    failed = registry.submit("export", {"k": 2}, failing)
    gate.set()
    assert wait(registry, failed["id"], "failed")["error"] == "RuntimeError: disk full"
    wait(registry, first["id"], "completed")
    assert registry.get("missing") is None and registry.cancel("missing") is None
    registry.close()


def test_close_rejects_new_tasks_and_history_is_bounded():
    registry = TaskRegistry(max_history=3)
    for index in range(5):
        wait(registry, registry.submit("quick", {"i": index}, lambda c, p: {})["id"], "completed")
    assert len(registry.list(limit=10)) == 3
    registry.close()
    with pytest.raises(TaskConflict):
        registry.submit("quick", {}, lambda c, p: {})


def test_task_cancelled_exception_type():
    assert issubclass(TaskCancelled, Exception)
