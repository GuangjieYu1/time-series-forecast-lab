import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.errors import AppError


SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}
logger = logging.getLogger(__name__)


def startup_cleanup() -> None:
    settings = get_settings()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.temp_upload_ttl_hours)
    for path in settings.upload_dir.glob("*"):
        if path.name == ".gitkeep":
            continue
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            if mtime < cutoff:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                logger.info("stale upload temp file cleaned", extra={"path": str(path)})
        except FileNotFoundError:
            continue


def _metadata_path(upload_id: str) -> Path:
    return get_settings().upload_dir / f"{upload_id}.json"


def get_upload_path(upload_id: str) -> Path:
    metadata = read_upload_metadata(upload_id)
    path = Path(metadata["path"])
    if not path.exists():
        raise AppError("Temporary upload was not found. Please upload the file again.", 404)
    return path


def read_upload_metadata(upload_id: str) -> dict:
    path = _metadata_path(upload_id)
    if not path.exists():
        raise AppError("Upload id was not found. Please upload the file again.", 404)
    return json.loads(path.read_text(encoding="utf-8"))


async def save_upload_file(file: UploadFile) -> dict:
    settings = get_settings()
    original_name = file.filename or "upload"
    ext = Path(original_name).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise AppError("Unsupported file format. Please upload a csv, xlsx, or xls file.")

    upload_id = f"tmp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:10]}"
    dest = settings.upload_dir / f"{upload_id}{ext}"
    max_bytes = settings.max_upload_mb * 1024 * 1024
    size = 0

    with dest.open("wb") as output:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                dest.unlink(missing_ok=True)
                raise AppError(f"File is too large. The current limit is {settings.max_upload_mb} MB.")
            output.write(chunk)

    metadata = {
        "uploadId": upload_id,
        "fileName": original_name,
        "fileSize": size,
        "extension": ext,
        "path": str(dest),
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    _metadata_path(upload_id).write_text(json.dumps(metadata, ensure_ascii=True), encoding="utf-8")
    logger.info("upload temp file created", extra={"upload_id": upload_id, "path": str(dest), "file_name": original_name})
    return metadata


def delete_upload(upload_id: str) -> None:
    try:
        metadata = read_upload_metadata(upload_id)
    except AppError:
        return
    Path(metadata["path"]).unlink(missing_ok=True)
    _metadata_path(upload_id).unlink(missing_ok=True)
    logger.info("upload temp file deleted", extra={"upload_id": upload_id, "path": metadata["path"]})
