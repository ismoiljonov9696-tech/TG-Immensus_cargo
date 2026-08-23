"""Telegram Bot API — yuborish, tasdiq tugmalari, qarorlarni o'qish."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

LOG = logging.getLogger("telegram")
TIMEOUT = 180
CAPTION_LIMIT = 1024
MESSAGE_LIMIT = 4096


class TelegramError(RuntimeError):
    pass


class Bot:
    def __init__(self, token: str):
        if not token:
            raise TelegramError("TELEGRAM_BOT_TOKEN bo'sh")
        self.base = f"https://api.telegram.org/bot{token}"

    # ------------------------------------------------------------------ #
    def _call(self, method: str, *, data: dict | None = None,
              files: dict | None = None, retries: int = 3) -> dict:
        url = f"{self.base}/{method}"
        for attempt in range(retries):
            try:
                resp = requests.post(url, data=data, files=files, timeout=TIMEOUT)
            except requests.RequestException as exc:
                if attempt == retries - 1:
                    raise TelegramError(f"{method}: tarmoq xatosi {exc}") from exc
                time.sleep(2 ** attempt)
                continue

            payload = resp.json() if resp.content else {}
            if payload.get("ok"):
                return payload["result"]

            desc = payload.get("description", resp.text[:300])
            # Flood control
            if resp.status_code == 429:
                wait = int((payload.get("parameters") or {}).get("retry_after", 5))
                LOG.warning("Telegram flood limit, %ss kutaman", wait)
                time.sleep(wait + 1)
                continue
            if resp.status_code >= 500 and attempt < retries - 1:
                time.sleep(2 ** attempt * 3)
                continue
            raise TelegramError(f"{method} → {desc}")

        raise TelegramError(f"{method}: javob yo'q")

    # ------------------------------------------------------------------ #
    def me(self) -> dict:
        return self._call("getMe")

    def send_message(self, chat_id: str, text: str, *,
                     buttons: list[list[dict]] | None = None,
                     preview: bool = False) -> dict:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:MESSAGE_LIMIT],
            "parse_mode": "HTML",
            "link_preview_options": json.dumps({"is_disabled": not preview}),
        }
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        return self._call("sendMessage", data=data)

    def send_photo(self, chat_id: str, photo: Path | str, caption: str = "",
                   buttons: list[list[dict]] | None = None) -> dict:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption[:CAPTION_LIMIT],
            "parse_mode": "HTML",
        }
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        if isinstance(photo, Path):
            with photo.open("rb") as fh:
                return self._call("sendPhoto", data=data, files={"photo": fh})
        data["photo"] = photo                      # file_id
        return self._call("sendPhoto", data=data)

    def send_video(self, chat_id: str, video: Path | str, caption: str = "",
                   buttons: list[list[dict]] | None = None,
                   thumb: Path | None = None) -> dict:
        data: dict[str, Any] = {
            "chat_id": chat_id,
            "caption": caption[:CAPTION_LIMIT],
            "parse_mode": "HTML",
            "supports_streaming": "true",
        }
        if buttons:
            data["reply_markup"] = json.dumps({"inline_keyboard": buttons})
        if isinstance(video, Path):
            files = {"video": video.open("rb")}
            if thumb and thumb.exists():
                files["thumbnail"] = thumb.open("rb")
            try:
                return self._call("sendVideo", data=data, files=files)
            finally:
                for fh in files.values():
                    fh.close()
        data["video"] = video                      # file_id
        return self._call("sendVideo", data=data)

    def send_audio(self, chat_id: str, audio: Path | str, caption: str = "",
                   title: str = "") -> dict:
        data: dict[str, Any] = {"chat_id": chat_id, "caption": caption[:CAPTION_LIMIT],
                                "parse_mode": "HTML", "title": title}
        if isinstance(audio, Path):
            with audio.open("rb") as fh:
                return self._call("sendAudio", data=data, files={"audio": fh})
        data["audio"] = audio
        return self._call("sendAudio", data=data)

    # ------------------------------------------------------------------ #
    def answer_callback(self, callback_id: str, text: str = "") -> None:
        try:
            self._call("answerCallbackQuery", data={"callback_query_id": callback_id, "text": text})
        except TelegramError as exc:
            LOG.debug("answerCallbackQuery: %s", exc)

    def edit_reply_markup(self, chat_id: str, message_id: int) -> None:
        """Tugmalarni olib tashlaydi (qaror qabul qilingandan keyin)."""
        try:
            self._call("editMessageReplyMarkup",
                       data={"chat_id": chat_id, "message_id": message_id,
                             "reply_markup": json.dumps({"inline_keyboard": []})})
        except TelegramError as exc:
            LOG.debug("editMessageReplyMarkup: %s", exc)

    def get_updates(self, offset: int | None = None, timeout: int = 0) -> list[dict]:
        data: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": json.dumps(["callback_query", "message"]),
        }
        if offset is not None:
            data["offset"] = offset
        return self._call("getUpdates", data=data)


# ---------------------------------------------------------------------- #
def approval_buttons(post_id: str, mode: str = "opt_out") -> list[list[dict]]:
    """Ko'rish oynasidagi tugmalar.

    opt_out — post o'zi chiqadi, tugmalar faqat to'xtatish uchun.
    opt_in  — post faqat "Chiqarish" bosilganda chiqadi.
    """
    if mode == "opt_in":
        return [[
            {"text": "✅ Chiqarish", "callback_data": f"ok:{post_id}"},
            {"text": "🔄 Qayta ishlash", "callback_data": f"redo:{post_id}"},
            {"text": "❌ Bekor qilish", "callback_data": f"no:{post_id}"},
        ]]
    # opt_out: "Hoziroq chiqarish" — kutmasdan darhol chiqarish uchun.
    # Hech narsa bosilmasa post baribir belgilangan vaqtda o'zi chiqadi.
    return [
        [{"text": "🚀 Hoziroq chiqarish", "callback_data": f"ok:{post_id}"}],
        [{"text": "🔄 Qayta ishlash", "callback_data": f"redo:{post_id}"},
         {"text": "❌ Bekor qilish", "callback_data": f"no:{post_id}"}],
    ]


def extract_file_id(result: dict) -> str | None:
    """Yuborilgan media javobidan file_id ni oladi — qayta yuklamaslik uchun."""
    if "video" in result:
        return result["video"].get("file_id")
    if "photo" in result and result["photo"]:
        return max(result["photo"], key=lambda p: p.get("file_size", 0)).get("file_id")
    if "audio" in result:
        return result["audio"].get("file_id")
    return None
