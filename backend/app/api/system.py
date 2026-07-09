from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import require_workspace_write_access
from app.core.config import Settings, get_settings
from app.core.errors import AppError, as_http_error
from app.schemas import LocalRebuildRequest, LocalRebuildResponse


router = APIRouter(prefix="/api/system", tags=["system"])


def _is_allowed_local_host(request: Request, settings: Settings) -> bool:
    client_host = request.client.host if request.client else None
    return bool(client_host and client_host in settings.local_rebuild_allowed_hosts)


@router.post("/local-rebuild", response_model=LocalRebuildResponse)
def schedule_local_rebuild(
    payload: LocalRebuildRequest,
    request: Request,
    _=Depends(require_workspace_write_access),
    settings: Settings = Depends(get_settings),
):
    try:
        if not _is_allowed_local_host(request, settings):
            raise AppError("一键重建只允许在本机 localhost 环境触发。", 403, "LOCAL_REBUILD_FORBIDDEN")
        expected_password = settings.resolved_local_rebuild_password
        if not expected_password:
            raise AppError("本地维护密码尚未配置。请在环境变量 TSFL_LOCAL_REBUILD_PASSWORD 或 deploy/.local-rebuild-password 中设置。", 500, "LOCAL_REBUILD_PASSWORD_NOT_CONFIGURED")
        if payload.password != expected_password:
            raise AppError("本地维护密码不正确。", 401, "LOCAL_REBUILD_AUTH_FAILED")

        script_path = settings.deploy_dir / "local_rebuild.py"
        if not script_path.exists():
            raise AppError("本地重建脚本不存在。", 500, "LOCAL_REBUILD_SCRIPT_MISSING", {"scriptPath": str(script_path)})

        log_path = settings.deploy_dir / "logs" / "local-rebuild.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        command = [sys.executable, str(script_path), "--delay-seconds", str(payload.delaySeconds)]
        log_handle = log_path.open("a", encoding="utf-8")
        try:
            popen_kwargs: dict[str, object] = {
                "cwd": str(settings.repo_root),
                "stdout": log_handle,
                "stderr": subprocess.STDOUT,
            }
            if os.name == "nt":
                popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
            else:
                popen_kwargs["start_new_session"] = True
            subprocess.Popen(command, **popen_kwargs)
        finally:
            log_handle.close()
        return LocalRebuildResponse(
            accepted=True,
            message="已接受本地一键重建请求。若当前后端随后中断，这是脚本在接管重启；若后端已经完全卡死，请直接双击 deploy 目录下的脚本。",
            scriptPath=str(script_path),
            logPath=str(log_path),
        )
    except AppError as exc:
        raise as_http_error(exc) from exc
