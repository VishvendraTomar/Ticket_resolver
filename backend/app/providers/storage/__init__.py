"""Storage provider selection."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import StorageProvider, get_settings
from app.providers.storage.base import Storage


@lru_cache
def get_storage() -> Storage:
    settings = get_settings()
    if settings.storage_provider is StorageProvider.MEMORY:
        from app.providers.storage.memory import MemoryStorage

        return MemoryStorage()
    if settings.storage_provider is StorageProvider.LOCAL:
        from app.providers.storage.local import LocalStorage

        return LocalStorage(settings.storage_local_dir)
    from app.providers.storage.gcs import GCSStorage

    assert settings.gcs_bucket  # enforced by settings validation
    return GCSStorage(settings.gcs_bucket, project=settings.vertex_project)
