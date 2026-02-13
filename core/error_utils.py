from __future__ import annotations

from pathlib import Path
from traceback import extract_tb


def get_exception_location(exc: BaseException) -> str:
    """
    Return a concise source location for an exception.

    Format: ``filename:line in function``.
    """
    tb = exc.__traceback__
    if tb is None:
        return "unknown"

    frames = extract_tb(tb)
    if not frames:
        return "unknown"

    frame = frames[-1]
    return f"{Path(frame.filename).name}:{frame.lineno} in {frame.name}"
