"""Fingerprints include uncommitted changes so equal Git labels cannot hide drift."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
import platform


@lru_cache(maxsize=1)
def build_info() -> dict[str, str]:
    root = Path(__file__).resolve().parents[3]
    digest = sha256()
    for folder in ("backend/app", "frontend/src"):
        for item in sorted((root / folder).rglob("*")):
            if item.is_file() and item.suffix in {".py", ".ts", ".tsx", ".css"}:
                digest.update(str(item.relative_to(root)).encode())
                digest.update(b"\0")
                digest.update(item.read_bytes())
    lock = root / "backend/requirements-standard.lock"
    return {
        "sourceFingerprint": digest.hexdigest(),
        "dependencyLockFingerprint": sha256(lock.read_bytes()).hexdigest() if lock.exists() else "unlocked",
        "pythonVersion": platform.python_version(),
    }
