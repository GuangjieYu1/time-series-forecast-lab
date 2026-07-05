from fastapi import APIRouter

from app.core.gpu import get_device_info
from app.schemas import DeviceInfoResponse, ModelsResponse
from app.services.model_registry import get_model_capabilities


router = APIRouter(prefix="/api/models", tags=["models"])


@router.get("", response_model=ModelsResponse)
def list_models():
    return ModelsResponse(models=get_model_capabilities())


@router.get("/device", response_model=DeviceInfoResponse)
def model_device():
    return DeviceInfoResponse.model_validate(get_device_info())