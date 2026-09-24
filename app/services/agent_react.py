# app/services/agent_react.py
"""ReAct-агент с Reflexion-light: Thought → Action → Observation → Thought."""

import json
import time
from typing import Any, Callable

import structlog
from openai import OpenAI

from app.core.config import get_settings

log = structlog.get_logger()

_SYSTEM_PROMPT = (
    "Действовать как агент: самостоятельно выбирать инструменты и их порядок, "
    "при необходимости разбивая задачу на подзадачи. "
    "На каждом шаге сначала одним предложением пояснять, что и зачем делается, "
    "затем вызывать ровно один инструмент и опираться на его результат. "
    "Как только данных достаточно — дать финальный ответ без вызова инструментов. "
    "Не выдумывать данные: использовать только то, что вернули инструменты; "
    "если доступными инструментами задачу решить нельзя — прямо сообщить об этом."
)


def run_react_with_reflection(
    question: str,
    tools: list[dict],
    tool_dispatch: dict[str, Callable[..., Any]],
    max_iterations: int = 10,
    timeout_per_iteration_sec: float = 10.0,
    max_revisions: int = 2,
    model_main: str = "gpt-4.1-mini",
    model_critic: str = "gpt-4.1-mini",
    client: OpenAI | None = None,
) -> dict:
    """Запускает ReAct-цикл с рефлексией; возвращает ответ, usage и трассу."""
    s = get_settings()

    assert 8 <= max_iterations <= 20, "max_iterations должен быть от 8 до 20"

    client = client or OpenAI(api_key=s.llm.openai_api_key.get_secret_value())

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    revisions_used = 0
    usage_total = {"prompt": 0, "completion": 0, "total": 0}
    steps_log: list[dict] = []

    for step in range(max_iterations):
        t0 = time.monotonic()

        try:
            response = client.chat.completions.create(
                model=model_main,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                timeout=timeout_per_iteration_sec,
            )
        except Exception as exc:
            log.warning("react.timeout", step=step, error=str(exc))
            return {
                "answer": "Timeout",
                "usage": usage_total,
                "steps": step + 1,
                "revisions": revisions_used,
                "steps_log": steps_log,
            }

        latency = round(time.monotonic() - t0, 3)
        message = response.choices[0].message
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        usage_total["prompt"] += tokens_in
        usage_total["completion"] += tokens_out
        usage_total["total"] += tokens_in + tokens_out
        messages.append(message)

        if not message.tool_calls:
            log.info(
                "react.step",
                step=step,
                tool=None,
                args=None,
                observation=message.content[:120] if message.content else None,
                latency_sec=latency,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            return {
                "answer": message.content,
                "usage": usage_total,
                "steps": step + 1,
                "revisions": revisions_used,
                "steps_log": steps_log,
            }

        for call in message.tool_calls:
            name = call.function.name
            raw_args = call.function.arguments

            if name not in tool_dispatch:
                observation = f"Ошибка: инструмент '{name}' недоступен."
            else:
                try:
                    args = json.loads(raw_args) if raw_args else {}
                    observation = str(tool_dispatch[name](**args))
                except Exception as exc:
                    observation = f"Ошибка инструмента: {exc}"

            log.info(
                "react.step",
                step=step,
                tool=name,
                args=raw_args[:120],
                observation=observation[:120],
                latency_sec=latency,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
            )
            steps_log.append({
                "step": step,
                "tool": name,
                "args": raw_args,
                "observation": observation[:300],
                "latency_sec": latency,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            })
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": observation,
            })

            if revisions_used < max_revisions:
                critic_resp = client.chat.completions.create(
                    model=model_critic,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Ты критик-агент. Прочитай наблюдение и оцени: "
                                "данных достаточно для продолжения? "
                                "Отвечай строго одной строкой: 'OK' или "
                                "'REVISE: <краткая причина>'."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Наблюдение: {observation}\n\n"
                                f"Текущий план (последние 3 сообщения): "
                                f"{json.dumps(messages[-3:], ensure_ascii=False, default=str)}"
                            ),
                        },
                    ],
                    timeout=timeout_per_iteration_sec,
                )
                verdict = (critic_resp.choices[0].message.content or "OK").strip()

                critic_usage = critic_resp.usage
                if critic_usage:
                    usage_total["prompt"] += critic_usage.prompt_tokens
                    usage_total["completion"] += critic_usage.completion_tokens
                    usage_total["total"] += critic_usage.total_tokens

                log.info("react.critic", step=step, verdict=verdict)

                if verdict.upper().startswith("REVISE"):
                    revisions_used += 1
                    messages.append({
                        "role": "system",
                        "content": (
                            f"[Критик, ревизия {revisions_used}/{max_revisions}]: "
                            f"{verdict}. Скорректируй план."
                        ),
                    })
                    log.info("react.revision", step=step, revision=revisions_used)

        if time.monotonic() - t0 > timeout_per_iteration_sec:
            log.warning("react.timeout_tool", step=step)
            return {
                "answer": "Timeout",
                "usage": usage_total,
                "steps": step + 1,
                "revisions": revisions_used,
                "steps_log": steps_log,
            }

    log.warning("react.max_iterations_exceeded", max_iterations=max_iterations)
    return {
        "answer": "Превышен лимит итераций",
        "usage": usage_total,
        "steps": max_iterations,
        "revisions": revisions_used,
        "steps_log": steps_log,
    }


def run_agent(
    question: str,
    max_iterations: int = 10,
    client: OpenAI | None = None,
) -> dict:
    """Обёртка с дефолтными инструментами — интерфейс как у agent_naive."""
    from app.tools.naive_tools import DISPATCH, TOOLS
    return run_react_with_reflection(
        question=question,
        tools=TOOLS,
        tool_dispatch=DISPATCH,
        max_iterations=max_iterations,
        client=client,
    )