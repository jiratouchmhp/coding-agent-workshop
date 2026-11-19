"""Agent Runtime HTTP Contract FastAPI Server (Solution Track — Lab 3).

Implements the verified Gemini Enterprise Agent Platform BYOC runtime contract
(``scale/runtime/runtime-contract``) on ``0.0.0.0:8080``:

- ``GET /``: Liveness/readiness health probe returning ``HTTP 200 OK``.
- ``POST /api/reasoning_engine``: Unary/async method dispatch
  (``api_mode`` ``""`` or ``"async"``) returning JSON ``{"output": ...}``.
- ``POST /api/stream_reasoning_engine``: Streaming method dispatch
  (``api_mode`` ``"stream"`` or ``"async_stream"``) returning NDJSON frames
  (one JSON object per line, converted to SSE by Agent Runtime; max 15 min).
- ``GET /is_busy``: Optional keep-alive probe endpoint (``200`` busy / ``412`` idle).
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
from collections.abc import AsyncGenerator
from typing import Any

import uvicorn
from fastapi import FastAPI, encoders, responses
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("coding_agent_runtime")

app = FastAPI(
    title="Enterprise Coding Agent — Agent Runtime HTTP Server",
    version="0.1.0",
)


class QueryRequest(BaseModel):
    """Canonical Agent Runtime JSON request envelope."""

    input: dict[str, Any] | None = None
    class_method: str


def _encode_ndjson_chunk(chunk: Any) -> str | None:
    """Serialize one streaming event/chunk as a single NDJSON line."""
    try:
        json_chunk = encoders.jsonable_encoder(chunk)
        return json.dumps(json_chunk) + "\n"
    except Exception:
        logger.exception("Failed to JSON-encode streaming chunk.")
        return None


async def _ndjson_stream(output: Any) -> AsyncGenerator[str, None]:
    """Emit NDJSON frames from either an async generator or synchronous iterable."""
    if hasattr(output, "__aiter__"):
        async for chunk in output:
            encoded = _encode_ndjson_chunk(chunk)
            if encoded is None:
                break
            yield encoded
        return

    if hasattr(output, "__iter__") and not isinstance(output, (str, bytes, dict)):
        for chunk in output:
            encoded = _encode_ndjson_chunk(chunk)
            if encoded is None:
                break
            yield encoded
        return

    encoded = _encode_ndjson_chunk({"output": output})
    if encoded is not None:
        yield encoded


async def _invoke_method(method: Any, payload: dict[str, Any]) -> Any:
    """Invoke a sync or async callable with keyword arguments."""
    if inspect.iscoroutinefunction(method):
        return await method(**payload)
    return method(**payload)


@functools.lru_cache(maxsize=1)
def get_runtime_app() -> Any:
    """Lazily construct and set up ``AdkApp`` from ``coding_agent.agent.app`` (or ``root_agent``).

    Forwarding ``app=adk_app`` when supported by the installed ``AdkApp`` signature
    preserves ``App``-level settings such as ``name="coding_agent"``,
    ``ResumabilityConfig(is_resumable=True)``, and ``GlobalInstructionPlugin`` for
    remote HITL, collaborative, graph, and dynamic deployments. Falls back cleanly
    to ``AdkApp(agent=root_agent)`` (forwarding ``plugins`` if supported) on older SDKs.

    Lazy initialization ensures the container passes startup health probes (``GET /``)
    even on first deploy under Agent Identity before env vars/secrets are attached.
    """
    from coding_agent.agent import app as adk_app
    from coding_agent.agent import root_agent

    try:
        from agentplatform.frameworks import AdkApp
    except ImportError:
        from vertexai.agent_engines import AdkApp

    init_params = inspect.signature(AdkApp.__init__).parameters
    if "app" in init_params:
        runtime_app = AdkApp(app=adk_app)
    else:
        kwargs: dict[str, Any] = {"agent": root_agent}
        app_plugins = getattr(adk_app, "plugins", None)
        if app_plugins and "plugins" in init_params:
            kwargs["plugins"] = list(app_plugins)
        runtime_app = AdkApp(**kwargs)

    setup_fn = getattr(runtime_app, "set_up", None)
    if callable(setup_fn):
        setup_fn()
    return runtime_app


def _resolve_public_method(runtime_app: Any, method_name: str) -> Any | None:
    """Resolve a public method on ``runtime_app``, rejecting private/dunder names."""
    if not method_name or method_name.startswith("_"):
        return None
    method = getattr(runtime_app, method_name, None)
    return method if callable(method) else None


@app.get("/")
def health_check() -> dict[str, str]:
    """Health check endpoint for Agent Runtime liveness and readiness probes."""
    return {"status": "ok"}


@app.post("/api/reasoning_engine")
async def query_endpoint(request: QueryRequest) -> responses.JSONResponse:
    """Serve unary and async ``class_method`` invocations (``:query``)."""
    runtime_app = get_runtime_app()
    method = _resolve_public_method(runtime_app, request.class_method)
    if method is None:
        return responses.JSONResponse(
            status_code=400,
            content={"error": f"Method {request.class_method!r} not found on agent"},
        )

    output = await _invoke_method(method, request.input or {})
    try:
        serialized = encoders.jsonable_encoder({"output": output})
    except ValueError:
        logger.exception("Failed to JSON-encode unary response for %s", request.class_method)
        raise
    return responses.JSONResponse(content=serialized)


@app.post("/api/stream_reasoning_engine")
async def stream_query_endpoint(request: QueryRequest) -> responses.StreamingResponse:
    """Serve streaming ``class_method`` invocations (``:streamQuery?alt=sse``) as NDJSON."""
    runtime_app = get_runtime_app()
    method = _resolve_public_method(runtime_app, request.class_method)
    if method is None:
        return responses.StreamingResponse(
            content=iter([json.dumps({"error": f"Method {request.class_method!r} not found"}) + "\n"]),
            status_code=400,
            media_type="application/json",
        )

    output = await _invoke_method(method, request.input or {})
    return responses.StreamingResponse(
        content=_ndjson_stream(output),
        media_type="application/json",
    )


@app.get("/is_busy")
def keep_alive_endpoint() -> responses.JSONResponse:
    """Optional keep-alive probe endpoint (200 = busy, 412 = eligible for scale-down)."""
    runtime_app = get_runtime_app()
    if getattr(runtime_app, "has_active_background_tasks", False):
        return responses.JSONResponse(status_code=200, content={"status": "busy"})
    return responses.JSONResponse(status_code=412, content={"status": "idle"})


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
