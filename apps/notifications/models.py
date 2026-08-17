import dataclasses
from typing import ClassVar

from django.db import models
from django.tasks import DEFAULT_TASK_BACKEND_ALIAS, DEFAULT_TASK_QUEUE_NAME
from django.tasks.base import DEFAULT_TASK_PRIORITY, TaskError, TaskResult, TaskResultStatus
from django.utils.module_loading import import_string
from django.utils.translation import gettext_lazy as _


class TaskRecord(models.Model):
    """Хранилище задач для DatabaseTaskBackend.

    Поля повторяют django.tasks.base.TaskResult, чтобы при появлении
    официального БД-бэкенда миграция данных была прямолинейной.
    """

    STATUSES: ClassVar[list[tuple[str, str]]] = [(s.value, s.value) for s in TaskResultStatus]

    id = models.CharField(primary_key=True, max_length=32, editable=False)
    task_path = models.TextField(_("путь к задаче"))
    args = models.JSONField(default=list, blank=True)
    kwargs = models.JSONField(default=dict, blank=True)

    priority = models.SmallIntegerField(default=DEFAULT_TASK_PRIORITY)
    queue_name = models.CharField(max_length=64, default=DEFAULT_TASK_QUEUE_NAME)
    backend_alias = models.CharField(max_length=64, default=DEFAULT_TASK_BACKEND_ALIAS)
    takes_context = models.BooleanField(default=False)

    status = models.CharField(max_length=16, choices=STATUSES, default=TaskResultStatus.READY)
    run_after = models.DateTimeField(null=True, blank=True)
    enqueued_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    last_attempted_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    attempts = models.PositiveSmallIntegerField(default=0)
    errors = models.JSONField(default=list, blank=True)
    worker_ids = models.JSONField(default=list, blank=True)
    return_value = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = _("фоновая задача")
        verbose_name_plural = _("фоновые задачи")
        indexes: ClassVar[list[models.Index]] = [
            # Основной запрос воркера: взять готовую задачу нужной очереди.
            models.Index(fields=["status", "queue_name", "run_after"]),
            models.Index(fields=["-enqueued_at"]),
        ]

    def __str__(self):
        return f"{self.task_path} [{self.status}]"

    def to_task_result(self) -> TaskResult:
        """Собрать обратно django.tasks.base.TaskResult."""
        task = import_string(self.task_path)
        task = dataclasses.replace(
            task,
            priority=self.priority,
            backend=self.backend_alias,
            queue_name=self.queue_name,
            run_after=self.run_after,
        )
        result = TaskResult(
            task=task,
            id=self.id,
            status=TaskResultStatus(self.status),
            enqueued_at=self.enqueued_at,
            started_at=self.started_at,
            last_attempted_at=self.last_attempted_at,
            finished_at=self.finished_at,
            args=self.args,
            kwargs=self.kwargs,
            backend=self.backend_alias,
            errors=[TaskError(**e) for e in self.errors],
            worker_ids=list(self.worker_ids),
        )
        # _return_value помечено приватным и в конструктор не принимается.
        object.__setattr__(result, "_return_value", self.return_value)
        return result
