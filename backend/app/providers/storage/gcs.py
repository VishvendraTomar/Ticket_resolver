"""Google Cloud Storage. Honours STORAGE_EMULATOR_HOST (fake-gcs-server) automatically.

Credentials: Application Default Credentials. The bucket should be in the EU
(europe-west3) with uniform bucket-level access; that's infrastructure, not code.
"""

from __future__ import annotations

import asyncio
import contextlib
import os

from google.api_core.exceptions import NotFound
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage  # type: ignore[import-untyped]

from app.providers.storage.base import ObjectNotFound, validate_key


class GCSStorage:
    def __init__(self, bucket: str, project: str | None = None) -> None:
        if os.environ.get("STORAGE_EMULATOR_HOST"):
            client = storage.Client(
                credentials=AnonymousCredentials(),  # type: ignore[no-untyped-call]
                project=project or "local",
            )
        else:
            client = storage.Client(project=project)
        self._bucket = client.bucket(bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        blob = self._bucket.blob(validate_key(key))
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)

    async def get(self, key: str) -> bytes:
        blob = self._bucket.blob(validate_key(key))
        try:
            data: bytes = await asyncio.to_thread(blob.download_as_bytes)
        except NotFound as exc:
            raise ObjectNotFound(key) from exc
        return data

    async def delete(self, key: str) -> None:
        blob = self._bucket.blob(validate_key(key))
        with contextlib.suppress(NotFound):
            await asyncio.to_thread(blob.delete)
