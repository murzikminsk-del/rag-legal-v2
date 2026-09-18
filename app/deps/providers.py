from typing import Annotated, Any

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


def get_agent_graph(request: Request) -> Any:
    """Скомпилированный ReAct-граф агента, собранный в lifespan.
    None — если сборка не удалась: /agent/* вернут 503."""
    return request.app.state.agent_graph


SettingsDep = Annotated[Settings, Depends(get_settings)]
CacheDep = Annotated[object, Depends(get_cache)]
LLMServiceDep = Annotated[LLMService, Depends(get_llm_service)]
AgentGraphDep = Annotated[Any, Depends(get_agent_graph)]