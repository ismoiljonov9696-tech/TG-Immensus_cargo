"""Rasm + audio -> MP4.

Telegram bitta xabarda rasm va audioni birga qo'ya olmaydi, shuning uchun
ularni bitta videoga birlashtiramiz. Video sekin zoom bilan jonlanadi
(statik rasm o'rniga) — lentada ko'proq e'tibor tortadi.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

LOG = logging.getLogger("video")


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

    # Sekin zoom (Ken Burns) + kirish/chiqish fade
    vf = (
        f"scale={size*2}:{size*2}:force_original_aspect_ratio=increase,"
        f"crop={size*2}:{size*2},"
        f"zoompan=z='min(zoom+0.0006,1.10)':d={frames}:s={size}x{size}:fps={fps},"
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
