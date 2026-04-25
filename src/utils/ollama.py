"""Helpers for interacting with Ollama's local APIs."""

from __future__ import annotations

import base64
import io
import json
import os
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib import error, request

from PIL import Image

DEFAULT_OLLAMA_HOST = "http://localhost:11434"


class OllamaRequestError(RuntimeError):
    """Raised when the Ollama host returns an invalid response."""


@dataclass(frozen=True)
class OllamaModelInfo:
    """Normalized Ollama model metadata for the API/UI layer."""

    name: str
    size: int
    modified: str
    digest: str
    format: str
    family: str
    capabilities: list[str]
    can_prompt: bool
    can_vision: bool
    can_image: bool


def ollama_host() -> str:
    """Return the configured Ollama host without a trailing slash."""
    return os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip("/")


def _request_json(
    path: str,
    *,
    payload: Optional[dict[str, Any]] = None,
    timeout: int = 60,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{ollama_host()}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = body
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                detail = (
                    (
                        parsed.get("error", {}).get("message")
                        if isinstance(parsed.get("error"), dict)
                        else parsed.get("error")
                    )
                    or parsed.get("detail")
                    or body
                )
        raise OllamaRequestError(
            f"Ollama request to {path} failed with {exc.code}: {detail or exc.reason}"
        ) from exc
    except error.URLError as exc:
        raise OllamaRequestError(
            f"Failed to reach Ollama at {ollama_host()}: {exc.reason}"
        ) from exc

    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OllamaRequestError(f"Ollama returned invalid JSON for {path}: {raw[:200]!r}") from exc

    if not isinstance(parsed, dict):
        raise OllamaRequestError(f"Ollama returned an unexpected payload for {path}")

    return parsed


def get_ollama_version(timeout: int = 10) -> str:
    """Return the Ollama host version."""
    return str(_request_json("/api/version", timeout=timeout).get("version", ""))


def show_ollama_model(model_name: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch detailed metadata for one Ollama model."""
    return _request_json("/api/show", payload={"model": model_name}, timeout=timeout)


def _normalize_capabilities(capabilities: Iterable[Any]) -> list[str]:
    return sorted({str(capability).strip().lower() for capability in capabilities if capability})


def list_ollama_models(timeout: int = 30) -> list[OllamaModelInfo]:
    """Fetch installed Ollama models plus their capability metadata."""
    tags_payload = _request_json("/api/tags", timeout=timeout)
    models: list[OllamaModelInfo] = []

    for raw_model in tags_payload.get("models", []):
        name = str(raw_model.get("name") or raw_model.get("model") or "").strip()
        if not name:
            continue

        tag_details = raw_model.get("details") or {}
        try:
            show_payload = show_ollama_model(name, timeout=timeout)
        except OllamaRequestError:
            show_payload = {}

        show_details = show_payload.get("details") or {}
        capabilities = _normalize_capabilities(show_payload.get("capabilities") or [])

        details = {
            "format": str(show_details.get("format") or tag_details.get("format") or ""),
            "family": str(show_details.get("family") or tag_details.get("family") or ""),
        }
        if not capabilities and details["format"].lower() == "safetensors":
            capabilities = ["image"]

        models.append(
            OllamaModelInfo(
                name=name,
                size=int(raw_model.get("size") or 0),
                modified=str(raw_model.get("modified_at") or ""),
                digest=str(raw_model.get("digest") or ""),
                format=details["format"],
                family=details["family"],
                capabilities=capabilities,
                can_prompt="completion" in capabilities,
                can_vision="vision" in capabilities,
                can_image="image" in capabilities,
            )
        )

    return models


def _match_model_name(
    configured_name: Optional[str],
    models: list[OllamaModelInfo],
) -> Optional[str]:
    if not configured_name:
        return None

    configured_name = configured_name.strip()
    model_names = {model.name for model in models}

    if configured_name in model_names:
        return configured_name

    if ":" not in configured_name:
        latest_name = f"{configured_name}:latest"
        if latest_name in model_names:
            return latest_name

    if configured_name.endswith(":latest"):
        bare_name = configured_name[: -len(":latest")]
        if bare_name in model_names:
            return bare_name

    return None


def resolve_ollama_model(
    models: list[OllamaModelInfo],
    configured_name: Optional[str],
    capability: str,
) -> Optional[str]:
    """Pick a usable model for the requested capability."""
    matched_name = _match_model_name(configured_name, models)
    if matched_name:
        matched_model = next(model for model in models if model.name == matched_name)
        if capability in matched_model.capabilities:
            return matched_model.name

    candidate_models = [model for model in models if capability in model.capabilities]
    if capability == "completion":
        candidate_models.sort(key=lambda model: (model.size <= 0, model.size, model.name))

    for model in candidate_models:
        if capability in model.capabilities:
            return model.name

    return None


def generate_image_via_ollama(
    *,
    model_name: str,
    prompt: str,
    width: int,
    height: int,
    timeout: int = 300,
) -> Image.Image:
    """Generate one image through Ollama's OpenAI-compatible image endpoint."""
    payload = json.dumps(
        {
            "model": model_name,
            "prompt": prompt,
            "size": f"{width}x{height}",
            "response_format": "b64_json",
        }
    ).encode("utf-8")

    req = request.Request(
        f"{ollama_host()}/v1/images/generations",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
            content_type = response.headers.get("Content-Type", "")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        detail = body
        if body:
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                detail = (
                    (
                        parsed.get("error", {}).get("message")
                        if isinstance(parsed.get("error"), dict)
                        else parsed.get("error")
                    )
                    or parsed.get("detail")
                    or body
                )
        raise OllamaRequestError(
            f"Ollama image generation failed with {exc.code}: {detail or exc.reason}"
        ) from exc
    except error.URLError as exc:
        raise OllamaRequestError(
            f"Failed to reach Ollama at {ollama_host()}: {exc.reason}"
        ) from exc

    encoded_image = _extract_image_payload(raw, content_type)
    if not encoded_image:
        raise OllamaRequestError(
            "Ollama accepted the image-generation request but returned no image bytes. "
            "The host may not fully support the experimental image API yet."
        )

    if encoded_image.startswith("data:image/"):
        encoded_image = encoded_image.split(",", 1)[-1]

    try:
        image_bytes = base64.b64decode(encoded_image)
    except Exception as exc:  # noqa: BLE001 - convert to one consistent backend error
        raise OllamaRequestError("Ollama returned invalid base64 image data") from exc

    try:
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        return image.convert("RGB")
    except Exception as exc:  # noqa: BLE001 - convert to one consistent backend error
        raise OllamaRequestError("Ollama returned unreadable image data") from exc


def _extract_image_payload(raw: bytes, content_type: str) -> Optional[str]:
    if not raw:
        return None

    decoded = raw.decode("utf-8", errors="replace")

    if "ndjson" in content_type:
        payloads = []
        for line in decoded.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payloads.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        for payload in reversed(payloads):
            encoded = _extract_image_field(payload)
            if encoded:
                return encoded
        return None

    try:
        payload = json.loads(decoded)
    except json.JSONDecodeError:
        return None

    return _extract_image_field(payload)


def _extract_image_field(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None

    data_items = payload.get("data")
    if isinstance(data_items, list):
        for item in data_items:
            if not isinstance(item, dict):
                continue
            encoded = item.get("b64_json") or item.get("image") or item.get("b64")
            if isinstance(encoded, str) and encoded:
                return encoded

    direct_value = payload.get("b64_json") or payload.get("image")
    if isinstance(direct_value, str) and direct_value:
        return direct_value

    return None
