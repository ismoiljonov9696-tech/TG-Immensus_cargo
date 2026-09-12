"""Doimiy holat: mavzular arxivi, navbatdagi postlar, Telegram offset.

Hammasi repo ichidagi kichik JSON fayllarda saqlanadi — GitHub Actions har
ishga tushganda ularni commit qilib qaytaradi. Media fayllar repoga tushmaydi:
ular Telegram'ga bir marta yuklanadi va file_id sifatida saqlanadi.
"""
from __future__ import annotations

import json
import hashlib
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA, ROOT

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


# Hali chiqmagan — navbatda turgan post holatlari.
LIVE_STATES = {"preview", "ready", "approved", "rewrite_requested"}


def queued() -> list[dict]:
    """Hali kanalga chiqmagan, navbatda turgan postlar."""
    return [i for i in pending() if i.get("status") in LIVE_STATES]


def prune_pending(keep_days: int = 3) -> None:
    """Navbatni ixchamlaydi.

    Navbatda turgan postlar hech qachon o'chirilmaydi. Chiqib bo'lgan yoki
    xatoga uchragan yozuvlar keep_days kundan keyin o'chadi, undan oldin esa
    og'ir maydonlari (matn, tadqiqot) tashlanadi — aks holda pending.json
    yuz kilobaytga o'sib, har bir ishga tushishda sekinlashtiradi.
    """
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    kept = []
    for item in pending():
        if item.get("status") in LIVE_STATES:
            kept.append(item)
            continue
        try:
            created = datetime.fromisoformat(item.get("created_at", ""))
        except ValueError:
            kept.append(item)
            continue
        if created <= cutoff:
            continue                       # eski va tugagan — o'chiriladi
        light = {k: v for k, v in item.items() if k not in ("text", "topic")}
        kept.append(light)
    save_pending(kept)


# --------------------------------------------------------------------- #
#  Telegram getUpdates offset
# --------------------------------------------------------------------- #
def offset() -> int | None:
    return _read(OFFSET, {}).get("offset")


def set_offset(value: int) -> None:
    _write(OFFSET, {"offset": value, "at": now_iso()})


def new_post_id() -> str:
    """Takrorlanmaydigan ID. Bir yurishda bir necha post tayyorlanganda
    ikkitasi bir xil soniyaga tushib qolmasligi uchun tekshiriladi."""
    base = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    used = {i.get("id") for i in pending()} | {i.get("post_id") for i in archive()}
    if base not in used:
        return base
    for n in range(1, 100):
        candidate = f"{base}-{n}"
        if candidate not in used:
            return candidate
    return base


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


def record_success(post_id: str, title: str, cost: float | None = None) -> None:
    m = meta()
    total_cost = float(m.get("total_cost_usd", 0) or 0) + float(cost or 0)
    total_posts = int(m.get("total_posts", 0) or 0) + 1
    changes: dict = dict(
        last_publish_at=now_iso(), last_publish_id=post_id,
        last_publish_title=title, last_publish_cost=cost,
        total_cost_usd=round(total_cost, 4), total_posts=total_posts,
        last_error=None, alerted_at=None,
    )
    # /balans bilan qo'lda kiritilgan qoldiq bo'lsa, har post narxi shundan
    # avtomatik ayiriladi — foydalanuvchi AI Studio'ga kirmasdan ham
    # taxminan qancha qolganini biladi.
    if m.get("balance_usd") is not None:
        changes["balance_usd"] = round(float(m["balance_usd"]) - float(cost or 0), 4)
    set_meta(**changes)


def record_error(stage: str, message: str) -> None:
    set_meta(last_error={"stage": stage, "message": message[:500], "at": now_iso()})


def is_paused() -> bool:
    return bool(meta().get("paused"))


# --------------------------------------------------------------------------- #
#  Git bilan sinxronlash — GitHub Actions rejimida ikkita ish (masalan
#  "tayyorlash" va "chiqarish", ular alohida concurrency guruhlarida bo'lgani
#  uchun bir vaqtda ishlashi mumkin) bir xil postni ikki marta kanalga
#  yubormasligi uchun.
# --------------------------------------------------------------------------- #
def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def _ensure_git_identity() -> None:
    if not _git("config", "user.email").stdout.strip():
        _git("config", "user.email", "autopost@users.noreply.github.com")
    if not _git("config", "user.name").stdout.strip():
        _git("config", "user.name", "autopost-bot")


def sync_to_remote(message: str, retries: int = 2) -> bool:
    """data/ ichidagi o'zgarishlarni commit qilib remote'ga yuboradi.

    Bu funksiya jim yutilmaydi: push oxir-oqibat o'tmasa False qaytaradi.
    Chaqiruvchi False ko'rsa, holat remote bilan aniq bir xilligiga
    ISHONMASLIGI kerak — ayniqsa kanalga chiqarishdan OLDIN "band qilish"
    uchun ishlatilganda, False degani boshqa bir jarayon ham shu payt
    ishlayotgan bo'lishi mumkin, demak post YUBORILMASLIGI kerak.

    Agar .git papkasi bo'lmasa (masalan lokal /VPS rejimida, src.scheduler
    orqali ishlatilganda git umuman kerak emas) — True qaytariladi, hech
    narsa qilinmaydi.
    """
    if not (ROOT / ".git").exists():
        return True

    _ensure_git_identity()

    add = _git("add", "data/")
    if add.returncode != 0:
        LOG.error("git add muvaffaqiyatsiz: %s", add.stderr.strip())
        return False

    if _git("diff", "--cached", "--quiet").returncode == 0:
        return True     # commit qiladigan o'zgarish yo'q

    commit = _git("commit", "-q", "-m", message)
    if commit.returncode != 0:
        LOG.error("git commit muvaffaqiyatsiz: %s", commit.stderr.strip())
        return False

    for attempt in range(retries + 1):
        if _git("push", "-q").returncode == 0:
            return True
        pull = _git("pull", "--rebase", "--autostash", "-q")
        if pull.returncode != 0:
            LOG.error("git pull --rebase muvaffaqiyatsiz (urinish %d/%d): %s",
                      attempt + 1, retries + 1, pull.stderr.strip())
            # Rebase o'rtada qotib qolmasin — aks holda shu ishning keyingi
            # git buyruqlari (hattoki boshqa postlar uchun ham) ishlamay qoladi.
            _git("rebase", "--abort")
            return False

    LOG.error("git push %d urinishdan keyin ham o'tmadi — boshqa jarayon "
              "bilan to'qnashuv bo'lishi mumkin", retries + 1)
    return False
