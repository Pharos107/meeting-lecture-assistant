"""Silero VAD và Whisper bản chuẩn. Kiến trúc mục 2.3 và 2.4."""

import gc
import os
import re
import unicodedata

import numpy as np

from app.services.audio_processor import SAMPLE_RATE

VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 250,
    "min_silence_duration_ms": 400,
    "speech_pad_ms": 200,
}
MAX_PROMPT_CHARS = 800

# Câu Whisper hay bịa ở đoạn ồn hoặc lặng. Chỉ bỏ khi cả câu chỉ là cụm này.
_HALLUCINATED = (
    "hãy đăng ký kênh",
    "hãy subscribe cho kênh",
    "đăng ký kênh để ủng hộ",
    "cảm ơn các bạn đã theo dõi",
    "cảm ơn các bạn đã xem",
    "hẹn gặp lại các bạn trong những video tiếp theo",
    "nhớ like share và đăng ký kênh",
    "subscribe",
)


class GpuOutOfMemory(Exception):
    pass


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_HALLUCINATED_PLAIN = tuple(_plain(item) for item in _HALLUCINATED)


def is_hallucination(text: str) -> bool:
    plain = _plain(text)
    if not plain:
        return False
    for phrase in _HALLUCINATED_PLAIN:
        if plain == phrase or (plain.startswith(phrase) and len(plain) - len(phrase) <= 25):
            return True
    return False


def speech_regions(pcm: np.ndarray) -> list[tuple[float, float]]:
    """Vùng có tiếng, đổi từ chỉ số mẫu sang giây."""
    if len(pcm) == 0:
        return []
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    stamps = get_speech_timestamps(np.asarray(pcm, dtype=np.float32), VadOptions(**VAD_PARAMETERS))
    return [(stamp["start"] / SAMPLE_RATE, stamp["end"] / SAMPLE_RATE) for stamp in stamps]


def prompt_or_none(vocabulary: str | None) -> str | None:
    if not vocabulary or not vocabulary.strip():
        return None
    return vocabulary.strip()[:MAX_PROMPT_CHARS]


def free_cuda() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _is_oom(error: BaseException) -> bool:
    text = str(error).lower()
    return "out of memory" in text or "cuda_error_out_of_memory" in text


class WhisperEngine:
    """Một model trong VRAM cho cả job. Gọi `release` trước khi nạp pyannote."""

    def __init__(self, model_name: str | None = None) -> None:
        from faster_whisper import WhisperModel

        self.beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "5"))
        try:
            self.model = WhisperModel(
                model_name or os.environ.get("WHISPER_MODEL", "large-v3-turbo"),
                device=os.environ.get("WHISPER_DEVICE", "cuda"),
                compute_type=os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
            )
        except RuntimeError as error:
            if _is_oom(error):
                raise GpuOutOfMemory(str(error)) from error
            raise

    def transcribe(self, audio: np.ndarray, vocabulary: str | None) -> list[dict]:
        """Trả câu với start, end, words tính bằng giây tương đối trong `audio`."""
        segments, _info = self.model.transcribe(
            audio,
            language="vi",
            task="transcribe",
            beam_size=self.beam_size,
            word_timestamps=True,
            condition_on_previous_text=False,
            vad_filter=False,
            temperature=0.0,
            compression_ratio_threshold=2.4,
            log_prob_threshold=-1.0,
            no_speech_threshold=0.6,
            initial_prompt=prompt_or_none(vocabulary),
        )
        produced: list[dict] = []
        for segment in segments:
            if is_hallucination(segment.text):
                continue
            words = [
                {"text": word.word.strip(), "start": float(word.start), "end": float(word.end)}
                for word in (segment.words or [])
                if word.word.strip()
            ]
            produced.append(
                {
                    "start": float(segment.start),
                    "end": float(segment.end),
                    "text": segment.text.strip(),
                    "words": words,
                }
            )
        return produced

    def release(self) -> None:
        self.model = None
        free_cuda()
