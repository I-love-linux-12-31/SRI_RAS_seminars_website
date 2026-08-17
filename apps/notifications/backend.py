"""БД-бэкенд для django.tasks.

В Django 6.1 штатных бэкендов только два — dummy и immediate, — поэтому
очередь в базе приходится реализовывать самим. Реализация намеренно сидит
за BaseTaskBackend: точки вызова пользуются обычными @task и .enqueue(),
и переход на официальный БД-бэкенд (ожидается в 6.2) сведётся к правке
TASKS в настройках плюс миграции данных.

Транзакционность достаётся бесплатно: при ATOMIC_REQUESTS вставка задачи
попадает в ту же транзакцию, что и бизнес-данные. Заявка на семинар и
письмо о ней либо сохраняются вместе, либо не сохраняются вовсе.
"""

from django.tasks.backends.base import BaseTaskBackend
from django.tasks.base import TaskResultStatus
from django.tasks.exceptions import TaskResultDoesNotExist
from django.tasks.signals import task_enqueued
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.json import normalize_json

from .models import TaskRecord


class DatabaseTaskBackend(BaseTaskBackend):
    supports_defer = True
    supports_get_result = True
    supports_priority = True
    # Воркер синхронный: корутины не принимаем, чтобы не обещать лишнего.
    supports_async_task = False

    def enqueue(self, task, args, kwargs):
        self.validate_task(task)

        record = TaskRecord.objects.create(
            id=get_random_string(32),
            task_path=task.module_path,
            args=normalize_json(list(args)),
            kwargs=normalize_json(dict(kwargs)),
            priority=task.priority,
            queue_name=task.queue_name,
            backend_alias=self.alias,
            takes_context=task.takes_context,
            run_after=task.run_after,
            status=TaskResultStatus.READY,
            enqueued_at=timezone.now(),
        )

        result = record.to_task_result()
        task_enqueued.send(type(self), task_result=result)
        return result

    def get_result(self, result_id):
        try:
            return TaskRecord.objects.get(id=result_id).to_task_result()
        except TaskRecord.DoesNotExist as exc:
            raise TaskResultDoesNotExist(result_id) from exc
