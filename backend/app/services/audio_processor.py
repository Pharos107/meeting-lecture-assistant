"""FFmpeg và chuẩn hóa Opus. Kiến trúc mục 2.2."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 4
MAX_PCM_BYTES = 800 * 1024 * 1024


class MediaError(Exception):
    """Lỗi file đầu vào. `code` là mã lỗi ghi vào jobs.error_code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Probe:
    has_audio: bool
    duration_s: float | None


@dataclass(frozen=True)
class NormalizedAudio:
    opus_path: Path
    pcm_path: Path
    duration_ms: int


def probe(path: Path) -> Probe:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_streams",
        "-show_format",
        str(path),
    ]
    result = subprocess.run(command, capture_output=True, timeout=120)
    if result.returncode != 0:
        return Probe(False, None)
    try:
        data = json.loads(result.stdout.decode("utf-8", errors="replace") or "{}")
    except ValueError:
        return Probe(False, None)
    streams = data.get("streams") or []
    has_audio = any(stream.get("codec_type") == "audio" for stream in streams)
    duration: float | None = None
    raw = (data.get("format") or {}).get("duration")
    try:
        duration = float(raw) if raw not in (None, "N/A") else None
    except (TypeError, ValueError):
        duration = None
    return Probe(has_audio, duration)


def check_duration(duration_s: float | None, max_duration_s: int) -> None:
    if duration_s is None:
        return
    if duration_s > max_duration_s or duration_s * SAMPLE_RATE * BYTES_PER_SAMPLE > MAX_PCM_BYTES:
        raise MediaError("duration_exceeded", "File dài hơn thời lượng cho phép.")


def _ffmpeg(arguments: list[str]) -> None:
    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *arguments]
    result = subprocess.run(command, capture_output=True)
    if result.returncode != 0:
        raise MediaError("unsupported_media", "Không đọc được âm thanh trong file.")


def normalize(source: Path, opus_path: Path, pcm_path: Path, max_duration_s: int) -> NormalizedAudio:
    """Tạo Opus canonical rồi giải mã ra PCM float32. Lỗi thì không để lại `.f32`."""
    info = probe(source)
    if not info.has_audio:
        raise MediaError("unsupported_media", "File không có luồng âm thanh.")
    check_duration(info.duration_s, max_duration_s)

    opus_path.parent.mkdir(parents=True, exist_ok=True)
    pcm_path.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != opus_path.resolve():
        staging = opus_path.with_suffix(".opus.part")
        try:
            _ffmpeg(
                ["-i", str(source), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
                 "-c:a", "libopus", "-b:a", "32k", "-f", "ogg", str(staging)]
            )
            staging.replace(opus_path)
        finally:
            staging.unlink(missing_ok=True)

    try:
        # Giải mã tới trần cộng một giây. Chạm trần nghĩa là file dài hơn mức cho phép.
        _ffmpeg(
            ["-i", str(opus_path), "-t", str(max_duration_s + 1), "-f", "f32le",
             "-acodec", "pcm_f32le", "-ac", "1", "-ar", str(SAMPLE_RATE), str(pcm_path)]
        )
        samples = pcm_path.stat().st_size // BYTES_PER_SAMPLE
        check_duration(samples / SAMPLE_RATE, max_duration_s)
    except Exception:
        pcm_path.unlink(missing_ok=True)
        raise
    return NormalizedAudio(opus_path, pcm_path, int(round(samples * 1000 / SAMPLE_RATE)))


def load_pcm(pcm_path: Path) -> np.ndarray:
    if pcm_path.stat().st_size < BYTES_PER_SAMPLE:
        return np.zeros(0, dtype=np.float32)
    return np.memmap(pcm_path, dtype="<f4", mode="r")


def close_pcm(pcm: np.ndarray | None) -> None:
    """Đóng memmap trước khi xóa file. Windows không xóa được file đang map."""
    handle = getattr(pcm, "_mmap", None)
    if handle is not None:
        handle.close()


def slice_pcm(pcm: np.ndarray, start_s: float, end_s: float) -> np.ndarray:
    start = max(0, int(round(start_s * SAMPLE_RATE)))
    end = min(len(pcm), int(round(end_s * SAMPLE_RATE)))
    return np.ascontiguousarray(pcm[start:end], dtype=np.float32)
