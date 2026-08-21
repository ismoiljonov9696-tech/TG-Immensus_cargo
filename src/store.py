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
    return _read(PENDING, [])


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
