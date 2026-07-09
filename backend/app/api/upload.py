from fastapi import APIRouter, Depends, File, UploadFile

from app.api.dependencies import WorkspaceContext, get_workspace_context, require_workspace_write_access
from app.core.errors import AppError, as_http_error
from app.core.storage import assert_upload_ownership, read_upload_metadata, save_upload_file
from app.schemas import SheetPreview, UploadPreviewResponse
from app.services.file_parser import preview_sheet, preview_upload


router = APIRouter(prefix="/api/upload", tags=["upload"])


@router.post("/preview", response_model=UploadPreviewResponse)
async def upload_preview(file: UploadFile = File(...), context: WorkspaceContext = Depends(require_workspace_write_access)):
    try:
        metadata = await save_upload_file(file, user_id=context.user.id, workspace_id=context.workspace.id)
        preview = preview_upload(metadata["uploadId"], limit=100)
        return UploadPreviewResponse(
            uploadId=preview.uploadId,
            workspaceId=context.workspace.id,
            fileName=preview.fileName,
            fileSize=preview.fileSize,
            fileSha256=metadata["fileSha256"],
            sheets=preview.sheets,
        )
    except AppError as exc:
        raise as_http_error(exc) from exc


@router.get("/{upload_id}/sheets/{sheet_name}/preview", response_model=SheetPreview)
def get_sheet_preview(upload_id: str, sheet_name: str, limit: int = 100, context: WorkspaceContext = Depends(get_workspace_context)):
    try:
        metadata = read_upload_metadata(upload_id)
        assert_upload_ownership(metadata, user_id=context.user.id, workspace_id=context.workspace.id)
        return preview_sheet(upload_id, sheet_name, limit=min(max(limit, 1), 500))
    except AppError as exc:
        raise as_http_error(exc) from exc
