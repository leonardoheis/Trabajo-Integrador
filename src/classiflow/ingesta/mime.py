import magic


def detect_mime(data: bytes) -> str:
    return magic.from_buffer(data, mime=True)
