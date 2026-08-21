"""Ichki jadval — GitHub Actions o'rniga.

Bu jarayon to'xtamasdan ishlaydi va o'zi vaqtni kuzatadi:
  · belgilangan soatda postni tayyorlaydi (1–5 agentlar)
  · har bir necha daqiqada tasdiq tugmalarini o'qiydi va vaqti kelganini chiqaradi

Ishga tushirish:
    python -m src.scheduler

Serverda doimiy ishlashi uchun systemd yoki Docker ishlatiladi — README ga qarang.
Cron ham, GitHub ham kerak emas.
"""
from __future__ import annotations

import logging
import signal
import sys
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import ConfigError, load_config
from .main import cmd_generate, cmd_tick, setup_logging

LOG = logging.getLogger("scheduler")

# Tugmalar va chiqish vaqti har daqiqada tekshiriladi.
# Ko'rish oynasi 10 daqiqa bo'lgani uchun bundan siyrak bo'lmasligi kerak.
TICK_EVERY_SECONDS = 60
_running = True


def _stop(signum, _frame) -> None:
    global _running
    LOG.info("To'xtatish signali (%s) — joriy ish tugagach chiqaman", signum)
    _running = False


def generate_times(cfg: dict) -> list[str]:
    """Post tayyorlanadigan soatlar.

    Standart hisob: chiqish vaqtidan
        preview_minutes + generate_buffer_minutes
    daqiqa oldin. Ya'ni 09:00 chiqadigan post 08:45 da tayyorlana boshlaydi,
    rasm va ovoz bilan ~08:47 da sizga yetib boradi va ko'rish uchun
    10 daqiqadan ko'proq vaqt qoladi.

    schedule.generate_times berilgan bo'lsa — o'sha ishlatiladi.
    """
    sch = cfg.get("schedule", {})
    if sch.get("generate_times"):
        return list(sch["generate_times"])

    ap = cfg.get("approval", {})
    lead = int(ap.get("preview_minutes", 10)) + int(ap.get("generate_buffer_minutes", 5))

    out: list[str] = []
    for hhmm in sch.get("publish_times") or ["09:00"]:
        hh, _, mm = hhmm.partition(":")
        t = (datetime(2000, 1, 2, int(hh), int(mm or 0)) - timedelta(minutes=lead)).time()
        out.append(f"{t.hour:02d}:{t.minute:02d}")
    return out


def _due(now: datetime, marks: list[str], last: dict[str, str]) -> str | None:
    """Shu daqiqada bajarilishi kerak bo'lgan belgini qaytaradi (bir marta)."""
    key = now.strftime("%Y-%m-%d")
    for mark in marks:
        hh, _, mm = mark.partition(":")
        if now.hour == int(hh) and now.minute == int(mm or 0) and last.get(mark) != key:
            return mark
    return None


def run() -> int:
    setup_logging()
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    try:
        cfg = load_config()
    except ConfigError as exc:
        LOG.error("%s", exc)
        return 1

    tz = ZoneInfo(cfg["channel"].get("timezone", "Asia/Tashkent"))
    ap = cfg.get("approval", {})
    gen_marks = generate_times(cfg)
    last_gen: dict[str, str] = {}
    next_tick = 0.0

    LOG.info("Jadval ishga tushdi")
    LOG.info("  Vaqt zonasi  : %s", tz)
    LOG.info("  Tayyorlash   : %s", ", ".join(gen_marks))
    LOG.info("  Chiqish      : %s", ", ".join(cfg["schedule"].get("publish_times", [])))
    LOG.info("  Rejim        : %s (ko'rsatish %s daqiqa oldin)",
             ap.get("mode", "opt_out"), ap.get("preview_minutes", 10))
    LOG.info("  Tekshiruv    : har %d soniyada", TICK_EVERY_SECONDS)

    while _running:
        now = datetime.now(tz)

        mark = _due(now, gen_marks, last_gen)
        if mark:
            last_gen[mark] = now.strftime("%Y-%m-%d")
            LOG.info("── %s: post tayyorlash boshlandi", mark)
            try:
                cmd_generate(cfg)
            except Exception as exc:                      # noqa: BLE001
                LOG.exception("Tayyorlashda xato: %s", exc)

        if time.monotonic() >= next_tick:
            next_tick = time.monotonic() + TICK_EVERY_SECONDS
            try:
                cmd_tick(cfg)
            except Exception as exc:                      # noqa: BLE001
                LOG.exception("Tekshiruvda xato: %s", exc)

        # Daqiqa boshiga tenglashib uxlaymiz — vaqt belgilarini o'tkazib yubormaslik uchun
        time.sleep(max(1, 60 - datetime.now(tz).second))

    LOG.info("To'xtadi")
    return 0


if __name__ == "__main__":
    sys.exit(run())
