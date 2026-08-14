import tempfile
from pathlib import Path

from markitdown import MarkItDown, MarkItDownException
from typing_extensions import override

from classiflow.ingesta.extractors.base import ExtractorBase
from classiflow.ingesta.extractors.exceptions import MarkItDownError


class MarkItDownExtractor(ExtractorBase):
    @override
    def extract(self, file_bytes: bytes, filename: str) -> str:
        with tempfile.NamedTemporaryFile(
            suffix=Path(filename).suffix or ".pdf", delete=False
        ) as tmp:
            tmp.write(file_bytes)
            tmp_path = Path(tmp.name)

        try:
            return MarkItDown().convert(str(tmp_path)).text_content.strip()
        except MarkItDownException as exc:
            raise MarkItDownError(filename, exc) from exc
        finally:
            tmp_path.unlink(missing_ok=True)
