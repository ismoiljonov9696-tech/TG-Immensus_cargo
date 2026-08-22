"""3-AGENT — RASSOM.

Post matnidan rasm tavsifi tuzadi va Nano Banana orqali rasm chizadi,
so'ng ustiga kompaniya logotipini qo'yadi.

Rasm mavzudan kelib chiqadi, mavzu esa rasmdan emas:
  1. Avval postning ASOSIY DARSI ajratiladi — post aynan nimani o'rgatyapti.
  2. Shu darsni ko'rsatadigan UCHTA turli g'oya o'ylab topiladi va
     "kutilmaganlik" bo'yicha baholanadi. Eng kutilmagani tanlanadi.
     Bitta so'rovda tavsif so'ralsa, model doim eng zerikarlisini beradi.
  3. Klishelar aniq taqiqlangan: quti uyumi, dunyo xaritasi, globus,
     qo'l siqish, o'suvchi diagramma.
  4. Kompozitsiya 7 ta uslubdan navbat bilan olinadi — lenta bir xil bo'lmaydi.
  5. Xitoy muhiti majburiy emas: sahna talab qilsa qo'yiladi, aks holda
     g'oya stol ustida yoki qo'lda ham ko'rsatilishi mumkin.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from ..branding import apply_logo
from ..config import ROOT
from ..gemini import generate_image, generate_json

LOG = logging.getLogger("agent3")

PROMPT_SYSTEM = """Siz reklama agentligining art-direktorisiz. Sizning ishingiz —
zerikarli, oldindan aytib bo'ladigan tasvirdan qochish.

Quyidagilar KLISHE va ular taqiqlanadi: bir-birining ustiga qalangan
bir xil qutilar, dunyo xaritasi ustidagi punktir chiziq, konteyner uyumi
umumiy planda, kompas, globus, qo'l siqish, ko'tarilayotgan diagramma,
sun'iy tabassumli ofis xodimi.

Yaxshi rasm bitta aniq g'oyani ko'rsatadi va uni kutilmagan burchakdan
ko'rsatadi. Tavsifda hech qachon matn, harf, raqam, iyeroglif yoki
logotip bo'lishini so'ramang."""

# Kompozitsiya uslublari — har post uchun bittasi tanlanadi.
# Shuning uchun kanal lentasi bir xil rasmlar qatoriga aylanmaydi.
COMPOSITIONS = [
    "extreme close-up on the key object, shallow depth of field, the rest softly blurred",
    "isometric 3/4 view of a small diorama-like scene, clean drop shadows",
    "wide establishing shot of the environment, one human figure small in frame for scale",
    "top-down flat-lay of the objects arranged neatly on a surface",
    "split composition contrasting two states side by side, clear visual divide",
    "over-the-shoulder view of hands working with the objects, face out of frame",
    "single bold symbolic object centered on a clean background, generous negative space",
]

# Xitoy konteksti — MAJBURIY emas, sahna tabiiy talab qilgandagina.
# Har rasmni bozorga tiqishtirish aynan bir xillikka olib keladi.
CHINA_CUES = (
    "If the scene naturally involves a place, make it read as the Chinese trade "
    "world — Yiwu-style wholesale aisles, a container terminal, a factory floor, "
    "a packing warehouse. Subtle cues only: roof lines, lanterns, signage shapes "
    "with NO readable characters, red and gold used sparingly. "
    "If the idea is better told on a desk, in a hand, or against a plain "
    "background, do that instead — do not force a market into every picture."
)

IDEA_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "lesson": {"type": "STRING"},
        "ideas": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "concept": {"type": "STRING"},
                    "why_it_works": {"type": "STRING"},
                    "surprise": {"type": "INTEGER"},
                },
                "required": ["concept", "why_it_works", "surprise"],
            },
        },
        "chosen": {"type": "STRING"},
        "prompt": {"type": "STRING"},
    },
    "required": ["lesson", "ideas", "chosen", "prompt"],
}


def _pick_composition(seed: str) -> str:
    idx = int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16) % len(COMPOSITIONS)
    return COMPOSITIONS[idx]


PEOPLE_RULES = {
    "never": (
        "Sahnada odam BO'LMASIN — faqat predmetlar va muhit."
    ),
    "sometimes": (
        "Sahnada odam bo'lishi mumkin, lekin asosiy urg'u predmetda qolsin. "
        "Odam bo'lsa — qo'llari yoki yelka ortidan ko'rinishi yetarli."
    ),
    "often": (
        "Sahnada ODAM BO'LSIN — bu rasmni jonli qiladi va e'tibor tortadi.\n"
        "  · Kim: o'zbek yoki markaziy osiyolik tadbirkor, xitoylik sotuvchi yoki "
        "ombor ishchisi, savdo vakili. Ish kiyimida yoki oddiy kundalik kiyimda.\n"
        "  · Qanday: tabiiy, hujjatli fotosurat kayfiyatida — ish qilayotgan "
        "paytda tutilgan lahza. Kameraga poza bermasin, tabassum sun'iy bo'lmasin.\n"
        "  · Yuz ko'rinishi mumkin, lekin umumlashgan bo'lsin — hech qanday "
        "taniqli yoki real shaxsga o'xshamasin.\n"
        "  · Yosh va jins turlicha bo'lsin: postlar ketma-ketligida bir xil "
        "odam takrorlanmasin."
    ),
}


def _describe(post_text: str, topic_title: str, cfg: dict,
              composition: str, api_key: str, model: str) -> tuple[str, str, str]:
    """Rasm tavsifini tuzadi.

    Bir bosqichda emas, uch bosqichda:
      1. Postning ASOSIY DARSI ajratiladi
      2. Uchta TURLI vizual g'oya o'ylab topiladi va "kutilmaganlik" bo'yicha
         baholanadi
      3. Eng kutilmagani tanlanadi va faqat o'shaning tavsifi yoziladi

    Bitta so'rovda darrov tavsif so'ralsa, model doim eng oddiy va eng
    zerikarli variantni beradi — konteyner va quti. Muqobil variantlarni
    ko'rishga majbur qilish rasmni jonlantiradi.
    """
    img = cfg["image"]
    people = PEOPLE_RULES.get(img.get("people", "often"), PEOPLE_RULES["often"])

    prompt = f"""Quyidagi Telegram posti uchun rasm g'oyasini topasiz.

POST SARLAVHASI: {topic_title}

POST MATNI:
{post_text[:1800]}

BOSQICH 1 — lesson
Post o'quvchiga QANDAY BITTA aniq narsani o'rgatyapti? Bir jumlada yozing.
Umumiy emas, aniq: "to'lovni 30/70 ga bo'lish", "qutining kubini o'lchash",
"sotuvchi litsenziyasini tekshirish".

BOSQICH 2 — ideas (3 ta, BIR-BIRIDAN KESKIN FARQ QILSIN)
Shu darsni ko'rsatadigan uchta turli vizual g'oya. Ular turli yo'ldan borsin:
  · biri — jarayonning aniq lahzasi (qo'l, predmet, harakat)
  · biri — ikki holatning qarama-qarshiligi (to'g'ri / xato, oldin / keyin)
  · biri — kutilmagan metafora (masshtab o'yini, g'ayrioddiy nuqtai nazar,
    predmetning odatiy bo'lmagan holati)

Har biriga:
  concept — sahna nima (2-3 jumla, aniq predmetlar bilan)
  why_it_works — nega u aynan shu darsni ko'rsatadi
  surprise — 1..10, qanchalik kutilmagan. Konteyner, quti uyumi, dunyo
             xaritasi, o'q-yo'nalish chizig'i kabi klishelar 1-3 ball oladi.

BOSQICH 3 — chosen va prompt
surprise eng yuqori bo'lganini tanlang (agar u darsni ham aniq ko'rsatsa).
chosen — qaysi g'oya tanlanganini bir jumlada yozing.
prompt — o'sha g'oyaning INGLIZ TILIDAGI rasm tavsifi, 60-95 so'z.

prompt uchun talablar:
- Aniq jismoniy predmetlar: tarozi, hujjat, plomba, tasma, telefon ekrani,
  pul, javon, o'lchov lentasi, quti. Mavhum tasvir emas.
- Muhit: {CHINA_CUES}
- Kompozitsiya (majburiy): {composition}
- Uslub: {img.get('style', '').strip()}
- Ranglar: {img.get('brand_colors', '')}
- Odamlar: {people}
- Rasmda MATN, HARF, RAQAM, IYEROGLIF, LOGOTIP yoki BAYROQ bo'lmasin —
  buni tavsifda aniq yozing
- Pastki o'ng burchakda logotip uchun toza joy qoldiring"""

    data = generate_json(prompt, api_key, IDEA_SCHEMA, model=model,
                         system=PROMPT_SYSTEM, temperature=1.0)

    ideas = data.get("ideas") or []
    for i in ideas:
        LOG.info("  g'oya (%s ball): %s", i.get("surprise"), str(i.get("concept"))[:88])

    desc = (data.get("prompt") or "").strip().strip('"').strip()
    if not desc:
        raise ValueError("Rasm tavsifi bo'sh qaytdi")
    return desc, data.get("lesson", ""), data.get("chosen", "")


def run(cfg: dict, post_text: str, out_path: Path, api_key: str,
        topic_title: str = "") -> tuple[Path, str]:
    img_cfg = cfg["image"]
    composition = _pick_composition(out_path.parent.name + topic_title)
    LOG.info("Kompozitsiya: %s", composition[:60])

    desc, lesson, chosen = _describe(post_text, topic_title or post_text[:80], cfg,
                                     composition, api_key, cfg["llm"]["model"])
    LOG.info("Post darsi   : %s", lesson[:100])
    LOG.info("Tanlangan    : %s", chosen[:100])
    LOG.info("Rasm tavsifi : %s", desc[:140])

    full_prompt = (
        f"{desc}\n\n"
        f"Composition: {composition}.\n"
        f"Style: {img_cfg.get('style', '').strip()}\n"
        f"Color palette: {img_cfg.get('brand_colors', '')}\n"
        f"Natural documentary lighting, believable human proportions and hands. "
        f"Absolutely no text, letters, numbers, Chinese characters, watermarks, "
        f"flags or logos anywhere in the image. No resemblance to any real or "
        f"famous person. Leave the bottom-right corner visually calm and uncluttered."
    )

    data, used = generate_image(
        full_prompt,
        api_key,
        model=img_cfg["model"],
        aspect_ratio=img_cfg.get("aspect_ratio", "1:1"),
        fallbacks=img_cfg.get("fallback_models") or [],
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(data)
    LOG.info("Rasm saqlandi: %s (%.0f KB, model: %s)", out_path.name, len(data) / 1024, used)

    apply_logo(out_path, cfg, ROOT)
    return out_path, desc
