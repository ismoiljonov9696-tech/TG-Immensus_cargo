"""Orkestrator — 6 agentni boshqaradi.

Buyruqlar:
  python -m src.main check      — kalitlar va ulanishlarni tekshiradi
  python -m src.main generate   — postni tayyorlaydi va ko'rish uchun yuboradi
  python -m src.main tick       — tugmalarni o'qiydi, qayta ishlaydi, vaqti kelganini chiqaradi
  python -m src.main status     — navbatdagi postlarni ko'rsatadi

Sinov uchun:
  MOCK=1 python -m src.main generate    — hech qanday API chaqirilmaydi

Tasdiq modeli (config.yaml -> approval.mode):
  opt_out  post chiqishidan preview_minutes oldin sizga yuboriladi.
           HECH NARSA BOSMASANGIZ — belgilangan vaqtda o'zi chiqadi.
           "Qayta ishlash" bossangiz — to'xtaydi, qaytadan yoziladi va
           yangi variant asl vaqt o'tib ketgan bo'lsa ham chiqadi.
  opt_in   post faqat "Chiqarish" bosilganda chiqadi.
  off      ko'rsatilmaydi, to'g'ridan-to'g'ri chiqadi.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import store
from .config import WORK, ConfigError, load_config, load_secrets
from .agents import a1_topics, a2_writer, a3_image, a4_voice, a5_qc, a6_publish
from .telegram import Bot, TelegramError, approval_buttons

LOG = logging.getLogger("main")
MOCK = os.getenv("MOCK") == "1"

RESEARCH_KEEP = 4000        # navbatda saqlanadigan tadqiqot matni uzunligi


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s  %(name)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )


# --------------------------------------------------------------------------- #
#  Yordamchilar
# --------------------------------------------------------------------------- #
def tz_of(cfg: dict) -> ZoneInfo:
    return ZoneInfo(cfg["channel"].get("timezone", "Asia/Tashkent"))


def mode_of(cfg: dict) -> str:
    return (cfg.get("approval") or {}).get("mode", "opt_out")


def pick_rubric(cfg: dict) -> dict:
    rubrics = cfg.get("rubrics") or []
    if not rubrics:
        raise ConfigError("config.yaml da kamida bitta rubrika bo'lishi kerak")
    return rubrics[len(store.archive()) % len(rubrics)]


def next_publish_time(cfg: dict) -> datetime:
    tz = tz_of(cfg)
    now = datetime.now(tz)
    times = cfg["schedule"].get("publish_times") or ["09:00"]

    candidates: list[datetime] = []
    for day_offset in (0, 1):
        day = now.date() + timedelta(days=day_offset)
        for hhmm in times:
            hh, _, mm = hhmm.partition(":")
            candidates.append(datetime(day.year, day.month, day.day,
                                       int(hh), int(mm or 0), tzinfo=tz))
    # Ko'rish oynasi sig'ishi uchun juda yaqin vaqtni tanlamaymiz
    margin = timedelta(minutes=1)
    future = [c for c in candidates if c > now + margin]
    return min(future) if future else min(candidates)


def _parse(when: str | None, tz: ZoneInfo) -> datetime | None:
    if not when:
        return None
    try:
        dt = datetime.fromisoformat(when)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


# --------------------------------------------------------------------------- #
#  Postni yasash (2–5 agentlar + media)
# --------------------------------------------------------------------------- #
def build_post(cfg: dict, secrets, rubric: dict, topic: dict, post_id: str,
               *, feedback: str | None = None, force: bool = False
               ) -> tuple[str, dict, Path | None, str] | None:
    """Matn + media tayyorlaydi. (text, verdict, media_path, kind) yoki None."""
    max_tries = int(cfg["llm"].get("max_rewrites", 2)) + 1
    text, verdict = "", {}

    for attempt in range(1, max_tries + 1):
        last = attempt == max_tries
        LOG.info("── Yozish, urinish %d/%d", attempt, max_tries)
        text = ("Mock post matni.\n\n" + "Bu sinov matni. " * 40) if MOCK else \
            a2_writer.run(cfg, rubric, topic, secrets.gemini_key, feedback)
        verdict = {"approved": True, "score": 9, "soft_pass": False,
                   "problems": [], "fix_instructions": ""} if MOCK else \
            a5_qc.run(cfg, topic, text, secrets.gemini_key, last_attempt=last)

        if verdict["approved"]:
            if verdict.get("soft_pass"):
                LOG.warning("Shartli o'tdi (%d ball)", verdict.get("score", 0))
            break
        feedback = verdict["fix_instructions"]
        if last and not force:
            LOG.error("Sifat nazoratidan o'tmadi: %s", "; ".join(verdict["problems"]))
            LOG.error("Doim shu yerda to'xtasa: config.yaml da llm.qc_min_score ni "
                      "pasaytiring yoki style/examples.md ga o'z postlaringizni qo'shing.")
            return None
        if last:
            LOG.warning("Nazoratdan o'tmadi, lekin --force berilgan — davom etaman")

    if MOCK:
        return text, verdict, None, "text"

    workdir = WORK / post_id
    workdir.mkdir(parents=True, exist_ok=True)
    image_path = audio_path = media_path = None
    kind = "text"

    try:
        image_path, _ = a3_image.run(cfg, text, workdir / "image.png", secrets.gemini_key)
        kind, media_path = "photo", image_path
    except Exception as exc:                              # noqa: BLE001
        LOG.error("3-agent (rasm) ishlamadi: %s", exc)

    if cfg["audio"].get("enabled") and secrets.has_azure:
        try:
            audio_path, _ = a4_voice.run(cfg, text, workdir / "audio.mp3",
                                         secrets.gemini_key, secrets.azure_key,
                                         secrets.azure_region)
        except Exception as exc:                          # noqa: BLE001
            LOG.error("4-agent (ovoz) ishlamadi: %s", exc)

    if cfg["video"].get("enabled") and image_path and audio_path:
        try:
            from .video import build
            media_path = build(image_path, audio_path, workdir / "post.mp4",
                               fade=float(cfg["video"].get("fade_seconds", 0.4)),
                               tail=float(cfg["video"].get("tail_seconds", 0.8)))
            kind = "video"
        except Exception as exc:                          # noqa: BLE001
            LOG.error("Video yig'ilmadi, rasm bilan davom etaman: %s", exc)

    return text, verdict, media_path, kind


def send_preview(cfg: dict, secrets, bot: Bot, post: dict,
                 media: Path | None, kind: str, header: str) -> None:
    """Postni adminga ko'rish uchun yuboradi va file_id ni saqlaydi."""
    mode = mode_of(cfg)
    buttons = approval_buttons(post["id"], mode)
    info = a6_publish.send_draft(bot, secrets.admin_chat_id, post, media, kind, buttons)
    post.update(file_id=info["file_id"], kind=info["kind"],
                admin_message_id=info["message_id"])
    bot.send_message(secrets.admin_chat_id, header)


def preview_header(cfg: dict, post: dict, verdict: dict, when: datetime) -> str:
    mode = mode_of(cfg)
    flag = " ⚠️ past ball" if verdict.get("soft_pass") else ""
    rew = post.get("rewrites", 0)
    left = int(cfg["approval"].get("max_rewrites", 3)) - rew

    if mode == "opt_in":
        action = "✅ <b>Chiqarish</b> tugmasini bosing — aks holda chiqmaydi."
    else:
        mins = max(1, int((when - datetime.now(when.tzinfo)).total_seconds() // 60))
        action = (f"⏳ <b>{when:%H:%M}</b> da o'zi chiqadi (taxminan {mins} daqiqadan keyin).\n"
                  f"Hech narsa bosmasangiz — chiqaveradi.")

    note = ""
    if verdict.get("soft_pass") and verdict.get("problems"):
        note = "\nNazoratchi izohi: " + "; ".join(verdict["problems"][:3])
    if rew:
        note += f"\n🔄 {rew}-qayta ishlash. Yana {max(left, 0)} marta mumkin."

    return (f"☝️ <b>{post['title']}</b>\n"
            f"Rubrika: {post['rubric']}  ·  Sifat: {verdict.get('score')}/10{flag}\n"
            f"{action}\n"
            f"ID: <code>{post['id']}</code>{note}")


# --------------------------------------------------------------------------- #
#  check
# --------------------------------------------------------------------------- #
def cmd_check(cfg: dict) -> int:
    from .azure_tts import list_uz_voices
    from .gemini import generate_text
    from .video import ffmpeg_available

    secrets = load_secrets(strict=False)
    ok = True

    def report(label: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        print(f"  {'✅' if good else '❌'}  {label}{('  — ' + detail) if detail else ''}")
        if not good:
            ok = False

    print("\nTekshiruv\n" + "─" * 52)

    if secrets.telegram_token:
        try:
            bot = Bot(secrets.telegram_token)
            me = bot.me()
            report("Telegram bot", True, f"@{me.get('username')}")
            try:
                chat = bot._call("getChat", data={"chat_id": cfg["channel"]["id"]})
                report("Kanalga ulanish", True, chat.get("title", ""))
                admins = bot._call("getChatAdministrators", data={"chat_id": cfg["channel"]["id"]})
                is_admin = any(a.get("user", {}).get("id") == me.get("id") for a in admins)
                report("Bot kanalda admin", is_admin,
                       "" if is_admin else "botga 'Post Messages' huquqini bering")
            except TelegramError as exc:
                report("Kanalga ulanish", False, str(exc)[:90])
        except TelegramError as exc:
            report("Telegram bot", False, str(exc)[:90])
    else:
        report("Telegram bot", False, "TELEGRAM_BOT_TOKEN yo'q")

    need_admin = mode_of(cfg) != "off"
    report("Admin chat ID", bool(secrets.admin_chat_id) or not need_admin,
           "" if secrets.admin_chat_id else "TELEGRAM_ADMIN_CHAT_ID yo'q — ko'rsatish ishlamaydi")

    if secrets.gemini_key:
        try:
            generate_text("Javob: OK", secrets.gemini_key, model=cfg["llm"]["model"], temperature=0)
            report(f"Gemini matn ({cfg['llm']['model']})", True)
        except Exception as exc:                          # noqa: BLE001
            report(f"Gemini matn ({cfg['llm']['model']})", False, str(exc)[:110])
        try:
            from .gemini import generate_image
            generate_image("A simple blue circle on white background, no text",
                           secrets.gemini_key, model=cfg["image"]["model"])
            report(f"Gemini rasm ({cfg['image']['model']})", True)
        except Exception as exc:                          # noqa: BLE001
            report(f"Gemini rasm ({cfg['image']['model']})", False, str(exc)[:110])
    else:
        report("Gemini", False, "GEMINI_API_KEY yo'q")

    if cfg["audio"].get("enabled"):
        if secrets.has_azure:
            try:
                voices = list_uz_voices(secrets.azure_key, secrets.azure_region)
                want = cfg["audio"]["voice"]
                report("Azure Speech", True, f"{len(voices)} ta uz ovoz")
                report(f"Ovoz {want}", want in voices,
                       "" if want in voices else "mavjudlari: " + ", ".join(voices))
            except Exception as exc:                      # noqa: BLE001
                report("Azure Speech", False, str(exc)[:90])
        else:
            report("Azure Speech", False, "AZURE_SPEECH_KEY / AZURE_SPEECH_REGION yo'q")

    if cfg["video"].get("enabled"):
        report("ffmpeg", ffmpeg_available(), "" if ffmpeg_available() else "apt install ffmpeg")

    from .config import style_examples
    ex = style_examples()
    report("Stil namunalari", len(ex) > 200,
           f"{len(ex)} belgi" if ex else "style/examples.md bo'sh")

    print("─" * 52)
    print(f"  Rejim: {mode_of(cfg)}  ·  ko'rsatish {cfg['approval'].get('preview_minutes', 10)} "
          f"daqiqa oldin  ·  chiqish {', '.join(cfg['schedule'].get('publish_times', []))}")
    print("─" * 52)
    print("Hammasi tayyor.\n" if ok else "Yuqoridagi ❌ larni to'g'rilang.\n")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
#  generate
# --------------------------------------------------------------------------- #
def cmd_generate(cfg: dict, force: bool = False) -> int:
    secrets = load_secrets(strict=not MOCK)
    rubric = pick_rubric(cfg)
    post_id = store.new_post_id()
    LOG.info("═══ Post %s | rubrika: %s ═══", post_id, rubric["name"])

    topic = a1_topics.run(cfg, rubric, secrets.gemini_key) if not MOCK else {
        "title": "Mock mavzu", "angle": "", "why_now": "",
        "research": "(mock)", "sources": [],
    }

    built = build_post(cfg, secrets, rubric, topic, post_id, force=force)
    if built is None:
        return 2
    text, verdict, media, kind = built

    when = next_publish_time(cfg)
    post = {
        "id": post_id,
        "rubric": rubric["name"],
        "title": topic["title"],
        "text": text,
        "kind": kind,
        "file_id": None,
        "media_path": str(media) if media else None,
        "topic": {**topic, "research": (topic.get("research") or "")[:RESEARCH_KEEP]},
        "qc_score": verdict.get("score"),
        "soft_pass": verdict.get("soft_pass", False),
        "rewrites": 0,
        "publish_at": when.isoformat(),
        "created_at": store.now_iso(),
    }

    if MOCK:
        print("\n" + "═" * 60 + "\n" + text + "\n" + "═" * 60)
        print(f"\nChiqish vaqti: {when:%Y-%m-%d %H:%M %Z}  ·  rejim: {mode_of(cfg)}")
        return 0

    bot = Bot(secrets.telegram_token)
    mode = mode_of(cfg)

    if mode == "off":
        post["status"] = "ready"
        LOG.info("Ko'rsatish o'chirilgan — belgilangan vaqtda chiqadi")
    else:
        if not secrets.admin_chat_id:
            LOG.error("TELEGRAM_ADMIN_CHAT_ID yo'q — ko'rsatib bo'lmaydi")
            return 3
        post["status"] = "preview"
        send_preview(cfg, secrets, bot, post, media, kind,
                     preview_header(cfg, post, verdict, when))
        LOG.info("Ko'rish uchun yuborildi. Chiqish: %s", when.strftime("%H:%M"))

    store.add_pending(post)
    store.remember(topic["title"], rubric["name"], post_id, topic.get("sources"))
    store.prune_pending()
    return 0


# --------------------------------------------------------------------------- #
#  tick — qarorlar, qayta ishlash, chiqarish
# --------------------------------------------------------------------------- #
def collect_decisions(bot: Bot) -> int:
    updates = bot.get_updates(offset=store.offset())
    if not updates:
        return 0

    handled, last_id = 0, None
    for upd in updates:
        last_id = upd["update_id"]
        cq = upd.get("callback_query")
        if not cq:
            continue
        action, _, post_id = cq.get("data", "").partition(":")
        if action not in ("ok", "no", "redo") or not post_id:
            continue

        item = store.find_pending(post_id)
        if not item:
            bot.answer_callback(cq["id"], "Bu post topilmadi")
            continue
        if item.get("status") in ("published", "cancelled"):
            bot.answer_callback(cq["id"], "Bu post allaqachon yakunlangan")
            continue

        status = {"ok": "approved", "no": "cancelled", "redo": "rewrite_requested"}[action]
        label = {"ok": "✅ Chiqariladi", "no": "❌ Bekor qilindi",
                 "redo": "🔄 Qayta ishlanmoqda…"}[action]
        store.update_pending(post_id, status=status)
        bot.answer_callback(cq["id"], label)

        msg = cq.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id", ""))
        if msg.get("message_id") and chat_id:
            bot.edit_reply_markup(chat_id, msg["message_id"])
            bot.send_message(chat_id, f"{label} — <code>{post_id}</code>")
        handled += 1
        LOG.info("Qaror: %s → %s", post_id, status)

    if last_id is not None:
        store.set_offset(last_id + 1)
    return handled


def process_rewrites(cfg: dict, secrets, bot: Bot) -> int:
    """'Qayta ishlash' bosilgan postlarni qaytadan yasaydi.

    Yangi variant asl chiqish vaqtiga bog'lanmaydi — u hozirdan
    rewrite_review_minutes keyin chiqadi. Ya'ni asl vaqt o'tib ketgan
    bo'lsa ham post baribir kanalga chiqadi.
    """
    tz = tz_of(cfg)
    ap = cfg["approval"]
    limit = int(ap.get("max_rewrites", 3))
    done = 0

    for item in store.pending():
        if item.get("status") != "rewrite_requested":
            continue

        rewrites = int(item.get("rewrites", 0)) + 1
        rubric = next((r for r in cfg["rubrics"] if r["name"] == item.get("rubric")),
                      cfg["rubrics"][0])
        LOG.info("── Qayta ishlash %s (%d-marta)", item["id"], rewrites)

        # Ikkinchi martadan boshlab mavzuning o'zini almashtiramiz:
        # demak muammo matnda emas, mavzuda.
        topic = item.get("topic") or {}
        if rewrites >= 2:
            try:
                topic = a1_topics.run(cfg, rubric, secrets.gemini_key)
                store.remember(topic["title"], rubric["name"], item["id"], topic.get("sources"))
                LOG.info("Yangi mavzu olindi: %s", topic["title"])
            except Exception as exc:                      # noqa: BLE001
                LOG.error("Yangi mavzu topilmadi, eskisi bilan davom etaman: %s", exc)

        feedback = ("Admin bu variantni qaytarib yubordi. Boshqa qarmoq, boshqa "
                    "tuzilish va boshqa misollar bilan qaytadan yozing — oldingi "
                    "variantni takrorlamang.")
        built = build_post(cfg, secrets, rubric, topic, f"{item['id']}-r{rewrites}",
                           feedback=feedback, force=rewrites >= limit)
        if built is None:
            LOG.error("Qayta yozib bo'lmadi: %s", item["id"])
            store.update_pending(item["id"], status="error",
                                 error="qayta yozishda sifat nazoratidan o'tmadi")
            if secrets.admin_chat_id:
                bot.send_message(secrets.admin_chat_id,
                                 f"⚠️ <code>{item['id']}</code> qayta yozilmadi — "
                                 f"sifat nazoratidan o'tmadi. Post chiqmaydi.")
            continue

        text, verdict, media, kind = built
        when = datetime.now(tz) + timedelta(minutes=int(ap.get("rewrite_review_minutes", 10)))

        post = {**item, "text": text, "kind": kind, "file_id": None,
                "media_path": str(media) if media else None,
                "title": topic.get("title", item.get("title")),
                "topic": {**topic, "research": (topic.get("research") or "")[:RESEARCH_KEEP]},
                "qc_score": verdict.get("score"),
                "soft_pass": verdict.get("soft_pass", False),
                "rewrites": rewrites,
                "publish_at": when.isoformat(),
                "status": "preview" if mode_of(cfg) != "off" else "ready"}

        if mode_of(cfg) != "off" and secrets.admin_chat_id:
            header = preview_header(cfg, post, verdict, when)
            if rewrites >= limit:
                header += ("\n\n⚠️ Qayta ishlash chegarasiga yetdi — "
                           "bu variant chiqadi. To'xtatish uchun ❌ bosing.")
            send_preview(cfg, secrets, bot, post, media, kind, header)

        store.update_pending(item["id"], **{k: v for k, v in post.items() if k != "id"})
        done += 1

    return done


def publish_due(cfg: dict, secrets, bot: Bot) -> int:
    tz = tz_of(cfg)
    now = datetime.now(tz)
    mode = mode_of(cfg)
    ready_states = {"opt_out": {"preview", "ready", "approved"},
                    "opt_in": {"approved"},
                    "off": {"ready", "approved"}}[mode]

    published = 0
    for item in store.pending():
        if item.get("status") not in ready_states:
            continue
        when = _parse(item.get("publish_at"), tz)
        if when and when > now:
            continue

        # file_id bo'lmasa (ko'rsatish o'chirilgan bo'lsa) media faylni yuklaymiz
        if not item.get("file_id") and item.get("media_path"):
            p = Path(item["media_path"])
            if p.exists():
                item = {**item, "file_id": None}
                try:
                    res = a6_publish.send_draft(bot, cfg["channel"]["id"], item,
                                                p, item.get("kind", "photo"), None)
                    store.update_pending(item["id"], status="published",
                                         file_id=res["file_id"],
                                         published_at=store.now_iso())
                    published += 1
                    LOG.info("Kanalga chiqarildi (yuklab): %s", item["id"])
                    continue
                except TelegramError as exc:
                    LOG.error("Chiqarib bo'lmadi %s: %s", item["id"], exc)
                    store.update_pending(item["id"], status="error", error=str(exc)[:300])
                    continue

        try:
            a6_publish.publish(bot, cfg["channel"]["id"], item)
            store.update_pending(item["id"], status="published", published_at=store.now_iso())
            published += 1
            if secrets.admin_chat_id:
                late = " (kechikkan variant)" if int(item.get("rewrites", 0)) else ""
                bot.send_message(secrets.admin_chat_id,
                                 f"📤 Kanalga chiqdi{late}: <b>{item.get('title', item['id'])}</b>")
        except TelegramError as exc:
            LOG.error("Chiqarib bo'lmadi %s: %s", item["id"], exc)
            store.update_pending(item["id"], status="error", error=str(exc)[:300])

    return published


def cmd_tick(cfg: dict) -> int:
    secrets = load_secrets()
    bot = Bot(secrets.telegram_token)

    decisions = collect_decisions(bot)
    rewritten = process_rewrites(cfg, secrets, bot)
    published = publish_due(cfg, secrets, bot)

    if decisions or rewritten or published:
        LOG.info("Qaror: %d  ·  qayta ishlangan: %d  ·  chiqarilgan: %d",
                 decisions, rewritten, published)
    store.prune_pending()
    return 0


# --------------------------------------------------------------------------- #
def cmd_status(cfg: dict) -> int:
    items = store.pending()
    if not items:
        print("Navbat bo'sh.")
        return 0
    icons = {"preview": "👀", "ready": "⏳", "approved": "✅", "published": "📤",
             "cancelled": "❌", "rewrite_requested": "🔄", "error": "⚠️"}
    print(f"\n{'ID':<18} {'Holat':<20} {'Chiqish':<14} {'↻':<3} Sarlavha")
    print("─" * 82)
    for i in items[-25:]:
        when = (i.get("publish_at") or "")[:16].replace("T", " ")[-11:]
        st = i.get("status", "")
        print(f"{i['id']:<18} {icons.get(st,'?')} {st:<17} {when:<14} "
              f"{i.get('rewrites',0):<3} {i.get('title','')[:30]}")
    print(f"\nArxivda {len(store.archive())} ta mavzu.  Rejim: {mode_of(cfg)}\n")
    return 0


# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Telegram avtomatik post tizimi")
    parser.add_argument("command",
                        choices=["check", "generate", "tick", "publish", "status"])
    parser.add_argument("--force", action="store_true",
                        help="sifat nazoratidan o'tmasa ham davom etadi")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)
    if MOCK:
        LOG.warning("MOCK rejimi — tashqi API chaqirilmaydi")

    try:
        cfg = load_config()
        if args.command == "check":
            return cmd_check(cfg)
        if args.command == "generate":
            return cmd_generate(cfg, force=args.force)
        if args.command in ("tick", "publish"):      # publish — eski nom
            return cmd_tick(cfg)
        if args.command == "status":
            return cmd_status(cfg)
    except ConfigError as exc:
        LOG.error("%s", exc)
        return 1
    except Exception as exc:                          # noqa: BLE001
        LOG.exception("Kutilmagan xato: %s", exc)
        return 1
    return 0


# Eski nom bilan chaqirilsa ham ishlasin
cmd_publish = cmd_tick


if __name__ == "__main__":
    sys.exit(main())
