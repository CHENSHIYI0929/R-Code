"""Bounded stream/non-stream provider diagnostic using the production AgentLoop."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from pathlib import Path
import time
from typing import Any, Literal

from benchmarks.repair_loop.experiments.repair_loop import CASES
from benchmarks.repair_loop.fixtures import fixture_workspace
from benchmarks.repair_loop.runtime_adapter import _collect, _runtime
from infrastructure.providers.chat_completions import OpenAICompatibleChatCompletionsClient, _assistant_message_from_stream, _join_url, _parse_usage
from infrastructure.providers.factory import resolve_config
from infrastructure.providers.http import HttpxAsyncHttpTransport
from services.context.snapshot import ContextSnapshot
from services.model.stream import ModelStreamEvent
from services.model.types import ProviderError


@dataclass
class CallObservation:
    mode: str
    finish_reason: str | None = None
    tool_calls: int = 0
    chunks: int = 0
    first_chunk_ms: int | None = None
    last_chunk_ms: int | None = None
    error_type: str | None = None
    response_ids: list[str] | None = None
    accumulated_arguments: list[str] | None = None
    parse_error: str | None = None
    model_input: list[dict[str, Any]] | None = None


class BoundedSmokeClient(OpenAICompatibleChatCompletionsClient):
    def __init__(self, *args: Any, mode: Literal["stream", "nonstream"], call_timeout_seconds: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.mode = mode
        self.call_timeout_seconds = call_timeout_seconds
        self.observations: list[CallObservation] = []
        self.max_model_calls: int | None = None

    async def stream(self, snapshot: ContextSnapshot) -> AsyncIterator[ModelStreamEvent]:
        observation = CallObservation(mode=self.mode)
        observation.response_ids = []
        observation.accumulated_arguments = []
        observation.model_input = [dict(message) for message in snapshot.messages]
        if self.max_model_calls is not None and len(self.observations) >= self.max_model_calls:
            observation.error_type = "model_call_budget_exceeded"
            self.observations.append(observation)
            raise ProviderError("Benchmark model-call budget exceeded.", provider_id=self.config.provider_id, error_type="model_call_budget_exceeded")
        self.observations.append(observation)
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.call_timeout_seconds):
                if self.mode == "stream":
                    async for event in super().stream(snapshot):
                        observation.chunks += 1
                        now = round((time.perf_counter() - started) * 1000)
                        observation.first_chunk_ms = observation.first_chunk_ms if observation.first_chunk_ms is not None else now
                        observation.last_chunk_ms = now
                        if event.type == "message_completed":
                            observation.finish_reason = event.stop_reason
                            observation.tool_calls = len(event.metadata.get("tool_calls", ()))
                            response_id = event.metadata.get("response_id")
                            if isinstance(response_id, str):
                                observation.response_ids.append(response_id)
                        yield event
                    return
                payload = {**self._build_payload(snapshot), "stream": False}
                response = await self.async_transport.post_json(_join_url(self.config.base_url, self.config.chat_completions_path), self._headers(), payload, self.config.timeout_seconds)
                observation.chunks = 1
                observation.first_chunk_ms = observation.last_chunk_ms = round((time.perf_counter() - started) * 1000)
                choice = response.get("choices", [None])[0]
                if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
                    raise self._invalid_response("Non-stream response is missing choices[0].message.")
                message = choice["message"]
                raw_calls = message.get("tool_calls")
                tool_calls = self._parse_tool_calls(raw_calls)
                text = message.get("content") if isinstance(message.get("content"), str) else ""
                observation.finish_reason = choice.get("finish_reason") if isinstance(choice.get("finish_reason"), str) else None
                if isinstance(response.get("id"), str):
                    observation.response_ids.append(response["id"])
                observation.tool_calls = len(tool_calls)
                usage = _parse_usage(response.get("usage"))
                if usage is not None:
                    yield ModelStreamEvent.usage_event(usage)
                for tool_call in tool_calls:
                    yield ModelStreamEvent.tool_call_completed(tool_call)
                yield ModelStreamEvent.message_completed(assistant_message=message, final_text=text, tool_calls=tool_calls, stop_reason=observation.finish_reason, usage=usage)
        except TimeoutError as exc:
            observation.error_type = "provider_timeout"
            raise ProviderError("Benchmark model-call timeout.", provider_id=self.config.provider_id, error_type="timeout_error") from exc
        except ProviderError as exc:
            observation.error_type = exc.error_type or "provider_error"
            raise

    def _parse_arguments(self, arguments: Any) -> dict[str, Any]:
        if self.observations:
            self.observations[-1].accumulated_arguments.append(arguments if isinstance(arguments, str) else repr(arguments))
        try:
            return super()._parse_arguments(arguments)
        except ProviderError as exc:
            if self.observations:
                self.observations[-1].parse_error = exc.message
            raise


async def run_smoke(*, env_path: Path, mode: Literal["stream", "nonstream"], timeout_seconds: float, max_model_calls: int = 12, max_tool_steps: int = 12, max_wall_clock_seconds: float = 120) -> dict[str, Any]:
    config = resolve_config(env_path)
    client = BoundedSmokeClient(config, async_transport=HttpxAsyncHttpTransport(provider_id=config.provider_id), mode=mode, call_timeout_seconds=timeout_seconds)
    client.max_model_calls = max_model_calls
    case = next(case for case in CASES if case.profile == "verification_only")
    with fixture_workspace(case.fixture) as workspace:
        state, store, trace, errors, loop, _memory = _runtime(workspace, client, repair_profile="verification_only")
        events: list[Any] = []
        started = time.perf_counter()
        try:
            async with asyncio.timeout(max_wall_clock_seconds):
                async for event in loop.stream(
                    "Repair the failing test in the known fixture layout: first read "
                    "src/sample.py and tests/test_sample.py. Then edit only the existing "
                    "src/sample.py; do not create helper scripts or inspect guessed paths. "
                    "Finish after the smallest test-directed repair."
                ):
                    events.append(event)
                    if sum(item.type == "tool_result" for item in events) > max_tool_steps:
                        raise ProviderError("Benchmark tool budget exceeded.", provider_id=config.provider_id, error_type="tool_budget_exceeded")
            error_type = None
        except TimeoutError:
            error_type = "wall_clock_budget_exceeded"
        except ProviderError as exc:
            error_type = _classify_error(exc.error_type)
        finally:
            store.flush_transcript(); trace.flush(); errors.flush()
        return {"mode": mode, "error_type": error_type, "terminal_outcome": state.last_transition.value if state.last_transition else None, "tool_calls": sum(item.tool_calls for item in client.observations), "events": len(events), "tool_steps": sum(item.type == "tool_result" for item in events), "wall_clock_ms": round((time.perf_counter() - started) * 1000), "budgets": {"max_model_calls": max_model_calls, "max_tool_steps": max_tool_steps, "max_wall_clock_seconds": max_wall_clock_seconds}, "calls": [asdict(item) for item in client.observations]}


def _classify_error(error_type: str | None) -> str:
    return {"timeout_error": "provider_timeout", "invalid_response": "invalid_response", "model_call_budget_exceeded": "model_call_budget_exceeded", "tool_budget_exceeded": "tool_budget_exceeded"}.get(error_type or "", "provider_error")
