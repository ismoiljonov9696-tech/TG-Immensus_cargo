"""OpenAI Responses, Web Search va Image API klienti.

Tashqi SDK o'rnatmaydi: loyiha allaqachon ishlatadigan ``requests`` orqali
rasmiy REST endpointlariga ulanadi. Funksiya imzolari eski AI klienti bilan
bir xil, shuning uchun agentlar provayderni bilishi shart emas.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import requests

LOG = logging.getLogger("openai")
BASE = "https://api.openai.com/v1"
TIMEOUT = 240

# Faqat ichki taxminiy xarajat hisoboti uchun. Haqiqiy summa OpenAI billingda.
PRICE_TEXT_IN = 0.75 / 1_000_000
PRICE_TEXT_OUT = 4.50 / 1_000_000
EST_IMAGE_COST = 0.05

_usage: list[dict] = []


class OpenAIError(RuntimeError):
    pass


def reset_usage() -> None:
    _usage.clear()


def usage_total() -> float:
    return sum(float(item.get("cost", 0)) for item in _usage)


def usage_breakdown() -> list[dict]:
    return list(_usage)


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _request_json(method: str, path: str, api_key: str, *, retries: int = 3,
                  **kwargs) -> dict:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.request(
                method,
                f"{BASE}{path}",
                headers=_headers(api_key),
                timeout=TIMEOUT,
                **kwargs,
            )
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 ** attempt)
            continue

        if response.status_code in (200, 201):
            return response.json()
        if response.status_code in (408, 409, 429, 500, 502, 503, 504) and attempt < retries - 1:
            wait = 5 * (2 ** attempt)
            LOG.warning("OpenAI HTTP %s, %ss dan keyin qayta urinaman",
                        response.status_code, wait)
            time.sleep(wait)
            continue
        raise OpenAIError(
            f"OpenAI {path} → HTTP {response.status_code}: {response.text[:700]}"
        )
    raise OpenAIError(f"OpenAI {path} javob bermadi: {last}")


def _response_text(data: dict) -> str:
    parts: list[str] = []
    for item in data.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "".join(parts).strip()


def _response_sources(data: dict) -> list[dict]:
    found: list[dict] = []
    for item in data.get("output") or []:
        if item.get("type") == "message":
            for content in item.get("content") or []:
                for annotation in content.get("annotations") or []:
                    if annotation.get("type") == "url_citation" and annotation.get("url"):
                        found.append({
                            "title": annotation.get("title") or annotation["url"],
                            "url": annotation["url"],
                        })
        if item.get("type") == "web_search_call":
            for source in (item.get("action") or {}).get("sources") or []:
                if source.get("url"):
                    found.append({
                        "title": source.get("title") or source["url"],
                        "url": source["url"],
                    })
    unique: list[dict] = []
    seen: set[str] = set()
    for source in found:
        if source["url"] not in seen:
            seen.add(source["url"])
            unique.append(source)
    return unique


def _track_text(model: str, data: dict) -> None:
    usage = data.get("usage") or {}
    tokens_in = int(usage.get("input_tokens", 0) or 0)
    tokens_out = int(usage.get("output_tokens", 0) or 0)
    cost = tokens_in * PRICE_TEXT_IN + tokens_out * PRICE_TEXT_OUT
    _usage.append({
        "model": model,
        "kind": "text",
        "prompt_tokens": tokens_in,
        "output_tokens": tokens_out,
        "cost": round(cost, 5),
    })


def _normalize_schema(value: Any) -> Any:
    """Gemini uslubidagi JSON Schema'ni OpenAI strict schema'ga moslaydi."""
    if isinstance(value, list):
        return [_normalize_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {key: _normalize_schema(item) for key, item in value.items()}
    if isinstance(out.get("type"), str):
        out["type"] = out["type"].lower()
    if out.get("type") == "object":
        out["additionalProperties"] = False
    return out


def _input(prompt: str, system: str | None) -> list[dict]:
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def generate_text(prompt: str, api_key: str, model: str = "gpt-5.4-mini", *,
                  system: str | None = None, json_schema: dict | None = None,
                  temperature: float = 0.8) -> str:
    del temperature  # GPT-5 oilasida standart sozlama barqarorroq.
    payload: dict[str, Any] = {
        "model": model,
        "input": _input(prompt, system),
        "store": False,
    }
    if json_schema:
        payload["text"] = {
            "format": {
                "type": "json_schema",
                "name": "result",
                "schema": _normalize_schema(json_schema),
                "strict": True,
            }
        }
    data = _request_json("POST", "/responses", api_key, json=payload)
    _track_text(model, data)
    text = _response_text(data)
    if not text:
        raise OpenAIError(f"OpenAI bo'sh javob qaytardi: {json.dumps(data)[:500]}")
    return text


def generate_json(prompt: str, api_key: str, schema: dict, **kwargs) -> Any:
    raw = generate_text(prompt, api_key, json_schema=schema, **kwargs)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)


def generate_grounded(prompt: str, api_key: str, model: str = "gpt-5.4-mini", *,
                      system: str | None = None,
                      temperature: float = 0.7) -> tuple[str, list[dict]]:
    del temperature
    payload = {
        "model": model,
        "input": _input(prompt, system),
        "tools": [{"type": "web_search"}],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
        "store": False,
    }
    try:
        data = _request_json("POST", "/responses", api_key, json=payload, retries=2)
        _track_text(model, data)
        text = _response_text(data)
        if text:
            return text, _response_sources(data)
    except OpenAIError as exc:
        LOG.warning("OpenAI web search ishlamadi (%s); qidiruvsiz davom etaman", exc)
    return generate_text(prompt, api_key, model=model, system=system), []


def _image_size(aspect_ratio: str) -> str:
    return {
        "1:1": "1024x1024",
        "4:5": "1024x1280",
        "16:9": "1536x864",
        "3:2": "1536x1024",
    }.get(aspect_ratio, "1024x1024")


def generate_image(prompt: str, api_key: str,
                   model: str = "gpt-image-2.5-flare", *,
                   aspect_ratio: str = "1:1",
                   fallbacks: list[str] | None = None) -> tuple[bytes, str]:
    models = [model] + [m for m in (fallbacks or []) if m and m != model]
    last: Exception | None = None
    for name in models:
        try:
            data = _request_json("POST", "/images/generations", api_key, retries=2, json={
                "model": name,
                "prompt": prompt,
                "size": _image_size(aspect_ratio),
                "quality": "medium",
                "output_format": "png",
            })
            encoded = ((data.get("data") or [{}])[0]).get("b64_json")
            if not encoded:
                raise OpenAIError("OpenAI Image API rasm baytlarini qaytarmadi")
            _usage.append({"model": name, "kind": "image", "cost": EST_IMAGE_COST})
            return base64.b64decode(encoded), name
        except OpenAIError as exc:
            last = exc
            LOG.warning("Rasm modeli ishlamadi: %s (%s)", name, str(exc)[:150])
    raise OpenAIError(f"Hech bir OpenAI rasm modeli ishlamadi: {last}")


def edit_image(prompt: str, images: list[bytes], api_key: str,
               model: str = "gpt-image-2.5-flare", *,
               fallbacks: list[str] | None = None,
               mime: str = "image/png") -> bytes:
    models = [model] + [m for m in (fallbacks or []) if m and m != model]
    last: Exception | None = None
    for name in models:
        files = [
            ("image[]", (f"image-{index}.png", blob, mime))
            for index, blob in enumerate(images)
        ]
        try:
            response = requests.post(
                f"{BASE}/images/edits",
                headers={"Authorization": f"Bearer {api_key}"},
                data={
                    "model": name,
                    "prompt": prompt,
                    "quality": "medium",
                    "output_format": "png",
                },
                files=files,
                timeout=TIMEOUT,
            )
            if response.status_code != 200:
                raise OpenAIError(f"OpenAI image edit HTTP {response.status_code}: {response.text[:500]}")
            encoded = ((response.json().get("data") or [{}])[0]).get("b64_json")
            if not encoded:
                raise OpenAIError("Tahrirlangan rasm qaytmadi")
            _usage.append({"model": name, "kind": "image_edit", "cost": EST_IMAGE_COST})
            return base64.b64decode(encoded)
        except (requests.RequestException, OpenAIError) as exc:
            last = exc
            LOG.warning("OpenAI rasm tahriri ishlamadi: %s", str(exc)[:160])
    raise OpenAIError(f"Rasmni tahrirlab bo'lmadi: {last}")

