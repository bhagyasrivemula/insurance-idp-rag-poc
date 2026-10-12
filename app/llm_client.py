"""
Thin wrapper around the OpenAI API.

The rest of the application only calls these functions:

    embed(texts)                  -> vectors for documents and questions
    generate_json(prompt, schema) -> structured extraction (IDP key facts)
    stream_chat(messages)         -> the chatbot's answer, token by token
    complete(messages)            -> a short non-streamed reply (query rewriting)
    moderate(text)                -> OpenAI safety classification (guardrails)
    is_available()                -> health/status for the UI and the pipeline

When LangSmith tracing is enabled, the client is wrapped with `wrap_openai`,
so every OpenAI call is recorded in the trace automatically.
"""
from __future__ import annotations

import json
import time
from typing import Iterator

from openai import OpenAI

from app import config

_client: OpenAI | None = None
_health_cache: tuple[float, dict] | None = None


def _openai() -> OpenAI:
    """Create the client on first use, with a clear message if the key is missing."""
    global _client
    if _client is None:
        if not config.OPENAI_API_KEY:
            raise RuntimeError("OPENAI_API_KEY is not set. Add it to the .env file (see .env.example).")
        _client = OpenAI(api_key=config.OPENAI_API_KEY, timeout=120, max_retries=3)
        if config.TRACING_ENABLED:
            from langsmith.wrappers import wrap_openai
            _client = wrap_openai(_client)
    return _client


def _strict_schema(schema: dict) -> dict:
    """
    OpenAI "strict" structured outputs require every object to forbid extra keys
    and to list all of its properties as required. Applied recursively.
    """
    schema = dict(schema)
    if schema.get("type") == "object":
        props = {k: _strict_schema(v) for k, v in schema.get("properties", {}).items()}
        schema.update(properties=props, required=list(props), additionalProperties=False)
    elif schema.get("type") == "array" and "items" in schema:
        schema["items"] = _strict_schema(schema["items"])
    return schema


def _accepts_temperature(model: str) -> bool:
    """Reasoning models (o-series, gpt-5 family) reject a custom temperature."""
    return not model.startswith(("o1", "o3", "o4", "gpt-5"))


def is_available() -> dict:
    """Check the key works and the configured models are available to it (cached for 60 s)."""
    global _health_cache
    if _health_cache and time.time() - _health_cache[0] < 60:
        return _health_cache[1]
    try:
        ids = {m.id for m in _openai().models.list()}
        status = {
            "reachable": True,
            "error": "",
            "chat_model_ready": config.CHAT_MODEL in ids,
            "extract_model_ready": config.EXTRACT_MODEL in ids,
            "embed_model_ready": config.EMBED_MODEL in ids,
        }
    except Exception as exc:  # missing/invalid key, no internet, ...
        status = {"reachable": False, "error": f"{type(exc).__name__}: {exc}"[:300],
                  "chat_model_ready": False, "extract_model_ready": False, "embed_model_ready": False}
    _health_cache = (time.time(), status)
    return status


def embed(texts: list[str], batch_size: int = 256) -> list[list[float]]:
    """Embed documents or questions (OpenAI embeddings need no query/document distinction)."""
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        resp = _openai().embeddings.create(model=config.EMBED_MODEL, input=texts[start:start + batch_size])
        vectors.extend(item.embedding for item in sorted(resp.data, key=lambda d: d.index))
    return vectors


def generate_json(prompt: str, schema: dict, system: str = "") -> dict:
    """Return model output that conforms to `schema` (used by the IDP key-fact stage)."""
    params = {
        "model": config.EXTRACT_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": "extraction", "strict": True, "schema": _strict_schema(schema)},
        },
    }
    if _accepts_temperature(config.EXTRACT_MODEL):
        params["temperature"] = 0
    resp = _openai().chat.completions.create(**params)
    return json.loads(resp.choices[0].message.content)


def complete(messages: list[dict], max_tokens: int = 200) -> str:
    """A short, deterministic, non-streamed reply from the chat model."""
    params = {"model": config.CHAT_MODEL, "messages": messages, "max_tokens": max_tokens}
    if _accepts_temperature(config.CHAT_MODEL):
        params["temperature"] = 0
    return (_openai().chat.completions.create(**params).choices[0].message.content or "").strip()


def moderate(text: str) -> dict:
    """
    OpenAI moderation (free): returns {"flagged": bool, "categories": [names]}.
    Fails open - a moderation outage must not take the assistant down.
    """
    try:
        result = _openai().moderations.create(model=config.MODERATION_MODEL, input=text).results[0]
        categories = [name for name, hit in result.categories.model_dump().items() if hit]
        return {"flagged": bool(result.flagged), "categories": categories}
    except Exception as exc:
        return {"flagged": False, "categories": [], "error": str(exc)[:200]}


def stream_chat(messages: list[dict], temperature: float = 0.1) -> Iterator[str]:
    """Yield the assistant's reply token by token."""
    params = {"model": config.CHAT_MODEL, "messages": messages, "stream": True}
    if _accepts_temperature(config.CHAT_MODEL):
        params["temperature"] = temperature
    for chunk in _openai().chat.completions.create(**params):
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
