from __future__ import annotations

from pathlib import Path

import chardet


SUPPORTED_ENCODINGS = ("utf-8", "utf-8-sig", "cp1250", "iso-8859-2")


def detect_encoding(path: Path) -> tuple[str, float]:
    with path.open("rb") as stream:
        sample = stream.read(131_072)
    if sample.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig", 1.0
    try:
        sample.decode("utf-8")
        return "utf-8", 1.0
    except UnicodeDecodeError:
        pass
    result = chardet.detect(sample)
    detected = (result.get("encoding") or "utf-8").lower()
    confidence = float(result.get("confidence") or 0.0)
    aliases = {
        "ascii": "utf-8",
        "windows-1250": "cp1250",
        "iso-8859-2": "iso-8859-2",
        "utf_8": "utf-8",
    }
    if detected in aliases:
        return aliases[detected], confidence
    if detected.startswith("windows-") or detected in {"iso-8859-1", "latin-1"}:
        return "cp1250", confidence
    return detected, confidence
