"""Thin Celery tasks around app/ingestion/pipeline.py (ADR-0007)."""

from __future__ import annotations

import asyncio
import functools
import logging
import threading
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

from celery import Task
from sqlalchemy.exc import InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.db import make_engine
from app.ingestion import pipeline
from app.providers.embeddings import get_embedder
from app.providers.embeddings.base import EmbeddingUnavailable
from app.providers.llm import get_llm
from app.providers.parser import get_parser
from app.providers.storage import get_storage
from workers.celery_app import celery_app

log = logging.getLogger(__name__)
T = TypeVar("T")

# Worth retrying: provider hiccups and dropped connections. Everything else fails at once.
TRANSIENT = (EmbeddingUnavailable, OperationalError, InterfaceError, ConnectionError, TimeoutError)
MAX_RETRIES = 4

Job = Callable[[async_sessionmaker[AsyncSession]], Awaitable[str]]


def run_coroutine[T](factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """asyncio.run, or in a helper thread when a loop is already running (eager mode)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = asyncio.run(factory())
        except BaseException as exc:
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]  # type: ignore[no-any-return]


def _run(task: Task, name: str, workspace_id: str, version_id: str, job: Job) -> str:
    ws, version = uuid.UUID(workspace_id), uuid.UUID(version_id)

    async def main(attempts: int) -> tuple[str, BaseException | None]:
        url = get_settings().app_database_url
        if url is None:
            raise RuntimeError("APP_DATABASE_URL is not set")
        engine = make_engine(url.get_secret_value(), null_pool=True)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            try:
                return await job(sm), None
            except pipeline.LeaseLost:
                return pipeline.SKIPPED, None
            except TRANSIENT as exc:
                if attempts <= MAX_RETRIES:
                    await pipeline.release_lease(sm, ws, version)
                    return "retry", exc
                error = f"{type(exc).__name__}: {exc} (after {attempts} attempts)"
            except Exception as exc:
                log.exception("task %s failed for version %s", name, version_id)
                error = f"{type(exc).__name__}: {exc}"
            await pipeline.record_failure(
                sm, ws, version, task_name=name, error=error, attempts=attempts
            )
            return "failed", None
        finally:
            await engine.dispose()

    attempts = task.request.retries + 1
    while True:
        outcome, retry_exc = run_coroutine(functools.partial(main, attempts))
        if outcome != "retry" or retry_exc is None:
            return outcome
        if task.request.is_eager:
            # Eager mode (tests, local dev without a worker): retry inline, no broker.
            attempts += 1
            continue
        raise task.retry(
            exc=retry_exc,
            countdown=pipeline.backoff_seconds(task.request.retries),
            max_retries=MAX_RETRIES,
        )


# Hard limits (parsing.md #5): a hung parse is killed and recorded, never left running.
_LIMIT = get_settings().parse_timeout_seconds


@celery_app.task(
    bind=True,
    name="ingestion.ingest_version",
    max_retries=MAX_RETRIES,
    soft_time_limit=_LIMIT + 120,
    time_limit=_LIMIT + 300,
)
def ingest_version_task(self: Task, workspace_id: str, version_id: str) -> str:
    def job(sm: async_sessionmaker[AsyncSession]) -> Awaitable[str]:
        return pipeline.ingest_version(
            sm,
            uuid.UUID(workspace_id),
            uuid.UUID(version_id),
            parser=get_parser(),
            storage=get_storage(),
            llm=get_llm(),
        )

    return _run(self, "ingest_version", workspace_id, version_id, job)


@celery_app.task(
    bind=True,
    name="ingestion.embed_version",
    max_retries=MAX_RETRIES,
    soft_time_limit=_LIMIT,
    time_limit=_LIMIT + 120,
)
def embed_version_task(self: Task, workspace_id: str, version_id: str) -> str:
    def job(sm: async_sessionmaker[AsyncSession]) -> Awaitable[str]:
        return pipeline.embed_version(
            sm, uuid.UUID(workspace_id), uuid.UUID(version_id), embedder=get_embedder()
        )

    return _run(self, "embed_version", workspace_id, version_id, job)


def enqueue_ingest(workspace_id: uuid.UUID, version_id: uuid.UUID) -> None:
    """Call only after the transaction that created the version has committed."""
    ingest_version_task.apply_async(args=[str(workspace_id), str(version_id)])


def enqueue_embed(workspace_id: uuid.UUID, version_id: uuid.UUID) -> None:
    embed_version_task.apply_async(args=[str(workspace_id), str(version_id)])
