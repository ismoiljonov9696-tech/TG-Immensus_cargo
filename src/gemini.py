"""Gemini REST klienti.

Google API sirtlari tez-tez o'zgaradi, shuning uchun bu klient himoyalangan:
grounding (Google qidiruvi) uchun bir nechta ma'lum shakl ketma-ket sinaladi va
qaysi biri ishlagani eslab qolinadi. Shu sabab modelni config'dan almashtirish
yetarli — kodni qayta yozish shart emas.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import requests

LOG = logging.getLogger("gemini")
BASE = "https://generativelanguage.googleapis.com/v1beta"
TIMEOUT = 180

# Grounding tool'ining bo'lishi mumkin bo'lgan shakllari — birinchi ishlagani eslanadi
_SEARCH_TOOL_SHAPES: list[list[dict]] = [
    [{"google_search": {}}],
    [{"googleSearch": {}}],
    [{"google_search_retrieval": {}}],
]
_working_search_shape: list[dict] | None = None


class GeminiError(RuntimeError):
    pass


def _post(model: str, payload: dict, api_key: str, retries: int = 3) -> dict:
    url = f"{BASE}/models/{model}:generateContent"
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                json=payload,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:      # tarmoq xatosi
            last_err = exc
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200:
            return resp.json()

        # 429 / 5xx — qayta urinamiz
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
            wait = 2 ** attempt * 5
            LOG.warning("Gemini %s → %s, %ss dan keyin qayta urinaman", model, resp.status_code, wait)
            time.sleep(wait)
            continue

        raise GeminiError(f"Gemini {model} → HTTP {resp.status_code}: {resp.text[:600]}")

    raise GeminiError(f"Gemini {model} javob bermadi: {last_err}")


def _extract_text(data: dict) -> str:
    parts: list[str] = []
    for cand in data.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            if isinstance(part.get("text"), str):
                parts.append(part["text"])
    return "".join(parts).strip()


def _extract_sources(data: dict) -> list[dict]:
    """Grounding metadata'dan manba havolalarini oladi."""
    out: list[dict] = []
    for cand in data.get("candidates", []):
        meta = cand.get("groundingMetadata") or cand.get("grounding_metadata") or {}
        for chunk in meta.get("groundingChunks", []) or meta.get("grounding_chunks", []) or []:
            web = chunk.get("web") or {}
            if web.get("uri"):
                out.append({"title": web.get("title") or web["uri"], "url": web["uri"]})
    # takrorlarni olib tashlash
    seen, uniq = set(), []
    for s in out:
        if s["url"] not in seen:
            seen.add(s["url"])
            uniq.append(s)
    return uniq


# --------------------------------------------------------------------------- #
#  Matn
# --------------------------------------------------------------------------- #
def generate_text(
    prompt: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    *,
    system: str | None = None,
    json_schema: dict | None = None,
    temperature: float = 0.8,
) -> str:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    if system:
        payload["systemInstruction"] = {"parts": [{"text": system}]}
    if json_schema:
        payload["generationConfig"]["response_mime_type"] = "application/json"
        payload["generationConfig"]["response_schema"] = json_schema

    data = _post(model, payload, api_key)
    text = _extract_text(data)
    if not text:
        raise GeminiError(f"Bo'sh javob: {json.dumps(data)[:400]}")
    return text


def generate_json(prompt: str, api_key: str, schema: dict, **kw) -> Any:
    raw = generate_text(prompt, api_key, json_schema=schema, **kw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Ba'zan model JSON'ni ```json blokka o'raydi
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(cleaned)


def generate_grounded(
    prompt: str,
    api_key: str,
    model: str = "gemini-2.5-flash",
    *,
    system: str | None = None,
    temperature: float = 0.7,
) -> tuple[str, list[dict]]:
    """Google qidiruvi bilan. (matn, manbalar) qaytaradi."""
    global _working_search_shape

    shapes = [_working_search_shape] if _working_search_shape else list(_SEARCH_TOOL_SHAPES)
    last_err: Exception | None = None

    for shape in shapes:
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": shape,
            "generationConfig": {"temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        try:
            data = _post(model, payload, api_key, retries=2)
        except GeminiError as exc:
            last_err = exc
            LOG.info("Grounding shakli ishlamadi (%s), keyingisini sinayman", list(shape[0])[0])
            continue
        _working_search_shape = shape
        return _extract_text(data), _extract_sources(data)

    # Qidiruvsiz ham bo'lsa ishlashi kerak — to'liq to'xtab qolmasin
    LOG.warning("Google qidiruvi ulanmadi (%s). Qidiruvsiz davom etaman.", last_err)
    return generate_text(prompt, api_key, model=model, system=system, temperature=temperature), []


# --------------------------------------------------------------------------- #
#  Rasm (Nano Banana)
# --------------------------------------------------------------------------- #
def _image_once(prompt: str, api_key: str, model: str, aspect_ratio: str) -> bytes:
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": aspect_ratio},
        },
    }
    try:
        data = _post(model, payload, api_key, retries=2)
    except GeminiError as exc:
        if "404" in str(exc) or "NOT_FOUND" in str(exc):
            raise                                   # model yo'q — soddalashtirish yordam bermaydi
        # Ba'zi modellar imageConfig / responseModalities ni qabul qilmaydi
        LOG.info("Rasm so'rovi rad etildi (%s), soddalashtirilgan shaklda sinayman", str(exc)[:110])
        data = _post(model, {"contents": [{"role": "user", "parts": [{"text": prompt}]}]},
                     api_key, retries=2)

    for cand in data.get("candidates", []):
        for part in (cand.get("content") or {}).get("parts", []):
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                return base64.b64decode(blob["data"])

    raise GeminiError(f"Rasm qaytmadi. Javob: {json.dumps(data)[:300]}")


def generate_image(
    prompt: str,
    api_key: str,
    model: str = "gemini-3.1-flash-image",
    *,
    aspect_ratio: str = "1:1",
    fallbacks: list[str] | None = None,
) -> tuple[bytes, str]:
    """Rasm generatsiya qiladi. (baytlar, ishlagan model nomi) qaytaradi.

    Google model nomlarini tez-tez o'zgartiradi va eskisini o'chiradi.
    Asosiy model 404 bersa, zaxira ro'yxatidan keyingisi sinaladi —
    shunda bitta noto'g'ri nom butun rasmni yo'qotmaydi.
    """
    chain = [model] + [m for m in (fallbacks or []) if m and m != model]
    last: Exception | None = None

    for i, name in enumerate(chain):
        try:
            data = _image_once(prompt, api_key, name, aspect_ratio)
            if i:
                LOG.warning("Rasm zaxira model bilan yaratildi: %s "
                            "(config.yaml da image.model ni shunga o'zgartiring)", name)
            return data, name
        except GeminiError as exc:
            last = exc
            if "404" in str(exc) or "NOT_FOUND" in str(exc):
                LOG.warning("Model topilmadi: %s — keyingisini sinayman", name)
                continue
            raise

    raise GeminiError(
        f"Hech bir rasm modeli ishlamadi. Sinalganlar: {', '.join(chain)}. "
        f"Oxirgi xato: {last}"
    )
