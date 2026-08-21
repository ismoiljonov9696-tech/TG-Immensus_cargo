"""3-AGENT — RASSOM.

Post matnidan rasm uchun tavsif tuzadi va Nano Banana (Gemini Image) orqali
rasm generatsiya qiladi.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..gemini import generate_image, generate_text

LOG = logging.getLogger("agent3")

PROMPT_SYSTEM = """Siz rasm uchun tavsif (prompt) yozuvchi mutaxassissiz.
Faqat ingliz tilidagi rasm tavsifini qaytaring — boshqa hech narsa yozmang.
Tavsifda hech qachon matn, harf, raqam yoki logotip bo'lishini so'ramang."""


def _describe(post_text: str, style: str, api_key: str, model: str) -> str:
    prompt = f"""Quyidagi Telegram posti uchun bitta rasm tavsifi yozing.

POST:
{post_text[:1500]}

USLUB TALABI:
{style}

Qoidalar:
- Ingliz tilida, 40-70 so'z
- Bitta aniq vizual metafora — sahna to'ldirilgan bo'lmasin
- Rasmda MATN, HARF, RAQAM yoki LOGOTIP bo'lmasin — buni tavsifda aniq yozing
- Odam yuzi bo'lsa — umumlashgan, taniqli shaxs emas
- Kompozitsiya markazlashgan, ijtimoiy tarmoq uchun

Faqat tavsifni qaytaring."""
    desc = generate_text(prompt, api_key, model=model, system=PROMPT_SYSTEM, temperature=0.9)
    return desc.strip().strip('"').strip()


def run(cfg: dict, post_text: str, out_path: Path, api_key: str) -> tuple[Path, str]:
    img_cfg = cfg["image"]
    desc = _describe(post_text, img_cfg["style"], api_key, cfg["llm"]["model"])
    full_prompt = (
        f"{desc}\n\nStyle: {img_cfg['style'].strip()}\n"
        f"Absolutely no text, letters, numbers, watermarks or logos anywhere in the image."
    )
    LOG.info("Rasm tavsifi: %s", desc[:120])

    data = generate_image(
        full_prompt,
        api_key,
        model=img_cfg["model"],
        aspect_ratio=img_cfg.get("aspect_ratio", "1:1"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    LOG.info("Rasm saqlandi: %s (%.0f KB)", out_path.name, len(data) / 1024)
    return out_path, desc
