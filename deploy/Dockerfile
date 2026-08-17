# syntax=docker/dockerfile:1
#
# Образ на базе uv: нужный Python приезжает вместе с зависимостями,
# поэтому сборка не зависит от того, что лежит в репозиториях хостовой ОС.
# Собирается и запускается одинаково в docker и podman.

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    # `uv run` неявно синхронизирует окружение и без этого втащит обратно
    # dev-группу, отброшенную предыдущим `uv sync --no-dev`.
    UV_NO_DEV=1

WORKDIR /app

# Зависимости отдельным слоем: пересобирается только при правке lock-файла.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# Статику собираем на этапе сборки. Настоящие секреты и БД тут не нужны —
# collectstatic до базы не дотягивается.
RUN SECRET_KEY=build-time-only \
    DATABASE_URL=postgres://build:build@localhost/build \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    uv run --no-dev manage.py collectstatic --noinput --clear


FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.prod

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app
COPY --from=builder --chown=app:app /app /app

# Сам каталог /app создаётся WORKDIR от root, а COPY --chown задаёт владельца
# только содержимому. Без этого gunicorn 26 не может создать /app/.gunicorn.
#
# .keep в media — не украшение. На это место монтируется том, и владельца
# каталога том перенимает у образа только тогда, когда каталог непустой:
# у пустого получается root:root, и приложение, работающее под app, не может
# сохранить ни фото докладчика, ни PDF аннотации.
RUN chown app:app /app \
    && mkdir -p /app/media \
    && touch /app/media/.keep \
    && chown -R app:app /app/media
USER app

EXPOSE 8000
ENTRYPOINT ["/app/deploy/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-"]
