"""5-AGENT — SIFAT NAZORATI.

Postni chiqarishdan oldin tekshiradi. Ikki qatlam:
  1) Mexanik tekshiruv (uzunlik, taqiqlangan iboralar, format) — kodda
  2) Mazmun tekshiruvi (fakt, stil, foyda, qarmoq) — model orqali

Model o'zi yozgan matnni baholayotgani uchun unga qat'iy va shubhali
bo'lishi buyuriladi: shubha bo'lsa — rad etsin.
"""
from __future__ import annotations

import logging
import re

from ..config import style_examples
from ..gemini import generate_json

LOG = logging.getLogger("agent5")

SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "approved": {"type": "BOOLEAN"},
        "score": {"type": "INTEGER"},
        "problems": {"type": "ARRAY", "items": {"type": "STRING"}},
        "fix_instructions": {"type": "STRING"},
    },
    "required": ["approved", "score", "problems", "fix_instructions"],
}

# Postda bo'lmasligi kerak bo'lgan izlar
BANNED_PATTERNS = [
    (r"\bAs an AI\b|\bmen sun'iy intellekt\b", "AI ekanini oshkor qilgan"),
    (r"```", "kod bloki qolib ketgan"),
    (r"^#{1,6}\s", "markdown sarlavha ishlatilgan"),
    (r"\[.*?\]\(.*?\)", "markdown havola — Telegram uni ko'rsatmaydi"),
    (r"\{\{.*?\}\}|\[TODO\]|\bLorem ipsum\b", "to'ldirilmagan shablon qolgan"),
    (r"XXXX|\bTBD\b", "to'ldirilmagan joy qolgan"),
]


def _is_cjk(ch: str) -> bool:
    """Xitoy iyeroglifi (CJK) yoki xitoycha tinish belgisimi."""
    o = ord(ch)
    return (
        0x4E00 <= o <= 0x9FFF        # asosiy CJK
        or 0x3400 <= o <= 0x4DBF     # kengaytma A
        or 0xF900 <= o <= 0xFAFF     # moslik belgilari
        or 0xFF01 <= o <= 0xFF60     # kenglikdagi tinish belgilari
        or 0x3000 <= o <= 0x303F     # CJK tinish belgilari
    )


def chinese_stats(text: str) -> tuple[int, float]:
    """(iyerogliflar soni, barcha harflarga nisbatan ulushi)."""
    cjk = sum(1 for ch in text if _is_cjk(ch))
    letters = sum(1 for ch in text if ch.isalpha() or _is_cjk(ch))
    return cjk, (cjk / letters if letters else 0.0)


def _check_chinese(cfg: dict, text: str) -> list[str]:
    """Iyerogliflarga nisbatan qoida.

    Nom va atama sifatida bir nechta iyeroglif — normal holat, ruxsat etiladi.
    Post asosan yoki butunlay xitoycha bo'lib qolsa — rad etiladi.
    """
    p = cfg.get("post", {})
    max_chars = p.get("max_chinese_chars", 40)
    max_ratio = p.get("max_chinese_ratio", 0.15)
    if max_chars is None and max_ratio is None:
        return []

    cjk, ratio = chinese_stats(text)
    if cjk == 0:
        return []

    # Asosiy mezon — ULUSH, son emas. Post o'zbekcha bo'lib, ichida o'nlab
    # nom bo'lishi mumkin (义乌, 阿里巴巴, 拼多多...) — bu normal holat.
    # Son bo'yicha chegara faqat ulush ham sezilarli bo'lgandagina ishlaydi.
    if max_ratio is None:
        return ([f"Juda ko'p xitoycha belgi: {cjk} ta (ruxsat {max_chars})."]
                if max_chars is not None and cjk > int(max_chars) else [])

    limit = float(max_ratio)
    if ratio > limit:
        return [f"Matnning {ratio:.0%} qismi xitoycha (ruxsat {limit:.0%}). "
                f"Post o'zbek tilida yozilsin — iyerogliflar faqat nom va "
                f"atama uchun qolsin."]

    if max_chars is not None and cjk > int(max_chars) and ratio > limit / 2:
        return [f"Xitoycha belgilar juda ko'payib ketdi: {cjk} ta, "
                f"matnning {ratio:.0%} qismi. Nomlarni kamaytiring."]

    return []


def _mechanical(cfg: dict, text: str) -> list[str]:
    p = cfg["post"]
    problems: list[str] = _check_chinese(cfg, text)

    n = len(text)
    if n < p["min_chars"]:
        problems.append(f"Juda qisqa: {n} belgi (kamida {p['min_chars']} kerak)")
    if n > p["max_chars"] * 1.25:
        problems.append(f"Juda uzun: {n} belgi (maksimum {p['max_chars']})")

    for pattern, why in BANNED_PATTERNS:
        if re.search(pattern, text, flags=re.M | re.I):
            problems.append(why)

    first = text.strip().splitlines()[0] if text.strip() else ""
    if len(first) > 120:
        problems.append("Birinchi qator juda uzun — qarmoq sifatida ishlamaydi")
    if re.match(r"^\s*(salom|assalom|hurmatli)", first, flags=re.I):
        problems.append("Quruq salomlashish bilan boshlangan — qarmoq yo'q")

    hashtags = p.get("hashtags") or []
    if hashtags and not any(h in text for h in hashtags):
        problems.append("Hashtag qo'shilmagan")

    return problems


def _content_prompt(cfg: dict, topic: dict, text: str) -> str:
    examples = style_examples()
    style_block = f"STIL ETALONI:\n{examples[:2500]}" if examples else "Stil namunasi berilmagan."
    p = cfg["post"]

    return f"""Siz muharrirsiz. Quyidagi post kanalga chiqishga tayyormi — tekshiring.
Talabchan bo'ling, lekin ADOLATLI: kamchilik postni haqiqatan yaroqsiz
qilsagina rad eting. Did masalasi yoki "men boshqacha yozardim" — rad etish
sababi emas.

RUXSAT ETILGAN, rad etish sababi BO'LMAGAN narsalar:
- Xitoycha, inglizcha yoki ruscha atamalar va nomlar: 1688, 义乌, Futian,
  MOQ, Alibaba, WeChat, packing list va shu kabilar. Bu auditoriya uchun
  tanish so'zlar — ularni olib tashlashni talab qilmang.
- Xitoy iyeroglifi bilan yozilgan sayt, bozor, tovar yoki hujjat nomlari.
  Bir necha o'nlab iyeroglif bo'lsa ham — bu normal holat, rad etmang.
- Kompaniya kontakt ma'lumotlari va o'z xizmatiga qisqa taklif.
- Emoji va belgilar bilan tuzilgan ro'yxatlar.

FAQAT BITTA TIL QOIDASI: postning o'zi o'zbek tilida bo'lishi shart.
Agar matnning katta qismi yoki butuni xitoycha (yoki boshqa tilda) bo'lsa —
rad eting. Ayrim nom va atamalar bunga kirmaydi.

{style_block}

TADQIQOT MATERIALI (postdagi faktlar faqat shundan kelib chiqishi kerak):
{topic.get('research', '')[:4000]}

TEKSHIRILAYOTGAN POST:
{text}

Quyidagilarni tekshiring:
1. FAKT — postdagi har bir dalil, raqam, nom tadqiqot materialida bormi?
   Materialda yo'q narsa yozilgan bo'lsa — bu jiddiy xato, rad eting.
1a. RASMIY RAQAMLAR — postda boj stavkasi, soliq foizi, bojxona limiti,
   qonun moddasi, muddat yoki narx ko'rsatilgan bo'lsa: u tadqiqot
   materialida AYNAN shundaymi? Aynan bo'lmasa — rad eting. Bunday
   raqamlar tez o'zgaradi va noto'g'ri ma'lumot o'quvchiga real zarar
   yetkazadi. Umumiy metodika (masalan, hajmli vaznni hisoblash formulasi)
   bunga kirmaydi — cheklov rasmiy stavka va limitlarga tegishli.
2. FOYDA — o'quvchi postni o'qib bugun aniq nima qila oladi? Javob noaniq bo'lsa — rad eting.
3. QARMOQ — birinchi qator to'xtatib qoladimi yoki bo'sh gapmi?
4. STIL — etalon namunalarga ohangi va tuzilishi mos keladimi?
5. TIL — o'zbek tilida tabiiy jumlalarmi, tarjima hidi kelmayaptimi?
6. HAJM — {p['min_chars']}–{p['max_chars']} belgi oralig'idami?
7. TAKROR — bir xil fikr bir necha marta aytilmaganmi?

score: 1–10, quyidagicha:
  9–10 — a'lo
  7–8  — chiqarish mumkin, jiddiy kamchilik yo'q
  5–6  — o'rtacha, tuzatish kerak
  1–4  — yaroqsiz (o'ylab topilgan fakt, ma'nosiz matn, mavzudan chetlashish)
approved: score 7 dan past bo'lsa false.
problems: HAQIQIY kamchiliklar (topilmasa bo'sh ro'yxat). Did masalasini yozmang.
fix_instructions: rad etilsa — 2-agentga aniq va qisqa tuzatish ko'rsatmasi."""


def run(cfg: dict, topic: dict, text: str, api_key: str,
        last_attempt: bool = False) -> dict:
    """Postni tekshiradi.

    last_attempt=True bo'lsa (oxirgi qayta yozish urinishi) yumshoqroq chegara
    qo'llanadi: post yaroqsiz bo'lmasa, past ball bilan bo'lsa ham o'tkaziladi
    va adminga belgi bilan boradi. Aks holda mukammal bo'lmagan post umuman
    chiqmay qolishi mumkin.
    """
    mech = _mechanical(cfg, text)

    verdict = generate_json(
        _content_prompt(cfg, topic, text),
        api_key,
        SCHEMA,
        model=cfg["llm"].get("qc_model", cfg["llm"]["model"]),
        temperature=0.2,
    )

    problems = mech + list(verdict.get("problems") or [])
    score = int(verdict.get("score", 0))
    min_score = int(cfg["llm"].get("qc_min_score", 7))

    approved = bool(verdict.get("approved")) and score >= min_score and not mech
    soft = False

    if not approved and last_attempt:
        last_chance = cfg["llm"].get("qc_last_chance")
        # Mexanik xatolar hech qachon kechirilmaydi — ular postni buzadi
        if last_chance is not None and not mech and score >= int(last_chance):
            approved, soft = True, True

    fix = verdict.get("fix_instructions", "").strip()
    if mech:
        fix = ("Mexanik xatolar: " + "; ".join(mech) + ". " + fix).strip()

    result = {
        "approved": approved,
        "soft_pass": soft,
        "score": score,
        "problems": problems,
        "fix_instructions": fix,
    }

    status = "O'TDI" if approved and not soft else ("SHARTLI O'TDI" if soft else "RAD ETILDI")
    LOG.info("Nazorat: %s (%d/%d ball), %d ta kamchilik",
             status, score, min_score, len(problems))
    for pr in problems:
        LOG.info("  · %s", pr)
    return result
