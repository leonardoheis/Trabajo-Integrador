from pathlib import Path

import anyio

from classiflow.storage.document_storage import LocalDiskStorage


class TestLocalDiskStorageSaveStaged:
    async def test_writes_file_under_staging_with_job_id_prefix(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))

        staged_path = await storage.save_staged("job-1", "doc.pdf", b"%PDF-1.4 fake bytes")

        expected = tmp_path / "staging" / "job-1_doc.pdf"
        assert staged_path == str(expected)
        assert expected.read_bytes() == b"%PDF-1.4 fake bytes"

    async def test_creates_staging_directory_if_missing(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path / "does" / "not" / "exist"))

        staged_path = await storage.save_staged("job-2", "doc.pdf", b"content")

        assert await anyio.Path(staged_path).exists()


class TestLocalDiskStorageMoveToFinal:
    async def test_relocates_staged_file_to_subdirectory(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        await storage.save_staged("job-3", "doc.pdf", b"content")

        final_path = await storage.move_to_final("job-3", "doc.pdf", "classified/ordenanzas")

        expected = tmp_path / "classified" / "ordenanzas" / "job-3_doc.pdf"
        assert final_path == str(expected)
        assert expected.read_bytes() == b"content"

    async def test_staged_file_no_longer_exists_at_old_path(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        staged_path = await storage.save_staged("job-4", "doc.pdf", b"content")

        await storage.move_to_final("job-4", "doc.pdf", "review/human_review")

        assert not await anyio.Path(staged_path).exists()

    async def test_creates_final_parent_directories(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        await storage.save_staged("job-5", "doc.pdf", b"content")

        final_path = await storage.move_to_final("job-5", "doc.pdf", "review/human_review")

        assert Path(final_path).parent == tmp_path / "review" / "human_review"

    async def test_moves_a_file_already_routed_once_to_a_new_subdirectory(
        self, tmp_path: Path
    ) -> None:
        # The human-review -> accept flow (spec Decision 9): a job already moved to
        # review/human_review/ by one move_to_final call gets moved AGAIN, to
        # classified/<label>/, by a second call -- the file is no longer in staging/
        # by then, so move_to_final must find it wherever it currently sits.
        storage = LocalDiskStorage(root=str(tmp_path))
        await storage.save_staged("job-6", "doc.pdf", b"content")
        await storage.move_to_final("job-6", "doc.pdf", "review/human_review")

        final_path = await storage.move_to_final("job-6", "doc.pdf", "classified/ordenanzas")

        expected = tmp_path / "classified" / "ordenanzas" / "job-6_doc.pdf"
        assert final_path == str(expected)
        assert expected.read_bytes() == b"content"
        assert not (tmp_path / "review" / "human_review" / "job-6_doc.pdf").exists()


class TestLocalDiskStorageFindCurrentPath:
    async def test_finds_staged_file(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        staged_path = await storage.save_staged("job-7", "doc.pdf", b"content")

        found = await storage.find_current_path("job-7")

        assert found == staged_path

    async def test_finds_file_after_move_to_final(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))
        await storage.save_staged("job-8", "doc.pdf", b"content")
        final_path = await storage.move_to_final("job-8", "doc.pdf", "classified/ordenanzas")

        found = await storage.find_current_path("job-8")

        assert found == final_path

    async def test_returns_none_for_unknown_job(self, tmp_path: Path) -> None:
        storage = LocalDiskStorage(root=str(tmp_path))

        assert await storage.find_current_path("no-such-job") is None
