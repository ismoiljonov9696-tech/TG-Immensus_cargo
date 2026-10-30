"""AI provayder routeri: OpenAI asosiy, Gemini vaqtinchalik zaxira."""
from __future__ import annotations

import os

from . import gemini, openai_api


def provider_name() -> str:
    return "openai" if os.getenv("OPENAI_API_KEY", "").strip() else "gemini"


def _backend():
    return openai_api if provider_name() == "openai" else gemini


def _model(model: str, kind: str = "text") -> str:
    """Config OpenAI'ga o'tgan bo'lsa ham eski Gemini zaxirasini ishlatadi."""
    if provider_name() == "openai":
        if model.startswith("gemini-"):
            return "gpt-image-2.5-flare" if kind == "image" else "gpt-5.4-mini"
        return model
    if model.startswith("gpt-image-"):
        return "gemini-3.1-flash-image"
    if model.startswith("gpt-"):
        return "gemini-3.8-flash"
    return model


def reset_usage() -> None:
    gemini.reset_usage()
    openai_api.reset_usage()


def usage_total() -> float:
    return _backend().usage_total()


def usage_breakdown() -> list[dict]:
    return _backend().usage_breakdown()


def generate_text(prompt: str, api_key: str, model: str = "gpt-5.4-mini", **kwargs):
    return _backend().generate_text(prompt, api_key, model=_model(model), **kwargs)


def generate_json(prompt: str, api_key: str, schema: dict, **kwargs):
    if "model" in kwargs:
        kwargs["model"] = _model(kwargs["model"])
    return _backend().generate_json(prompt, api_key, schema, **kwargs)


def generate_grounded(prompt: str, api_key: str, model: str = "gpt-5.4-mini", **kwargs):
    return _backend().generate_grounded(prompt, api_key, model=_model(model), **kwargs)


def generate_image(prompt: str, api_key: str,
                   model: str = "gpt-image-2.5-flare", **kwargs):
    kwargs["fallbacks"] = [_model(item, "image") for item in kwargs.get("fallbacks") or []]
    return _backend().generate_image(
        prompt, api_key, model=_model(model, "image"), **kwargs
    )


def edit_image(prompt: str, images: list[bytes], api_key: str,
               model: str = "gpt-image-2.5-flare", **kwargs):
    kwargs["fallbacks"] = [_model(item, "image") for item in kwargs.get("fallbacks") or []]
    return _backend().edit_image(
        prompt, images, api_key, model=_model(model, "image"), **kwargs
    )

