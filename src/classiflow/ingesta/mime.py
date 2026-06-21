from collections.abc import Callable

import filetype

MimeDetector = Callable[[bytes], str]


def detect_mime(data: bytes) -> str:
    kind = filetype.guess(data)
    return kind.mime if kind else "application/octet-stream"
