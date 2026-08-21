"""2-AGENT — YOZUVCHI.

Mavzuni aniq maslahatga aylantiradi va foydalanuvchining stilida post qilib yozadi.
Stilni style/examples.md dagi namuna postlardan o'rganadi.
"""
from __future__ import annotations

import logging

from ..config import style_examples
from ..gemini import generate_text

LOG = logging.getLogger("agent2")

EMOJI_RULE = {
    "none": "Emoji ISHLATMANG.",
    "low": "Emoji juda kam — butun postda 1-2 ta, faqat ma'no qo'shsa.",
    "medium": "Emoji o'rtacha — sarlavhada 1 ta, ro'yxat bandlarida belgilar sifatida. Ortiqcha emas.",
    "high": "Emoji faol ishlatiladi, lekin har jumlada emas.",
}

SYSTEM = """Siz tajribali Telegram kontent muharririsiz. Sizning vazifangiz —
berilgan mavzuni o'quvchi darhol qo'llay oladigan aniq maslahatga aylantirish.

Qat'iy qoidalar:
- Faqat post matnini qaytaring. Izoh, sarlavha belgisi, ```blok``` — hech narsa qo'shmang.
- O'ylab topilgan fakt, raqam yoki iqtibos YOZMANG. Manbada bo'lmagan narsani yozmang.
- Umumiy gap yozmang. Har bir jumla aniq ish yoki aniq ma'lumot bersin.
- Birinchi qator — qarmoq: foyda yoki savol. "Bugun sizga aytmoqchimanki" kabi
  bo'sh boshlanish qat'iyan man etiladi.
- Markdown sarlavhalar (#, ##) ishlatmang — Telegram ularni ko'rsatmaydi."""


def _prompt(cfg: dict, rubric: dict, topic: dict, feedback: str | None) -> str:
    p = cfg["post"]
    lang_name = {"uz": "o'zbek", "ru": "rus", "en": "ingliz"}.get(
        cfg["channel"].get("language", "uz"), "o'zbek"
    )
    examples = style_examples()
    style_block = (
        f"STIL NAMUNALARI — ohang, tuzilish va jumla uzunligini AYNAN shulardan oling:\n\n{examples}"
        if examples else
        "STIL NAMUNASI BERILMAGAN. Ishbilarmon, sodda va aniq ohangda yozing: "
        "qisqa jumlalar, 'siz'lab murojaat, hech qanday quruq marketing tili yo'q."
    )
    fb = f"\n\nOLDINGI URINISH RAD ETILDI. Tuzatilishi kerak:\n{feedback}\n" if feedback else ""

    hashtags = " ".join(p.get("hashtags") or [])

    return f"""{style_block}

────────────────────────
MAVZU: {topic['title']}
BURCHAK: {topic.get('angle', '')}
NEGA HOZIR: {topic.get('why_now', '')}

TADQIQOT MATERIALI (faktlar faqat shundan olinadi):
{topic.get('research', '')[:6000]}
────────────────────────

RUBRIKA: {rubric['name']} — {rubric.get('brief', '').strip()}
AUDITORIYA: {rubric.get('audience', '').strip()}

TALABLAR:
- Til: {lang_name}
- Uzunlik: {p['min_chars']}–{p['max_chars']} belgi
- {EMOJI_RULE.get(p.get('emoji_level', 'medium'), EMOJI_RULE['medium'])}
- Tuzilishi:
  1) Qarmoq — bitta kuchli qator
  2) Muammo yoki kontekst — 1-2 qator
  3) Maslahatning o'zi — aniq qadamlar yoki ro'yxat
  4) Amaliy misol yoki natija
  5) CTA: {p.get('cta', '')}
  6) Oxirgi qator: {hashtags}
{fb}
Faqat tayyor post matnini qaytaring."""


def run(cfg: dict, rubric: dict, topic: dict, api_key: str,
        feedback: str | None = None) -> str:
    text = generate_text(
        _prompt(cfg, rubric, topic, feedback),
        api_key,
        model=cfg["llm"]["model"],
        system=SYSTEM,
        temperature=0.85,
    )
    text = text.strip().strip("`").strip()
    # Model ba'zan "Post:" deb boshlaydi
    for prefix in ("Post:", "POST:", "Matn:"):
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
    LOG.info("Post yozildi: %d belgi", len(text))
    return text
