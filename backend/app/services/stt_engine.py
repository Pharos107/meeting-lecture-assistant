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
# Bản nháp PT2 cùng ngưỡng, nhưng không đệm và tách ở khoảng lặng 200 ms, để đo được
# luật đóng câu khi lặng 600 ms và cắt tại khoảng lặng từ 200 ms. Kiến trúc mục 3.2.
LIVE_VAD_PARAMETERS = {**VAD_PARAMETERS, "min_silence_duration_ms": 200, "speech_pad_ms": 0}
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
# Lời mời đăng ký kênh: bỏ cả câu ngắn chứa cụm này ở bất kỳ đâu, như
# "Các bạn hãy đăng kí cho kênh lalaschool Để không bỏ lỡ những video hấp dẫn"
# hay câu đuôi đứng riêng "Để không bỏ lỡ những video hấp dẫn".
_CALL_TO_ACTION = (
    "hãy subscribe",
    "subscribe cho kênh",
    "hãy đăng ký kênh",
    "hãy đăng ký cho kênh",
    "không bỏ lỡ những video",
    "theo dõi và đăng ký kênh",
    "like share và đăng ký kênh",
    "đăng ký kênh để ủng hộ kênh",
)
_CALL_TO_ACTION_MAX_WORDS = 20
# Câu dài hơn trần: bỏ khi số từ nằm ngoài mọi cụm đã biết không quá mức này.
_CALL_TO_ACTION_MAX_OTHER_WORDS = 8


class GpuOutOfMemory(Exception):
    pass


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Whisper viết cả "đăng kí" lẫn "đăng ký".
    return text.replace("đăng kí", "đăng ký")


_HALLUCINATED_PLAIN = tuple(_plain(item) for item in _HALLUCINATED)
_CALL_TO_ACTION_PLAIN = tuple(_plain(item) for item in _CALL_TO_ACTION)
_KNOWN_PHRASES = tuple(item.split() for item in _HALLUCINATED_PLAIN + _CALL_TO_ACTION_PLAIN)


def is_hallucination(text: str) -> bool:
    plain = _plain(text)
    if not plain:
        return False
    for phrase in _HALLUCINATED_PLAIN:
        if plain == phrase or (plain.startswith(phrase) and len(plain) - len(phrase) <= 25):
            return True
    words = plain.split()
    padded = f" {plain} "
    if not any(f" {phrase} " in padded for phrase in _CALL_TO_ACTION_PLAIN):
        return False
    if len(words) <= _CALL_TO_ACTION_MAX_WORDS:
        return True
    # Câu dài hơn trần vẫn là câu bịa khi gần như toàn bộ là các cụm đã biết, như
    # "Cảm ơn các bạn đã theo dõi và hãy subscribe cho kênh lalaschool Để không bỏ lỡ
    # những video hấp dẫn" (21 từ, #25). Lời thật dính sau lời mời thì còn nhiều từ lạ.
    return _uncovered_words(words) <= _CALL_TO_ACTION_MAX_OTHER_WORDS


def _coverage(words: list[str], phrases=_KNOWN_PHRASES) -> list[bool]:
    covered = [False] * len(words)
    for phrase in phrases:
        size = len(phrase)
        for start in range(len(words) - size + 1):
            if words[start : start + size] == phrase:
                covered[start : start + size] = [True] * size
    return covered


def _uncovered_words(words: list[str]) -> int:
    return _coverage(words).count(False)


# Từ lạ xen giữa hai cụm, như tên kênh "Ghiền Mì Gõ" và chữ "để", và từ lạ còn ở mép câu, như "các bạn".
_CALL_TO_ACTION_GAP = 4
_CALL_TO_ACTION_EDGE = 2
_CALL_TO_ACTION_PLAIN_WORDS = tuple(item.split() for item in _CALL_TO_ACTION_PLAIN)
_TRIM_PHRASES = _KNOWN_PHRASES + (_plain("để không bỏ lỡ những video hấp dẫn").split(),)


def call_to_action_span(words: list[str]) -> tuple[int, int] | None:
    """Khoảng [đầu, cuối) theo chỉ số từ của lời mời đăng ký kênh dính trong một câu dài, hoặc None.

    Bắt đầu từ một cụm lời mời, nới sang hai bên qua các cụm đã biết, cho phép tối đa
    _CALL_TO_ACTION_GAP từ lạ xen giữa. Còn không quá _CALL_TO_ACTION_EDGE từ ở mép câu thì lấy tới mép.
    """
    hits = _coverage(words, _CALL_TO_ACTION_PLAIN_WORDS)
    if True not in hits:
        return None
    covered = _coverage(words, _TRIM_PHRASES)
    first = hits.index(True)
    start, end = first, first
    while end < len(words) and covered[end]:
        end += 1
    while True:
        ahead = end
        while ahead < len(words) and ahead - end < _CALL_TO_ACTION_GAP and not covered[ahead]:
            ahead += 1
        if ahead < len(words) and covered[ahead]:
            end = ahead
            while end < len(words) and covered[end]:
                end += 1
            continue
        break
    while True:
        back = start
        while back > 0 and start - back < _CALL_TO_ACTION_GAP and not covered[back - 1]:
            back -= 1
        if back > 0 and covered[back - 1]:
            start = back - 1
            while start > 0 and covered[start - 1]:
                start -= 1
            continue
        break
    if start <= _CALL_TO_ACTION_EDGE:
        start = 0
    if len(words) - end <= _CALL_TO_ACTION_EDGE:
        end = len(words)
    return start, end


def trim_call_to_action(words: list[dict]) -> list[dict]:
    """Bỏ các từ thuộc lời mời đăng ký kênh dính trong câu dài, giữ lời thật hai bên (#25)."""
    tokens: list[str] = []
    owner: list[int] = []
    for index, word in enumerate(words):
        for token in _plain(word["text"]).split():
            # _plain quy "đăng kí" trên cả chuỗi. Tách theo từ thì phải quy lại ở đây.
            if token == "kí" and tokens and tokens[-1] == "đăng":
                token = "ký"
            tokens.append(token)
            owner.append(index)
    span = call_to_action_span(tokens)
    if span is None:
        return words
    dropped = set(owner[span[0] : span[1]])
    return [word for index, word in enumerate(words) if index not in dropped]


def trim_call_to_action_text(text: str) -> str:
    kept = trim_call_to_action([{"text": part} for part in text.split()])
    return " ".join(word["text"] for word in kept)


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


def speech_regions(pcm: np.ndarray, parameters: dict = VAD_PARAMETERS) -> list[tuple[float, float]]:
    """Vùng có tiếng, đổi từ chỉ số mẫu sang giây."""
    if len(pcm) == 0:
        return []
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    stamps = get_speech_timestamps(np.asarray(pcm, dtype=np.float32), VadOptions(**parameters))
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


def load_whisper(name: str):
    """Nạp từ cache trước. Model đã tải thì không phải chờ Hugging Face trả lời, mạng chậm vẫn mở được phiên."""
    from faster_whisper import WhisperModel

    options = {
        "device": os.environ.get("WHISPER_DEVICE", "cuda"),
        "compute_type": os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
    }
    try:
        try:
            return WhisperModel(name, local_files_only=True, **options)
        except OSError:
            # Chưa có trong cache: tải về.
            return WhisperModel(name, **options)
    except RuntimeError as error:
        if _is_oom(error):
            raise GpuOutOfMemory(str(error)) from error
        raise


def standard_model_name(model_name: str | None = None) -> str:
    return model_name or os.environ.get("WHISPER_MODEL", "large-v3-turbo")


class WhisperEngine:
    """Một model trong VRAM cho cả job. Gọi `release` trước khi nạp pyannote."""

    def __init__(self, model_name: str | None = None, *, model=None) -> None:
        self.beam_size = int(os.environ.get("WHISPER_BEAM_SIZE", "5"))
        # Phiên nghe đã nạp cùng model cho bản nháp thì đưa sang, không nạp lần hai.
        self.model = model if model is not None else load_whisper(standard_model_name(model_name))

    def transcribe(self, audio: np.ndarray, vocabulary: str | None, greedy: bool = False) -> list[dict]:
        """Trả câu với start, end, words tính bằng giây tương đối trong `audio`. `greedy` giải mã với beam 1."""
        segments, _info = self.model.transcribe(
            audio,
            language="vi",
            task="transcribe",
            beam_size=1 if greedy else self.beam_size,
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
            start, end, text = float(segment.start), float(segment.end), segment.text.strip()
            kept = trim_call_to_action(words)
            if len(kept) != len(words):
                if not kept:
                    continue
                words = kept
                start, end = words[0]["start"], words[-1]["end"]
                text = " ".join(word["text"] for word in words)
            produced.append({"start": start, "end": end, "text": text, "words": words})
        return produced

    def release(self) -> None:
        self.model = None
        free_cuda()


class DraftEngine:
    """Model của pass 1, mặc định cùng `large-v3-turbo` với bản chuẩn. Không có mốc từ, chỉ trả chữ của cả câu."""

    def __init__(self, model_name: str | None = None) -> None:
        self.beam_size = int(os.environ.get("WHISPER_DRAFT_BEAM_SIZE", "1"))
        self.model_name = model_name or os.environ.get("WHISPER_DRAFT_MODEL", "large-v3-turbo")
        self.model = load_whisper(self.model_name)

    def hand_over(self) -> WhisperEngine | None:
        """Bản chuẩn dùng lại model đang nằm trong VRAM khi hai pass cùng một model."""
        if self.model is None or self.model_name != standard_model_name():
            return None
        engine = WhisperEngine(model=self.model)
        self.model = None
        return engine

    def transcribe(self, audio: np.ndarray, vocabulary: str | None) -> str:
        segments, _info = self.model.transcribe(
            audio,
            language="vi",
            task="transcribe",
            beam_size=self.beam_size,
            word_timestamps=False,
            condition_on_previous_text=False,
            vad_filter=False,
            temperature=0.0,
            initial_prompt=prompt_or_none(vocabulary),
        )
        kept = [trim_call_to_action_text(segment.text.strip()) for segment in segments if not is_hallucination(segment.text)]
        return " ".join(text for text in kept if text)

    def release(self) -> None:
        self.model = None
        free_cuda()
