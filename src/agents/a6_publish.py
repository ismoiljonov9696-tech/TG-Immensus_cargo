"""6-AGENT — CHIQARUVCHI.

Tayyor postni kanalga chiqaradi. Media Telegram'ga bir marta yuklanadi
(adminga tasdiqqa yuborilganda) va file_id sifatida saqlanadi — kanalga
chiqarishda qayta yuklanmaydi.
"""
from __future__ import annotations

import logging
from pathlib import Path

from ..telegram import CAPTION_LIMIT, Bot, extract_file_id

LOG = logging.getLogger("agent6")


def send_draft(bot: Bot, admin_chat: str, post: dict,
               media: Path | None, kind: str,
               buttons: list[list[dict]] | None) -> dict:
    """Adminga tasdiq uchun yuboradi va media file_id ni qaytaradi."""
    text = post["text"]
    caption = text if len(text) <= CAPTION_LIMIT else ""

    if media and kind == "video":
        res = bot.send_video(admin_chat, media, caption=caption, buttons=buttons if caption else None)
    elif media and kind == "photo":
        res = bot.send_photo(admin_chat, media, caption=caption, buttons=buttons if caption else None)
    else:
        res = bot.send_message(admin_chat, text, buttons=buttons)
        return {"message_id": res["message_id"], "file_id": None, "kind": "text",
                "text_separate": False}

    file_id = extract_file_id(res)
    message_id = res["message_id"]
    text_separate = not caption

    if text_separate:
        # Matn caption'ga sig'madi — alohida xabar sifatida, tugmalar shunda
        msg = bot.send_message(admin_chat, text, buttons=buttons)
        message_id = msg["message_id"]

    return {"message_id": message_id, "file_id": file_id, "kind": kind,
            "text_separate": text_separate}


def publish(bot: Bot, channel_id: str, post: dict) -> dict:
    """Kanalga chiqaradi. Saqlangan file_id ishlatiladi."""
    text = post["text"]
    file_id = post.get("file_id")
    kind = post.get("kind", "text")
    caption = text if len(text) <= CAPTION_LIMIT else ""

    if file_id and kind == "video":
        res = bot.send_video(channel_id, file_id, caption=caption)
    elif file_id and kind == "photo":
        res = bot.send_photo(channel_id, file_id, caption=caption)
    else:
        res = bot.send_message(channel_id, text)
        LOG.info("Kanalga chiqarildi (matn): %s", post["id"])
        return res

    if not caption:
        bot.send_message(channel_id, text)

    LOG.info("Kanalga chiqarildi (%s): %s", kind, post["id"])
    return res
