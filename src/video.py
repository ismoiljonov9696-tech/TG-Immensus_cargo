"""Rasm + audio -> MP4.

Telegram bitta xabarda rasm va audioni birga qo'ya olmaydi, shuning uchun
ularni bitta videoga birlashtiramiz. Video zoom + diagonal siljish (pan)
bilan jonlanadi (statik rasm o'rniga) — lentada ko'proq e'tibor tortadi.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
from pathlib import Path

LOG = logging.getLogger("video")

ZOOM_MAX = 1.10
PULSE_MAX = 1.06

# Har biri pastki o'ng burchakka (logotip turgan joy) qarab yakunlanadi —
# zumlanish avjida oyna doim o'sha burchakni ko'rsatib turishi kerak,
# aks holda logotip kadrdan chiqib ketadi. Faqat BOSHLANISH nuqtasi va
# qay darajada siljishi farq qiladi — shu bilan lenta bir xil bo'lmaydi.
# Formula har doim JORIY ZOOMga bog'liq (vaqtga emas), shuning uchun
# zoom ortsa ham (push-in), kamaysa ham (push-out) bir xil ishlaydi.
PANS: list[tuple[float, float, float, float]] = [
    (0.20, 0.70, 0.20, 0.70),   # kuchli diagonal
    (0.20, 0.68, 0.50, 0.65),   # ko'proq gorizontal, sal vertikal
    (0.50, 0.65, 0.20, 0.68),   # ko'proq vertikal, sal gorizontal
    (0.40, 0.65, 0.40, 0.65),   # yumshoq diagonal
]


def _pick(seed: str, n: int, salt: str = "") -> int:
    return int(hashlib.sha1((seed + salt).encode("utf-8")).hexdigest(), 16) % n


def _xy_exprs(pan: tuple[float, float, float, float]) -> tuple[str, str]:
    fx0, fx1, fy0, fy1 = pan
    progress = f"((zoom-1)/{ZOOM_MAX - 1:.4f})"
    x = f"(iw-iw/zoom)*({fx0}+{fx1 - fx0}*{progress})"
    y = f"(ih-ih/zoom)*({fy0}+{fy1 - fy0}*{progress})"
    return x, y


def _zoom_expr(style: int, frames: int) -> str:
    if style == 0:                                  # ichkariga zumlanish
        return f"min(zoom+0.0006,{ZOOM_MAX})"
    if style == 1:                                   # tashqariga zumlanish
        return f"if(eq(on,0),{ZOOM_MAX},max(zoom-0.0006,1.0))"
    # nafas olish effekti — sekin kirib-chiqadi
    return f"1.0+{PULSE_MAX - 1:.3f}*abs(sin(PI*on/{frames}))"


class VideoError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def audio_duration(audio: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(audio)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def build(
    image: Path,
    audio: Path | None,
    out: Path,
    *,
    fade: float = 0.4,
    tail: float = 0.8,
    size: int = 1080,
    silent_seconds: float = 6.0,
    loop: bool = True,
) -> Path:
    """Rasmdan MP4 yasaydi.

    Ovoz bo'lsa — video davomiyligi audio + tail.
    Ovoz bo'lmasa — jimjit video, silent_seconds davomida. Lentada rasm
    o'rniga sekin harakatlanuvchi tasvir chiqadi va e'tiborni ko'proq tortadi.
    Premium yoki stiker kerak emas.
    """
    if not ffmpeg_available():
        raise VideoError("ffmpeg topilmadi. O'rnating: apt-get install -y ffmpeg")

    dur = (audio_duration(audio) + tail) if audio else float(silent_seconds)
    fps = 30
    frames = max(int(dur * fps), 1)

    # Ken Burns: har post uchun 3 uslubdan (ichkariga zum, tashqariga zum,
    # nafas olish) va 4 yo'nalishdan biri tanlanadi — lenta bir xil
    # bo'lib qolmaydi. x/y doim joriy zoomga bog'liq va pastki o'ng
    # burchakka (logotip joyi) qarab yakunlanadi, shuning uchun uslub yoki
    # yo'nalishdan qat'i nazar logotip kadrdan chiqib ketmaydi.
    seed = image.parent.name or image.stem
    style = _pick(seed, 3, salt="style")
    pan = PANS[_pick(seed, len(PANS), salt="pan")]
    x_expr, y_expr = _xy_exprs(pan)
    z_expr = _zoom_expr(style, frames)
    vf = (
        f"scale={size*2}:{size*2}:force_original_aspect_ratio=increase,"
        f"crop={size*2}:{size*2},"
        f"zoompan=z='{z_expr}':"
        f"x='{x_expr}':y='{y_expr}':"
        f"d={frames}:s={size}x{size}:fps={fps},"
        f"fade=t=in:st=0:d={fade},fade=t=out:st={max(dur-fade,0):.2f}:d={fade},"
        f"format=yuv420p"
    )

    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-i", str(image)]
    if audio:
        cmd += ["-i", str(audio)]
    cmd += ["-filter_complex", f"[0:v]{vf}[v]", "-map", "[v]"]
    if audio:
        cmd += ["-map", "1:a", "-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-an"]                                   # ovozsiz
    cmd += [
        "-c:v", "libx264", "-preset", "medium", "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-t", f"{dur:.2f}",
        "-movflags", "+faststart",
        str(out),
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not out.exists():
        raise VideoError(f"ffmpeg xatosi:\n{proc.stderr[:800]}")

    LOG.info("Video tayyor: %s (%.1fs, %s, %.1f MB)", out.name, dur,
             "ovozli" if audio else "ovozsiz", out.stat().st_size / 1e6)
    return out
