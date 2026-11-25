"""GCSStorage against fake-gcs-server (compose service `fake-gcs`).

Runs when STORAGE_EMULATOR_HOST is set, e.g. STORAGE_EMULATOR_HOST=http://localhost:4443.
"""

from __future__ import annotations

import os
import uuid

import pytest

from app.providers.storage.base import ObjectNotFound

pytestmark = pytest.mark.skipif(
    not os.environ.get("STORAGE_EMULATOR_HOST"), reason="needs fake-gcs-server"
)


async def test_gcs_round_trip() -> None:
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import storage  # type: ignore[import-untyped]

    from app.providers.storage.gcs import GCSStorage

    bucket = f"tr-test-{uuid.uuid4().hex[:8]}"
    storage.Client(credentials=AnonymousCredentials(), project="local").create_bucket(bucket)  # type: ignore[no-untyped-call]
    gcs = GCSStorage(bucket)
    key = f"workspaces/{uuid.uuid4()}/originals/abc.pdf"
    await gcs.put(key, b"%PDF-1.7 bytes", "application/pdf")
    assert await gcs.get(key) == b"%PDF-1.7 bytes"
    await gcs.delete(key)
    with pytest.raises(ObjectNotFound):
        await gcs.get(key)
    await gcs.delete(key)  # idempotent
