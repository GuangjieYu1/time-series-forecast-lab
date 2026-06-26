from fastapi import APIRouter

from app.core.gpu import get_device, get_memory_info
from app.schemas import ModelsResponse
from app.services.model_registry import get_model_capabilities


router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=ModelsResponse)
def list_models():
    return ModelsResponse(models=get_model_capabilities())


@router.get("/device")
def model_device():
    return {"device": get_device(), **get_memory_info()}
