from typing import Annotated

from fastapi import Depends, Request
from openai import AsyncOpenAI

from app.core.config import Settings, get_settings
from app.services.llm import LLMService


def get_openai(request: Request) -> AsyncOpenAI:
    return request.app.state.openai


def get_cache(request: Request):
    return request.app.state.cache


def get_llm_service(
    client: Annotated[AsyncOpenAI, Depends(get_openai)],
    cache: Annotated[object, Depends(get_cache)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> LLMService:
    return LLMService(client=client, cache=cache, settings=settings)


SettingsDep = Annotated[Settings, Depends(get_settings)]
CacheDep = Annotated[object, Depends(get_cache)]
LLMServiceDep = Annotated[LLMService, Depends(get_llm_service)]