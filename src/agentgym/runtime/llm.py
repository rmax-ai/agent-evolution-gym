"""OpenAI-compatible chat-completions clients for the reference runtime."""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMToolCall(BaseModel):
    """Normalized function tool call returned by a chat-completions model."""

    model_config = ConfigDict(extra="forbid")

    id: str = ""
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)

    @field_validator("arguments", mode="before")
    @classmethod
    def parse_arguments(cls, value: object) -> object:
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as error:
                raise ValueError("tool-call arguments must be valid JSON") from error
            if not isinstance(parsed, dict):
                raise ValueError("tool-call arguments must decode to an object")
            return parsed
        return value


class LLMResponse(BaseModel):
    """Small provider-neutral response returned to the reference agent."""

    model_config = ConfigDict(extra="forbid")

    content: str | None = None
    tool_calls: list[LLMToolCall] = Field(default_factory=list)
    input_tokens: int | None = None
    output_tokens: int | None = None


@runtime_checkable
class LLMClient(Protocol):
    """Async chat-completions interface used by the generic runtime."""

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> LLMResponse:
        """Complete one non-streaming conversation turn."""


class OpenAIChatClient:
    """HTTPX client for OpenAI-compatible ``/chat/completions`` APIs."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("AGENTGYM_LLM_BASE_URL") or "https://api.openai.com/v1"
        ).rstrip("/")
        self.api_key = (
            api_key if api_key is not None else os.environ.get("AGENTGYM_LLM_API_KEY", "")
        )
        self.model = model or os.environ.get("AGENTGYM_LLM_MODEL")
        if not self.model:
            raise ValueError("AGENTGYM_LLM_MODEL or model= is required")
        self.timeout = timeout

    @classmethod
    def from_env(cls, *, timeout: float = 60.0) -> OpenAIChatClient:
        """Construct a client entirely from the documented environment."""

        return cls(timeout=timeout)

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [dict(message) for message in messages],
            "stream": False,
        }
        if tools:
            body["tools"] = [dict(tool) for tool in tools]
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout, trust_env=False) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
        return _response_from_openai_payload(payload)


ResponseScript = Sequence[LLMResponse | Mapping[str, Any]] | Callable[..., Any]


class FakeLLM:
    """Scriptable LLM for hermetic tests and local runner smoke tasks.

    A one-item sequence repeats its last response by default, which is useful
    for deliberately infinite tool-loop tests whose budget should terminate the
    run.  Set ``repeat_last=False`` to make exhaustion an explicit test error.
    """

    def __init__(
        self,
        responses: ResponseScript,
        *,
        repeat_last: bool = True,
    ) -> None:
        self.repeat_last = repeat_last
        self.calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
        self._callable: Callable[..., Any] | None = responses if callable(responses) else None
        self._responses = list(responses) if not callable(responses) else []
        self._index = 0

    async def complete(
        self,
        messages: Sequence[Mapping[str, Any]],
        tools: Sequence[Mapping[str, Any]],
    ) -> LLMResponse:
        message_copy = [dict(message) for message in messages]
        tool_copy = [dict(tool) for tool in tools]
        self.calls.append((message_copy, tool_copy))

        if self._callable is not None:
            value = self._callable(messages, tools)
            if inspect.isawaitable(value):
                value = await value
            return _normalize_response(value)

        if not self._responses:
            raise RuntimeError("FakeLLM has no scripted responses")
        if self._index >= len(self._responses):
            if not self.repeat_last:
                raise RuntimeError("FakeLLM response script is exhausted")
            value = self._responses[-1]
        else:
            value = self._responses[self._index]
            self._index += 1
        return _normalize_response(value)


def _response_from_openai_payload(payload: object) -> LLMResponse:
    if not isinstance(payload, Mapping):
        raise ValueError("LLM response must be a JSON object")
    choices = payload.get("choices")
    if not isinstance(choices, Sequence) or not choices:
        raise ValueError("LLM response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("LLM response choice must be an object")
    message = first.get("message", {})
    if not isinstance(message, Mapping):
        raise ValueError("LLM response message must be an object")
    raw_calls = message.get("tool_calls", [])
    tool_calls: list[LLMToolCall] = []
    if isinstance(raw_calls, Sequence) and not isinstance(raw_calls, (str, bytes, bytearray)):
        for raw_call in raw_calls:
            if not isinstance(raw_call, Mapping):
                raise ValueError("LLM tool call must be an object")
            function = raw_call.get("function", raw_call)
            if not isinstance(function, Mapping):
                raise ValueError("LLM tool call function must be an object")
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("LLM tool call has no function name")
            tool_calls.append(
                LLMToolCall(
                    id=str(raw_call.get("id", "")),
                    name=name,
                    arguments=function.get("arguments", {}),
                )
            )
    usage = payload.get("usage")
    usage_mapping = usage if isinstance(usage, Mapping) else {}
    content = message.get("content")
    if content is not None and not isinstance(content, str):
        content = str(content)
    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        input_tokens=_optional_int(usage_mapping.get("prompt_tokens")),
        output_tokens=_optional_int(usage_mapping.get("completion_tokens")),
    )


def _normalize_response(value: object) -> LLMResponse:
    if isinstance(value, LLMResponse):
        return value
    if isinstance(value, Mapping):
        return LLMResponse.model_validate(value)
    raise TypeError(f"LLM response must be LLMResponse or mapping, got {type(value).__name__}")


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


__all__ = [
    "FakeLLM",
    "LLMClient",
    "LLMResponse",
    "LLMToolCall",
    "OpenAIChatClient",
]
