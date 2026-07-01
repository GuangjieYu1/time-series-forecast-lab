from __future__ import annotations

from fastapi import APIRouter

from app.schemas import DeepSeekConnectionRequest, DeepSeekConnectionResponse
from app.services.deepseek import test_deepseek_connection


router = APIRouter(prefix="/api/llm", tags=["llm"])


@router.post("/deepseek/test", response_model=DeepSeekConnectionResponse)
def test_deepseek(request: DeepSeekConnectionRequest):
    return test_deepseek_connection(api_key=request.apiKey, base_url=request.baseUrl, model=request.model)
