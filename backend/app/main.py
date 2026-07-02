import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import experiments, forecast, llm, models, reports, system, upload
from app.core.config import get_settings
from app.core.constants import APP_VERSION
from app.core.errors import AppError, error_payload
from app.core.storage import startup_cleanup
from app.db.models import Base
from app.db.schema_compat import ensure_schema_compatibility
from app.db.session import engine


settings = get_settings()
logging.getLogger("app").setLevel(logging.INFO)
app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    startup_cleanup()
    Base.metadata.create_all(bind=engine)
    ensure_schema_compatibility(engine)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=error_payload(exc.message, exc.code, exc.details))


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict) and {"message", "code", "details"}.issubset(exc.detail.keys()):
        payload = exc.detail
    else:
        payload = error_payload(str(exc.detail), "HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content=error_payload("Request validation failed.", "VALIDATION_ERROR", {"errors": exc.errors()}),
    )


@app.get("/api/health")
def health():
    return {"ok": True, "app": settings.app_name, "version": APP_VERSION}


app.include_router(upload.router)
app.include_router(models.router)
app.include_router(forecast.router)
app.include_router(experiments.router)
app.include_router(llm.router)
app.include_router(reports.router)
app.include_router(system.router)
