"""Doimiy holat: mavzular arxivi, navbatdagi postlar, Telegram offset.

Hammasi repo ichidagi kichik JSON fayllarda saqlanadi — GitHub Actions har
ishga tushganda ularni commit qilib qaytaradi. Media fayllar repoga tushmaydi:
ular Telegram'ga bir marta yuklanadi va file_id sifatida saqlanadi.
"""
from __future__ import annotations

import json
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA

LOG = logging.getLogger("store")

ARCHIVE = DATA / "archive.json"
PENDING = DATA / "pending.json"
OFFSET = DATA / "tg_offset.json"
META = DATA / "state.json"


def _read(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOG.warning("%s buzilgan, boshidan boshlanadi", path.name)
        return default


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------- #
#  Arxiv — takrorlanishning oldini oladi
# --------------------------------------------------------------------- #
def archive() -> list[dict]:
    return _read(ARCHIVE, [])


def archived_titles(rubric: str | None = None, limit: int = 200) -> list[str]:
    items = archive()
    if rubric:
        items = [i for i in items if i.get("rubric") == rubric]
    return [i["title"] for i in items[-limit:] if i.get("title")]


def topic_key(title: str) -> str:
    """Sarlavhani normallashtirib, barqaror kalit qaytaradi.

    Tinish belgilari, katta-kichik harf va ortiqcha probellar hisobga olinmaydi —
    "Test  mavzu!" va "test mavzu" bir xil mavzu deb qaraladi.
    """
    norm = "".join(ch.lower() if (ch.isalnum() or ch.isspace()) else " " for ch in title)
    norm = " ".join(norm.split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:12]


def is_used(title: str) -> bool:
    key = topic_key(title)
    return any(i.get("key") == key for i in archive())


def remember(title: str, rubric: str, post_id: str, sources: list[dict] | None = None) -> None:
    items = archive()
    items.append({
        "key": topic_key(title),
        "title": title,
        "rubric": rubric,
        "post_id": post_id,
        "sources": [s.get("url") for s in (sources or [])][:5],
        "at": now_iso(),
    })
    _write(ARCHIVE, items[-500:])


# --------------------------------------------------------------------- #
#  Navbat (tasdiq kutayotgan postlar)
# --------------------------------------------------------------------- #
def pending() -> list[dict]:
    """Navbat. Fayl buzilgan bo'lsa ham hech qachon yiqilmaydi.

    pending.json ro'yxat bo'lishi kerak: [ {...}, {...} ].
    Agar u yakka obyekt bo'lib qolgan bo'lsa (qo'lda tahrirlanganda shunday
    bo'ladi), uni ro'yxatga o'raymiz — aks holda kod uni harflar bo'yicha
    aylanib chiqib, butun tsikl yiqiladi va na tugmalar o'qiladi,
    na post chiqadi.
    """
    raw = _read(PENDING, [])
    if isinstance(raw, dict):
        LOG.warning("pending.json yakka obyekt ekan — ro'yxatga o'raldi")
        raw = [raw]
        _write(PENDING, raw)
    if not isinstance(raw, list):
        LOG.error("pending.json shakli noto'g'ri (%s) — tozalandi", type(raw).__name__)
        _write(PENDING, [])
        return []
    good = [i for i in raw if isinstance(i, dict) and i.get("id")]
    if len(good) != len(raw):
        LOG.warning("pending.json da %d ta yaroqsiz yozuv tashlandi", len(raw) - len(good))
        _write(PENDING, good)
    return good


def save_pending(items: list[dict]) -> None:
    _write(PENDING, items)


def add_pending(item: dict) -> None:
    items = pending()
    items.append(item)
    save_pending(items)


def find_pending(post_id: str) -> dict | None:
    return next((i for i in pending() if i.get("id") == post_id), None)


def update_pending(post_id: str, **changes) -> dict | None:
    items = pending()
    for item in items:
        if item.get("id") == post_id:
            item.update(changes)
            item["updated_at"] = now_iso()
            save_pending(items)
            return item
    return None


def prune_pending(keep_days: int = 7) -> None:
    """Chiqarilgan yoki rad etilgan eski yozuvlarni tozalaydi."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    kept = []
    for item in pending():
        if item.get("status") in ("waiting", "approved"):
            kept.append(item)
            continue
        try:
            created = datetime.fromisoformat(item.get("created_at", ""))
        except ValueError:
            kept.append(item)
            continue
        if created > cutoff:
            kept.append(item)
    save_pending(kept)


# --------------------------------------------------------------------- #
#  Telegram getUpdates offset
# --------------------------------------------------------------------- #
def offset() -> int | None:
    return _read(OFFSET, {}).get("offset")


def set_offset(value: int) -> None:
    _write(OFFSET, {"offset": value, "at": now_iso()})


def new_post_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


# --------------------------------------------------------------------------- #
#  Tizim holati — kuzatuv uchun
# --------------------------------------------------------------------------- #
def meta() -> dict:
    """Umumiy holat: oxirgi chiqish, oxirgi xato, pauza, ogohlantirish vaqti."""
    return _read(META, {})


def set_meta(**changes) -> dict:
    data = meta()
    data.update(changes)
    _write(META, data)
    return data


def record_success(post_id: str, title: str) -> None:
    set_meta(last_publish_at=now_iso(), last_publish_id=post_id,
             last_publish_title=title, last_error=None, alerted_at=None)


def record_error(stage: str, message: str) -> None:
    set_meta(last_error={"stage": stage, "message": message[:500], "at": now_iso()})


def is_paused() -> bool:
    return bool(meta().get("paused"))
