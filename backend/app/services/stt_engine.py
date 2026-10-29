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
# Bỏ câu bịa sau khoảng lặng dài hơn mức này. Cần word_timestamps=True.
HALLUCINATION_SILENCE_S = 2.0
# Người nói nhanh nhất đo được khoảng 8,5 từ/giây. Câu bịa của Whisper dồn hàng chục từ vào dưới 1 giây.
MAX_WORDS_PER_SECOND = 12
MIN_WORDS_FOR_RATE = 4

# Câu Whisper hay bịa ở đoạn ồn hoặc lặng. Chỉ bỏ khi cả câu chỉ là cụm này.
_HALLUCINATED = (
    "hãy đăng ký kênh",
    "hãy subscribe cho kênh",
    "đăng ký kênh để",
    "cảm ơn các bạn đã theo dõi",
    "cảm ơn các bạn đã xem",
    "hẹn gặp lại các bạn trong những video tiếp theo",
    "nhớ like share và đăng ký kênh",
    "subscribe",
)
# Lời mời đăng ký kênh: bỏ cả câu ngắn mở đầu bằng cụm này, dù phần đuôi dài, như
# "Hãy subscribe cho kênh La La School để không bỏ lỡ những video hấp dẫn".
_CALL_TO_ACTION = (
    "hãy subscribe",
    "hãy đăng ký kênh",
    "hãy đăng kí kênh",
    "các bạn hãy đăng ký kênh",
    "các bạn hãy đăng kí kênh",
)
_CALL_TO_ACTION_MAX_WORDS = 20


class GpuOutOfMemory(Exception):
    pass


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_HALLUCINATED_PLAIN = tuple(_plain(item) for item in _HALLUCINATED)
_CALL_TO_ACTION_PLAIN = tuple(_plain(item) for item in _CALL_TO_ACTION)


def is_hallucination(text: str) -> bool:
    plain = _plain(text)
    if not plain:
        return False
    for phrase in _HALLUCINATED_PLAIN:
        if plain == phrase or (plain.startswith(phrase) and len(plain) - len(phrase) <= 25):
            return True
    if len(plain.split()) <= _CALL_TO_ACTION_MAX_WORDS and plain.startswith(_CALL_TO_ACTION_PLAIN):
        return True
    return False


def too_fast(text: str, start: float, end: float) -> bool:
    """Câu bịa ở cuối cửa sổ 30 giây có mốc vài phần trăm giây mà mang hàng chục từ."""
    count = len(text.split())
    if count < MIN_WORDS_FOR_RATE:
        return False
    return count / max(end - start, 0.01) > MAX_WORDS_PER_SECOND


def collect_words(raw_words) -> list[dict]:
    """Ghép mảnh không có dấu cách đầu vào từ trước, để "150" ".000" thành "150.000"."""
    words: list[dict] = []
    for word in raw_words or []:
        text = word.word.strip()
        if not text:
            continue
        if words and not word.word[:1].isspace():
            words[-1]["text"] += text
            words[-1]["end"] = float(word.end)
            continue
        words.append({"text": text, "start": float(word.start), "end": float(word.end)})
    return words


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
            hallucination_silence_threshold=HALLUCINATION_SILENCE_S,
            initial_prompt=prompt_or_none(vocabulary),
        )
        produced: list[dict] = []
        for segment in segments:
            if is_hallucination(segment.text) or too_fast(segment.text, segment.start, segment.end):
                continue
            words = collect_words(segment.words)
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
