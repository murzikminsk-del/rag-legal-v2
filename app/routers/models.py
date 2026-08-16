from fastapi import APIRouter

from app.schemas.models import AVAILABLE_MODELS, ModelInfo

router = APIRouter(tags=["models"])


@router.get("/models", summary="List available models", response_model=list[ModelInfo])
async def list_models():
    return AVAILABLE_MODELS