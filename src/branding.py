"""Brend elementlari — logotipni rasmga qo'yish.

Logotipni AI ga chizdirib bo'lmaydi: har safar boshqacha va buzuq chiqadi.
Shuning uchun rasm generatsiya qilingandan keyin haqiqiy logo fayli
ustiga qo'yiladi — har safar bir xil, aniq va o'zgarmas.
"""
from __future__ import annotations

import logging
from pathlib import Path

LOG = logging.getLogger("branding")

POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left")


def find_logo(cfg: dict, root: Path) -> Path | None:
    """Logo faylini topadi.

    Sozlamadagi yo'l bo'yicha topilmasa, odatiy joylardan qidiradi —
    shunda faylni reponing ildiziga tashlasangiz ham ishlaydi va
    papka yaratish bilan ovora bo'lmaysiz.
    """
    logo_cfg = (cfg.get("image") or {}).get("logo") or {}
    rel = logo_cfg.get("path")

    candidates: list[Path] = []
    if rel:
        candidates.append(Path(rel) if Path(rel).is_absolute() else root / rel)
    for folder in (root / "assets", root):
        for ext in ("png", "PNG", "jpg", "jpeg", "webp"):
            candidates.append(folder / f"logo.{ext}")

    for path in candidates:
        if path.exists() and path.is_file():
            return path

    # logo* bilan boshlanadigan har qanday rasm
    for folder in (root / "assets", root):
        if folder.is_dir():
            for path in sorted(folder.glob("logo*")):
                if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                    return path
    return None


def apply_logo(image_path: Path, cfg: dict, root: Path) -> Path:
    """Rasmga logo qo'yadi. Logo topilmasa rasm o'zgarishsiz qoladi."""
    logo_cfg = (cfg.get("image") or {}).get("logo") or {}
    if logo_cfg.get("enabled") is False:
        return image_path

    logo_path = find_logo(cfg, root)
    if logo_path is None:
        LOG.warning("Logo fayli topilmadi (assets/logo.png yoki logo.png) — "
                    "rasm logosiz qoldi")
        return image_path
    LOG.info("Logo fayli: %s", logo_path.relative_to(root) if root in logo_path.parents
             else logo_path)

    try:
        from PIL import Image, ImageDraw, ImageFilter
    except ImportError:
        LOG.warning("Pillow o'rnatilmagan — logo qo'yilmadi")
        return image_path

    try:
        base = Image.open(image_path).convert("RGBA")
        logo = Image.open(logo_path).convert("RGBA")

        width_pct = float(logo_cfg.get("width_percent", 18)) / 100
        margin_pct = float(logo_cfg.get("margin_percent", 4)) / 100
        opacity = float(logo_cfg.get("opacity", 0.95))
        position = logo_cfg.get("position", "bottom-right")
        if position not in POSITIONS:
            position = "bottom-right"

        target_w = max(int(base.width * width_pct), 24)
        target_h = max(int(logo.height * target_w / logo.width), 12)
        logo = logo.resize((target_w, target_h), Image.LANCZOS)

        if opacity < 1:
            alpha = logo.getchannel("A").point(lambda a: int(a * opacity))
            logo.putalpha(alpha)

        margin = int(base.width * margin_pct)
        x = margin if "left" in position else base.width - target_w - margin
        y = margin if "top" in position else base.height - target_h - margin

        layer = Image.new("RGBA", base.size, (0, 0, 0, 0))

        # Logo ostiga yumshoq plashka — rang-barang fonda ham o'qiladigan bo'lsin
        if logo_cfg.get("backdrop", True):
            pad = max(int(target_w * 0.12), 8)
            box = (x - pad, y - pad, x + target_w + pad, y + target_h + pad)
            shade = Image.new("RGBA", base.size, (0, 0, 0, 0))
            ImageDraw.Draw(shade).rounded_rectangle(
                box, radius=pad, fill=(255, 255, 255, 205)
            )
            shade = shade.filter(ImageFilter.GaussianBlur(1.5))
            layer = Image.alpha_composite(layer, shade)

        layer.paste(logo, (x, y), logo)
        out = Image.alpha_composite(base, layer).convert("RGB")
        out.save(image_path, "PNG")
        LOG.info("Logo qo'yildi: %s (%dpx, %s)", logo_path.name, target_w, position)
    except Exception as exc:                              # noqa: BLE001
        LOG.error("Logo qo'yilmadi: %s", exc)

    return image_path
