from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class FilesystemAssetStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve_path(self, storage_key: str) -> Path:
        if ".." in storage_key or storage_key.startswith("/") or storage_key.startswith("\\"):
            raise ValueError(f"Invalid storage key: {storage_key}")
        target = self.root / storage_key
        try:
            target.resolve().relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"Invalid storage key: {storage_key}") from exc
        return target

    def write(self, storage_key: str, data: bytes) -> None:
        target = self._resolve_path(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = Path(f"{target}.tmp")
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
            os.replace(tmp_path, target)
        except BaseException:
            tmp_path.unlink(missing_ok=True)
            raise

    def open(self, storage_key: str) -> BinaryIO:
        target = self._resolve_path(storage_key)
        return open(target, "rb")

    def delete(self, storage_key: str) -> None:
        target = self._resolve_path(storage_key)
        try:
            target.unlink()
        except FileNotFoundError:
            pass

    def exists(self, storage_key: str) -> bool:
        target = self._resolve_path(storage_key)
        return target.is_file()


__all__ = ["FilesystemAssetStorage"]
