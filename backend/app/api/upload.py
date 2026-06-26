from fastapi import APIRouter, File, UploadFile

from app.core.errors import AppError, as_http_error
from app.core.storage import save_upload_file
from app.schemas import SheetPreview, UploadPreviewResponse
from app.services.file_parser import preview_sheet, preview_upload


router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("/preview", response_model=UploadPreviewResponse)
async def upload_preview(file: UploadFile = File(...)):
    try:
        metadata = await save_upload_file(file)
        return preview_upload(metadata["uploadId"], limit=100)
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{upload_id}/sheets/{sheet_name}/preview", response_model=SheetPreview)
def get_sheet_preview(upload_id: str, sheet_name: str, limit: int = 100):
    try:
        return preview_sheet(upload_id, sheet_name, limit=min(max(limit, 1), 500))
    except AppError as exc:
        raise as_http_error(exc) from exc
