"""Shared ETL utilities: download, hash, import_run tracking."""
import hashlib
import os
from pathlib import Path

RAW_DATA_DIR = Path(__file__).parent.parent / "rawData"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
