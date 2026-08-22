"""Sozlamalar va muhit o'zgaruvchilarini yuklash."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STYLE = ROOT / "style"
WORK = ROOT / ".work"           # vaqtinchalik media (git'ga tushmaydi)


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Secrets:
    gemini_key: str
    telegram_token: str
    admin_chat_id: str          # birinchi admin — media shunga yuklanadi
    azure_key: str
    azure_region: str
    admin_chat_ids: tuple[str, ...] = ()

    @property
    def has_azure(self) -> bool:
        return bool(self.azure_key and self.azure_region)

    @property
    def admins(self) -> tuple[str, ...]:
        return self.admin_chat_ids or ((self.admin_chat_id,) if self.admin_chat_id else ())


def parse_chat_ids(raw: str) -> tuple[str, ...]:
    """Bir nechta admin ID sini ajratadi.

    TELEGRAM_ADMIN_CHAT_ID ga bittadan ko'p yozish mumkin — vergul,
    nuqta-vergul yoki probel bilan ajratib:
        123456789,987654321
    """
    if not raw:
        return ()
    parts = raw.replace(";", ",").replace(" ", ",").split(",")
    seen, out = set(), []
    for p in parts:
        p = p.strip()
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return tuple(out)


def load_config(path: Path | None = None) -> dict:
    path = path or ROOT / "config.yaml"
    if not path.exists():
        raise ConfigError(f"config.yaml topilmadi: {path}")
    with path.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    channel = (cfg.get("channel") or {}).get("id", "")
    if not channel or channel == "@CHANGE_ME":
        raise ConfigError("config.yaml ichida channel.id ni to'ldiring (@kanal_nomi yoki -100...)")
    return cfg


def load_secrets(strict: bool = True) -> Secrets:
    """Kalitlarni muhitdan oladi. Lokalda .env fayl ham o'qiladi."""
    _load_dotenv()
    ids = parse_chat_ids(os.getenv("TELEGRAM_ADMIN_CHAT_ID", ""))
    s = Secrets(
        gemini_key=os.getenv("GEMINI_API_KEY", "").strip(),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
        admin_chat_id=ids[0] if ids else "",
        azure_key=os.getenv("AZURE_SPEECH_KEY", "").strip(),
        azure_region=os.getenv("AZURE_SPEECH_REGION", "").strip(),
        admin_chat_ids=ids,
    )
    if strict:
        missing = [
            name
            for name, val in (
                ("GEMINI_API_KEY", s.gemini_key),
                ("TELEGRAM_BOT_TOKEN", s.telegram_token),
            )
            if not val
        ]
        if missing:
            raise ConfigError("Quyidagi kalitlar yo'q: " + ", ".join(missing))
    return s


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def style_examples() -> str:
    """Foydalanuvchi yozgan namuna postlar — 2-agent stilni shulardan o'rganadi."""
    path = STYLE / "examples.md"
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    # Yo'riqnoma sarlavhalarini olib tashlaymiz — faqat namunalar qolsin
    if "<!-- NAMUNALAR -->" in text:
        text = text.split("<!-- NAMUNALAR -->", 1)[1].strip()
    return text
