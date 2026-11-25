"""Local filesystem storage for development (STORAGE_LOCAL_DIR)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from app.providers.storage.base import ObjectNotFound, validate_key


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        path = (self.root / validate_key(key)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"invalid storage key: {key!r}")
        return path

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, path)  # atomic: readers never see half a file

        await asyncio.to_thread(_write)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)
