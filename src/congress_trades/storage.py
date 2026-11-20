"""The landing zone: every source file stored byte for byte before parsing.

Keys are slash-separated paths such as ``house/ptr/2025/20032062.pdf``. The
same keys work on both backends, so a file's location never depends on where
the pipeline runs:

- ``LocalStore`` keeps files under ``DATA_DIR/landing/<key>``.
- ``GCSStore`` keeps them in the raw bucket at ``gs://<bucket>/<key>``.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from congress_trades.config import Settings


class Store(Protocol):
    def exists(self, key: str) -> bool: ...
    def read(self, key: str) -> bytes: ...
    def write(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> None: ...
    def list(self, prefix: str) -> Iterator[str]: ...
    def uri(self, key: str) -> str: ...


class LocalStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError(f"key escapes the landing folder: {key!r}")
        return path

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def read(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def write(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)  # atomic, so a crash never leaves half a file

    def list(self, prefix: str) -> Iterator[str]:
        base = self.root / prefix
        if not base.exists():
            return
        for path in sorted(base.rglob("*")):
            if path.is_file() and not path.name.endswith(".part"):
                yield path.relative_to(self.root).as_posix()

    def uri(self, key: str) -> str:
        return self._path(key).as_uri()


class GCSStore:
    def __init__(self, bucket: str, project: str | None = None):
        from google.cloud import storage  # imported lazily: only the gcp backend needs it

        self._client = storage.Client(project=project)
        self._bucket = self._client.bucket(bucket)
        self.bucket_name = bucket

    def exists(self, key: str) -> bool:
        return self._bucket.blob(key).exists()

    def read(self, key: str) -> bytes:
        return self._bucket.blob(key).download_as_bytes()

    def write(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        self._bucket.blob(key).upload_from_string(data, content_type=content_type)

    def list(self, prefix: str) -> Iterator[str]:
        for blob in self._client.list_blobs(self._bucket, prefix=prefix):
            yield blob.name

    def uri(self, key: str) -> str:
        return f"gs://{self.bucket_name}/{key}"


def get_store(settings: Settings) -> Store:
    if settings.is_local:
        return LocalStore(Path(settings.data_dir) / "landing")
    return GCSStore(settings.gcs_raw_bucket, settings.gcp_project_id)
