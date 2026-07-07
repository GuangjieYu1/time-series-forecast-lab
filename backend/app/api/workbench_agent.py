from __future__ import annotations

from fastapi import APIRouter

from app.schemas import (
    WorkbenchCustomModelSpecRequest,
    WorkbenchCustomModelValidateRequest,
    WorkbenchCustomModelValidateResponse,
    WorkbenchDataSourceSearchRequest,
    WorkbenchDataSourceSearchResponse,
    WorkbenchIdeaAnalyzeRequest,
    WorkbenchIdeaAnalyzeResponse,
)
from app.services.workbench_agent import (
    analyze_idea,
    build_custom_model_spec,
    search_data_sources,
    validate_custom_model_spec,
)


router = APIRouter(prefix="/api/workbench-agent", tags=["workbench-agent"])


@router.post("/ideas/analyze", response_model=WorkbenchIdeaAnalyzeResponse)
def analyze_workbench_idea(request: WorkbenchIdeaAnalyzeRequest):
    return analyze_idea(request)


@router.post("/data-sources/search", response_model=WorkbenchDataSourceSearchResponse)
def search_workbench_data_sources(request: WorkbenchDataSourceSearchRequest):
    return search_data_sources(request)


@router.post("/custom-models/spec")
def build_workbench_custom_model_spec(request: WorkbenchCustomModelSpecRequest):
    return {"spec": build_custom_model_spec(request.idea, request.context)}


@router.post("/custom-models/validate", response_model=WorkbenchCustomModelValidateResponse)
def validate_workbench_custom_model(request: WorkbenchCustomModelValidateRequest):
    return validate_custom_model_spec(request.spec)
