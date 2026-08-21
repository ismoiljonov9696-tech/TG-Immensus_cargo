"""Azure Speech (Text-to-Speech) — o'zbek tilida ovoz.

Azure'da rasmiy uz-UZ ovozlari bor: uz-UZ-SardorNeural, uz-UZ-MadinaNeural.
"""
from __future__ import annotations

import html
import logging
import re
import time

import requests

LOG = logging.getLogger("azure_tts")
TIMEOUT = 120


class AzureTTSError(RuntimeError):
    pass


def _clean_for_speech(text: str) -> str:
    """Post matnini ovozga tayyorlash: emoji, hashtag, havola va telefonlarni olib tashlash."""
    t = text
    t = re.sub(r"https?://\S+|\bt\.me/\S+", "", t)            # havolalar
    t = re.sub(r"@[A-Za-z0-9_]{3,}", "", t)                   # username lar
    t = re.sub(r"#\w+", "", t)                                # hashtaglar
    t = re.sub(r"\+?\d[\d\s()\-]{7,}\d", "", t)               # telefon raqamlar
    # keycap ketma-ketligi: "1️⃣" -> "1." (avval, chunki keyin qismlari qoladi)
    t = re.sub(r"([0-9#*])️?⃣", r"\1.", t)
    t = re.sub(r"[▪•·─━—›»▶️]+", " ", t)                      # ajratgichlar
    # emoji, piktogramma va birlashuvchi belgilar
    t = re.sub(
        "["
        "\U0001F000-\U0001FAFF"
        "\U00002190-\U000027BF"
        "\U00002B00-\U00002BFF"
        "\U00002000-\U0000206F"
        "\U000020D0-\U000020FF"
        "\U0000FE00-\U0000FE0F"
        "\U0001F1E6-\U0001F1FF"
        "\U00002700-\U000027BF"
        "]+",
        "",
        t,
    )
    t = re.sub(r"[ \t]{2,}", " ", t)
    t = re.sub(r"[ \t]+([,.!?:;])", r"\1", t)
    t = re.sub(r"\n[ \t]+", "\n", t)
    # havola olib tashlangach osilib qolgan bog'lovchi/tinish belgilari
    t = re.sub(r"[ \t]*(?:va|hamda|yoki)?[ \t]*[:,;]?[ \t]*$", "", t, flags=re.M)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _ssml(text: str, voice: str, rate: str, pitch: str) -> str:
    lang = voice.split("-")[0] + "-" + voice.split("-")[1]
    body = html.escape(text)
    # Xatboshilar orasiga qisqa pauza
    body = body.replace("\n\n", '<break time="600ms"/>').replace("\n", '<break time="300ms"/>')
    return (
        f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{lang}">'
        f'<voice name="{voice}">'
        f'<prosody rate="{rate}" pitch="{pitch}">{body}</prosody>'
        f"</voice></speak>"
    )


def synthesize(
    text: str,
    key: str,
    region: str,
    *,
    voice: str = "uz-UZ-SardorNeural",
    rate: str = "+0%",
    pitch: str = "+0%",
    retries: int = 3,
) -> bytes:
    """Matndan MP3 audio qaytaradi."""
    clean = _clean_for_speech(text)
    if not clean:
        raise AzureTTSError("Ovozga aylantiriladigan matn bo'sh")

    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/ssml+xml",
        "X-Microsoft-OutputFormat": "audio-24khz-96kbitrate-mono-mp3",
        "User-Agent": "tg-autopost",
    }
    body = _ssml(clean, voice, rate, pitch).encode("utf-8")

    for attempt in range(retries):
        try:
            resp = requests.post(url, headers=headers, data=body, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if attempt == retries - 1:
                raise AzureTTSError(f"Azure'ga ulanib bo'lmadi: {exc}") from exc
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 200 and resp.content:
            return resp.content
        if resp.status_code in (429, 500, 502, 503) and attempt < retries - 1:
            time.sleep(2 ** attempt * 5)
            continue
        raise AzureTTSError(f"Azure TTS → HTTP {resp.status_code}: {resp.text[:400]}")

    raise AzureTTSError("Azure TTS javob bermadi")


def list_uz_voices(key: str, region: str) -> list[str]:
    """Mavjud o'zbek ovozlarini tekshirish uchun (check buyrug'i uchun)."""
    url = f"https://{region}.tts.speech.microsoft.com/cognitiveservices/voices/list"
    resp = requests.get(url, headers={"Ocp-Apim-Subscription-Key": key}, timeout=60)
    resp.raise_for_status()
    return sorted(v["ShortName"] for v in resp.json() if v.get("Locale", "").startswith("uz"))
