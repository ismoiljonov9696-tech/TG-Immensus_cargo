"""1-AGENT — MAVZU IZLOVCHI.

Berilgan rubrikada internetdan yangi mavzular izlaydi (Gemini + Google qidiruvi),
arxiv bilan solishtiradi va takrorlanmagan eng yaxshi mavzuni qaytaradi.
"""
from __future__ import annotations

import logging

from .. import store
from ..gemini import generate_grounded, generate_json

LOG = logging.getLogger("agent1")

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "topics": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "title": {"type": "STRING"},
                    "angle": {"type": "STRING"},
                    "why_now": {"type": "STRING"},
                    "value_score": {"type": "INTEGER"},
                },
                "required": ["title", "angle", "why_now", "value_score"],
            },
        }
    },
    "required": ["topics"],
}


def _search_prompt(rubric: dict, avoid: list[str], lang_name: str) -> str:
    domains = rubric.get("allowed_domains") or []
    domain_line = (
        "Faqat quyidagi manbalardan foydalaning: " + ", ".join(domains)
        if domains else
        "Ishonchli, rasmiy manbalardan foydalaning."
    )
    avoid_block = "\n".join(f"- {t}" for t in avoid[-60:]) or "(hali hech narsa yozilmagan)"

    return f"""Siz kontent tadqiqotchisiz. Telegram kanali uchun mavzu izlayapsiz.

RUBRIKA: {rubric['name']}
TAVSIF: {rubric.get('brief', '').strip()}
AUDITORIYA: {rubric.get('audience', '').strip()}

{domain_line}

Internetdan qidiring va shu rubrikaga mos, HOZIR dolzarb bo'lgan aniq mavzularni toping.
Har bir mavzu bitta amaliy maslahatga aylantirilishi mumkin bo'lsin — umumiy
"AI foydali" turidagi gaplar emas, balki o'quvchi bugun qo'llay oladigan narsa.

QUYIDAGI MAVZULAR ALLAQACHON YOZILGAN — ularni va ularga juda yaqin variantlarni TAKLIF QILMANG:
{avoid_block}

8 ta nomzod toping. Har biri uchun qisqacha yozing:
1. Sarlavha ({lang_name} tilida)
2. Qaysi burchakdan yoritiladi
3. Nega aynan hozir dolzarb
4. Foydalilik bahosi 1–10

Javobni oddiy ro'yxat ko'rinishida bering."""


def _rank_prompt(raw: str, avoid: list[str], lang_name: str) -> str:
    avoid_block = "\n".join(f"- {t}" for t in avoid[-60:]) or "(bo'sh)"
    return f"""Quyidagi tadqiqot natijasidan mavzularni ajratib oling va JSON qiling.

TADQIQOT:
{raw}

Talablar:
- title: {lang_name} tilida, aniq va qisqa (60 belgidan oshmasin)
- angle: qaysi burchakdan yoritiladi (1-2 jumla)
- why_now: nega hozir dolzarb (1 jumla)
- value_score: 1–10 oralig'ida butun son, o'quvchi uchun amaliy foydasi

Quyidagilar bilan bir xil yoki juda yaqin mavzularni TASHLAB YUBORING:
{avoid_block}

value_score bo'yicha kamayish tartibida joylashtiring."""


def run(cfg: dict, rubric: dict, api_key: str) -> dict:
    """Bitta yangi mavzu qaytaradi: {title, angle, why_now, research, sources}"""
    lang_name = {"uz": "o'zbek", "ru": "rus", "en": "ingliz"}.get(
        cfg["channel"].get("language", "uz"), "o'zbek"
    )
    model = cfg["llm"]["model"]
    avoid = store.archived_titles(rubric["name"])

    LOG.info("Mavzu izlanmoqda — rubrika: %s (arxivda %d ta)", rubric["name"], len(avoid))
    research, sources = generate_grounded(
        _search_prompt(rubric, avoid, lang_name), api_key, model=model, temperature=0.9
    )
    LOG.info("Qidiruv tugadi, %d manba topildi", len(sources))

    data = generate_json(
        _rank_prompt(research, avoid, lang_name), api_key, SCHEMA, model=model, temperature=0.3
    )
    topics = data.get("topics") or []
    if not topics:
        raise RuntimeError("1-agent hech qanday mavzu topmadi")

    for topic in sorted(topics, key=lambda t: -int(t.get("value_score", 0))):
        if store.is_used(topic["title"]):
            LOG.info("Takror, tashlandi: %s", topic["title"])
            continue
        LOG.info("Tanlandi: %s (%s ball)", topic["title"], topic.get("value_score"))
        return {
            "title": topic["title"],
            "angle": topic.get("angle", ""),
            "why_now": topic.get("why_now", ""),
            "research": research,
            "sources": sources,
        }

    raise RuntimeError(
        "Barcha topilgan mavzular arxivda bor. Rubrikani kengaytiring yoki "
        "data/archive.json dagi eski yozuvlarni tozalang."
    )
