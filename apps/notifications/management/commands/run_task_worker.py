"""Воркер очереди задач.

По умолчанию разбирает очередь и завершается — этот режим и запускается
systemd-таймером раз в минуту. Флаг --loop оставлен для отладки и для
случая, если позже захочется держать постоянный процесс.
"""

import logging
import time
from datetime import timedelta
from traceback import format_exception

from django.core.management.base import BaseCommand
from django.db import models, transaction
from django.tasks import DEFAULT_TASK_QUEUE_NAME
from django.tasks.base import TaskContext, TaskResultStatus
from django.tasks.signals import task_finished, task_started
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.json import normalize_json

from apps.notifications.models import TaskRecord

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
BACKOFF_CAP = timedelta(hours=1)
# Через сколько задача в статусе RUNNING считается брошенной. Воркер могли
# перезапустить деплоем или убить по OOM прямо во время выполнения — без
# подбора такая задача осталась бы в RUNNING навсегда, а письмо потерялось бы.
STUCK_AFTER = timedelta(minutes=15)


class Command(BaseCommand):
    help = "Выполнить задачи из очереди (по умолчанию — до опустошения очереди)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop", action="store_true", help="не завершаться, опрашивать очередь"
        )
        parser.add_argument("--interval", type=float, default=5.0, help="пауза в режиме --loop, с")
        parser.add_argument("--queue", default=DEFAULT_TASK_QUEUE_NAME)
        parser.add_argument("--max-tasks", type=int, default=0, help="0 — без ограничения")

    def handle(self, *args, **options):
        self.worker_id = get_random_string(32)
        queue, limit = options["queue"], options["max_tasks"]
        done = 0

        self._reclaim_abandoned(queue)

        while True:
            record = self._claim(queue)
            if record is None:
                if not options["loop"]:
                    break
                time.sleep(options["interval"])
                continue

            self._run(record)
            done += 1
            if limit and done >= limit:
                break

        if done:
            self.stdout.write(f"выполнено задач: {done}")

    def _reclaim_abandoned(self, queue: str) -> None:
        """Разобрать задачи, брошенные умершим воркером.

        Исчерпавшие попытки хороним сразу: если задача роняет сам процесс
        (например, её модуль больше не импортируется), бесконечный цикл
        «подобрал — упал — подобрал» хуже честного провала.
        """
        cutoff = timezone.now() - STUCK_AFTER
        abandoned = TaskRecord.objects.filter(
            status=TaskResultStatus.RUNNING, queue_name=queue, last_attempted_at__lt=cutoff
        )

        buried = abandoned.filter(attempts__gte=MAX_ATTEMPTS).update(
            status=TaskResultStatus.FAILED, finished_at=timezone.now()
        )
        requeued = abandoned.filter(attempts__lt=MAX_ATTEMPTS).update(
            status=TaskResultStatus.READY, run_after=None
        )

        if buried or requeued:
            logger.warning(
                "Подобрано брошенных задач: возвращено в очередь %s, провалено %s",
                requeued,
                buried,
            )

    def _claim(self, queue: str) -> TaskRecord | None:
        """Атомарно забрать одну задачу. skip_locked даёт безопасную работу нескольких воркеров."""
        now = timezone.now()
        with transaction.atomic():
            record = (
                TaskRecord.objects.select_for_update(skip_locked=True)
                .filter(status=TaskResultStatus.READY, queue_name=queue)
                .filter(models.Q(run_after__isnull=True) | models.Q(run_after__lte=now))
                .order_by("-priority", "enqueued_at")
                .first()
            )
            if record is None:
                return None

            record.status = TaskResultStatus.RUNNING
            record.started_at = record.started_at or now
            record.last_attempted_at = now
            record.attempts += 1
            record.worker_ids = [*record.worker_ids, self.worker_id]
            record.save(
                update_fields=[
                    "status",
                    "started_at",
                    "last_attempted_at",
                    "attempts",
                    "worker_ids",
                ]
            )
            return record

    def _run(self, record: TaskRecord) -> None:
        try:
            # Сборка тоже под защитой: если модуль задачи переименовали или
            # удалили, воркер должен пометить задачу упавшей, а не умереть сам,
            # оставив её навсегда в RUNNING.
            result = record.to_task_result()
            task = result.task
        except Exception as exc:
            self._fail(record, exc)
            return

        task_started.send(sender=type(self), task_result=result)

        try:
            if record.takes_context:
                value = task.call(TaskContext(task_result=result), *record.args, **record.kwargs)
            else:
                value = task.call(*record.args, **record.kwargs)
        except KeyboardInterrupt:
            # Пользователь прерывает работу — вернуть задачу в очередь и выйти.
            record.status = TaskResultStatus.READY
            record.save(update_fields=["status"])
            raise
        except BaseException as exc:
            self._fail(record, exc)
        else:
            record.return_value = normalize_json(value)
            record.status = TaskResultStatus.SUCCESSFUL
            record.finished_at = timezone.now()
            record.save(update_fields=["return_value", "status", "finished_at"])
            self._notify_finished(record)

    def _fail(self, record: TaskRecord, exc: BaseException) -> None:
        exc_type = type(exc)
        record.errors = [
            *record.errors,
            {
                "exception_class_path": f"{exc_type.__module__}.{exc_type.__qualname__}",
                "traceback": "".join(format_exception(exc)),
            },
        ]

        if record.attempts < MAX_ATTEMPTS:
            # Экспоненциальная задержка: 2, 4, 8, 16 минут, но не больше часа.
            delay = min(timedelta(minutes=2**record.attempts), BACKOFF_CAP)
            record.status = TaskResultStatus.READY
            record.run_after = timezone.now() + delay
            logger.warning(
                "Задача %s упала (попытка %s/%s), повтор через %s",
                record.id,
                record.attempts,
                MAX_ATTEMPTS,
                delay,
            )
            record.save(update_fields=["errors", "status", "run_after"])
        else:
            record.status = TaskResultStatus.FAILED
            record.finished_at = timezone.now()
            logger.error(
                "Задача %s окончательно провалена после %s попыток",
                record.id,
                record.attempts,
            )
            record.save(update_fields=["errors", "status", "finished_at"])
            self._notify_finished(record)

    def _notify_finished(self, record: TaskRecord) -> None:
        """Разослать task_finished, не падая на несобираемой задаче.

        Сюда попадают в том числе задачи, упавшие на импорте: пересобрать
        TaskResult для них нельзя, но и ронять воркер из-за сигнала незачем.
        """
        try:
            task_finished.send(sender=type(self), task_result=record.to_task_result())
        except Exception:
            logger.debug("Не удалось собрать TaskResult для сигнала по задаче %s", record.id)
            task_finished.send(sender=type(self), task_result=record.to_task_result())
