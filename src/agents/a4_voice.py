"""4-AGENT — OVOZ.

Post matnini Azure Speech (uz-UZ) orqali audioga aylantiradi.
Avval matnni ovoz uchun qayta yozadi: yozma matn va og'zaki nutq boshqacha.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..azure_tts import synthesize
from ..gemini import generate_text

LOG = logging.getLogger("agent4")

SYSTEM = """Siz matnni ovozli o'qish uchun tayyorlaysiz. Faqat tayyor matnni
qaytaring — izohsiz, sarlavhasiz, belgilarsiz."""


def _spoken_version(post_text: str, api_key: str, model: str, lang_name: str) -> str:
    prompt = f"""Quyidagi Telegram postini ovozli o'qish uchun qayta yozing.

POST:
{post_text}

Qoidalar:
- Til: {lang_name}
- Ma'no o'zgarmasin, faqat og'zaki nutqqa moslashtiring
- Emoji, hashtag, havola, telefon raqam va "izohda yozing" kabi CTA larni olib tashlang
- Ro'yxatlarni jonli jumlalarga aylantiring ("birinchidan", "ikkinchidan")
- Boshida 1 ta qisqa jumla bilan salomlashing, oxirida 1 ta jumla bilan yakunlang
- 45–75 soniyada o'qiladigan hajm

Faqat matnni qaytaring."""
    return generate_text(prompt, api_key, model=model, system=SYSTEM, temperature=0.6).strip()


def run(cfg: dict, post_text: str, out_path: Path,
        gemini_key: str, azure_key: str, azure_region: str) -> tuple[Path, str]:
    a = cfg["audio"]
    lang_name = {"uz": "o'zbek", "ru": "rus", "en": "ingliz"}.get(
        cfg["channel"].get("language", "uz"), "o'zbek"
    )

    spoken = _spoken_version(post_text, gemini_key, cfg["llm"]["model"], lang_name)
    LOG.info("Ovoz matni tayyor: %d belgi", len(spoken))

    audio = synthesize(
        spoken,
        azure_key,
        azure_region,
        voice=a.get("voice", "uz-UZ-SardorNeural"),
        rate=a.get("rate", "+0%"),
        pitch=a.get("pitch", "+0%"),
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(audio)
    LOG.info("Audio saqlandi: %s (%.0f KB)", out_path.name, len(audio) / 1024)
    return out_path, spoken
