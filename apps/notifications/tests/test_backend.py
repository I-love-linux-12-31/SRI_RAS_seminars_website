"""Проверки собственного БД-бэкенда django.tasks.

Тесты намеренно ходят через публичное API (@task / .enqueue), а не через
внутренности бэкенда: когда в Django появится штатный БД-бэкенд, эти тесты
должны продолжить проходить без правок.
"""

import pytest
from django.core.management import call_command
from django.tasks import task
from django.tasks.base import TaskResultStatus

from apps.notifications.models import TaskRecord

pytestmark = pytest.mark.django_db

CALLS: list[str] = []


@task()
def record_call(value: str) -> str:
    CALLS.append(value)
    return f"ok:{value}"


@task()
def always_fails() -> None:
    raise RuntimeError("сломалось")


@pytest.fixture(autouse=True)
def _clear_calls():
    CALLS.clear()
    yield
    CALLS.clear()


@pytest.fixture
def db_backend(settings):
    settings.TASKS = {"default": {"BACKEND": "apps.notifications.backend.DatabaseTaskBackend"}}


def test_enqueue_stores_row_without_executing(db_backend):
    result = record_call.enqueue("раз")

    assert CALLS == [], "задача не должна выполняться в момент постановки"
    record = TaskRecord.objects.get(id=result.id)
    assert record.status == TaskResultStatus.READY
    assert record.args == ["раз"]
    assert record.enqueued_at is not None


def test_worker_executes_and_marks_successful(db_backend):
    result = record_call.enqueue("два")

    call_command("run_task_worker")

    assert CALLS == ["два"]
    record = TaskRecord.objects.get(id=result.id)
    assert record.status == TaskResultStatus.SUCCESSFUL
    assert record.return_value == "ok:два"
    assert record.finished_at is not None
    assert record.attempts == 1


def test_worker_drains_queue_and_exits(db_backend):
    for i in range(3):
        record_call.enqueue(str(i))

    call_command("run_task_worker")

    assert sorted(CALLS) == ["0", "1", "2"]
    assert TaskRecord.objects.filter(status=TaskResultStatus.SUCCESSFUL).count() == 3


def test_failure_is_retried_with_backoff(db_backend):
    result = always_fails.enqueue()

    call_command("run_task_worker")

    record = TaskRecord.objects.get(id=result.id)
    # Первая неудача возвращает задачу в очередь с отложенным стартом,
    # а не хоронит её.
    assert record.status == TaskResultStatus.READY
    assert record.attempts == 1
    assert record.run_after is not None
    assert len(record.errors) == 1
    assert "RuntimeError" in record.errors[0]["exception_class_path"]


def test_failure_gives_up_after_max_attempts(db_backend):
    from apps.notifications.management.commands import run_task_worker

    result = always_fails.enqueue()

    for _ in range(run_task_worker.MAX_ATTEMPTS):
        # Сбрасываем задержку, иначе воркер задачу не подхватит.
        TaskRecord.objects.filter(id=result.id).update(run_after=None)
        call_command("run_task_worker")

    record = TaskRecord.objects.get(id=result.id)
    assert record.status == TaskResultStatus.FAILED
    assert record.attempts == run_task_worker.MAX_ATTEMPTS
    assert record.finished_at is not None


def test_get_result_round_trip(db_backend):
    result = record_call.enqueue("три")
    call_command("run_task_worker")

    from django.tasks import task_backends

    refreshed = task_backends["default"].get_result(result.id)
    assert refreshed.status == TaskResultStatus.SUCCESSFUL
    assert refreshed.return_value == "ok:три"
    assert refreshed.args == ["три"]


def test_deferred_task_is_not_picked_up_early(db_backend):
    from datetime import timedelta

    from django.utils import timezone

    result = record_call.using(run_after=timezone.now() + timedelta(hours=1)).enqueue("потом")

    call_command("run_task_worker")

    assert CALLS == []
    assert TaskRecord.objects.get(id=result.id).status == TaskResultStatus.READY


# --- Восстановление после падения воркера -------------------------------------


def test_abandoned_running_task_returns_to_queue(db_backend):
    """Воркер могли убить деплоем прямо во время выполнения задачи.

    Без подбора такая задача навсегда осталась бы в RUNNING, а письмо
    молча пропало бы.
    """
    from datetime import timedelta

    from django.utils import timezone

    from apps.notifications.management.commands.run_task_worker import STUCK_AFTER

    result = record_call.enqueue("брошенная")
    TaskRecord.objects.filter(id=result.id).update(
        status=TaskResultStatus.RUNNING,
        attempts=1,
        last_attempted_at=timezone.now() - STUCK_AFTER - timedelta(minutes=1),
    )

    call_command("run_task_worker")

    assert CALLS == ["брошенная"]
    assert TaskRecord.objects.get(id=result.id).status == TaskResultStatus.SUCCESSFUL


def test_recently_started_task_is_not_stolen(db_backend):
    """Задачу, которую прямо сейчас выполняет живой воркер, трогать нельзя."""
    from django.utils import timezone

    result = record_call.enqueue("в работе")
    TaskRecord.objects.filter(id=result.id).update(
        status=TaskResultStatus.RUNNING, attempts=1, last_attempted_at=timezone.now()
    )

    call_command("run_task_worker")

    assert CALLS == []
    assert TaskRecord.objects.get(id=result.id).status == TaskResultStatus.RUNNING


def test_abandoned_task_out_of_attempts_is_buried(db_backend):
    """Задача, роняющая сам процесс, не должна крутиться вечно."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.notifications.management.commands.run_task_worker import (
        MAX_ATTEMPTS,
        STUCK_AFTER,
    )

    result = record_call.enqueue("безнадёжная")
    TaskRecord.objects.filter(id=result.id).update(
        status=TaskResultStatus.RUNNING,
        attempts=MAX_ATTEMPTS,
        last_attempted_at=timezone.now() - STUCK_AFTER - timedelta(minutes=1),
    )

    call_command("run_task_worker")

    assert CALLS == []
    assert TaskRecord.objects.get(id=result.id).status == TaskResultStatus.FAILED


def test_unimportable_task_does_not_kill_worker(db_backend):
    """Модуль задачи мог быть переименован между постановкой и выполнением."""
    result = record_call.enqueue("сирота")
    TaskRecord.objects.filter(id=result.id).update(task_path="apps.notifications.gone.nope")

    call_command("run_task_worker")

    record = TaskRecord.objects.get(id=result.id)
    assert record.status == TaskResultStatus.READY, "должна уйти в ретрай, а не остаться в RUNNING"
    assert record.attempts == 1
    assert "ModuleNotFoundError" in record.errors[0]["exception_class_path"]
