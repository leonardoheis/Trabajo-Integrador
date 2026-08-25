import asyncio
import shutil
from pathlib import Path
from typing import Protocol

from classiflow.settings import Settings


class IDocumentStorage(Protocol):
    async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str: ...
    async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str: ...
    async def find_current_path(self, job_id: str) -> str | None: ...


class LocalDiskStorage:
    def __init__(self, root: str | None = None) -> None:
        self._root = Path(root if root is not None else Settings.document_storage_root)

    async def save_staged(self, job_id: str, filename: str, file_bytes: bytes) -> str:
        return await asyncio.to_thread(self._save_staged_sync, job_id, filename, file_bytes)

    def _save_staged_sync(self, job_id: str, filename: str, file_bytes: bytes) -> str:
        staged_path = self._root / "staging" / f"{job_id}_{filename}"
        staged_path.parent.mkdir(parents=True, exist_ok=True)
        staged_path.write_bytes(file_bytes)
        return str(staged_path)

    async def move_to_final(self, job_id: str, filename: str, subdirectory: str) -> str:
        return await asyncio.to_thread(self._move_to_final_sync, job_id, filename, subdirectory)

    def _move_to_final_sync(self, job_id: str, filename: str, subdirectory: str) -> str:
        # Locates the file wherever it currently sits (glob, not a fixed "staging/"
        # path) rather than assuming it's always still staged. A job routed to
        # human_review legitimately gets moved TWICE: staging/ -> review/human_review/
        # (Routing's automatic run), then review/human_review/ -> classified/<label>/
        # (the human-decision endpoint calling Routing a second time). There is always
        # exactly one physical copy on disk (moved, never copied), so the glob is
        # unambiguous.
        target_name = f"{job_id}_{filename}"
        matches = list(self._root.glob(f"**/{target_name}"))
        if not matches:
            msg = f"No staged or previously-routed file found for job {job_id} ({filename})"
            raise FileNotFoundError(msg)
        source_path = matches[0]
        final_path = self._root / subdirectory / target_name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(final_path))
        return str(final_path)

    async def find_current_path(self, job_id: str) -> str | None:
        return await asyncio.to_thread(self._find_current_path_sync, job_id)

    def _find_current_path_sync(self, job_id: str) -> str | None:
        matches = list(self._root.glob(f"**/{job_id}_*"))
        return str(matches[0]) if matches else None
