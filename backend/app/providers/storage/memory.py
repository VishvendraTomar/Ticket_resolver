"""In-memory storage for tests (one store per process)."""

from __future__ import annotations

from app.providers.storage.base import ObjectNotFound, validate_key


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[validate_key(key)] = (data, content_type)

    async def get(self, key: str) -> bytes:
        try:
            return self.objects[validate_key(key)][0]
        except KeyError as exc:
            raise ObjectNotFound(key) from exc

    async def delete(self, key: str) -> None:
        self.objects.pop(validate_key(key), None)
