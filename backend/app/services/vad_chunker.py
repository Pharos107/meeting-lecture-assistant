"""Cắt vùng có tiếng thành các chunk 20–30 giây."""

from dataclasses import dataclass


MIN_CHUNK_S = 20
MAX_CHUNK_S = 30
OVERLAP_S = 1
MAX_GAP_S = 2
MIN_TAIL_S = 0.3
# Whisper có lúc trả trống một vùng có tiếng nằm giữa chunk, nhất là ở giảng đường vang
# hoặc người nói xa micro. Nhận dạng riêng khoảng trống đó thường lấy lại được chữ.
MIN_EMPTY_S = 1.5
EDGE_TOLERANCE_S = 0.1


@dataclass(frozen=True)
class SpeechSlice:
    start: float
    end: float
    forced: bool


@dataclass(frozen=True)
class SpeechChunk:
    start: float
    end: float
    slices: tuple[SpeechSlice, ...]

    @property
    def last_forced(self) -> bool:
        return self.slices[-1].forced


def split_region(start: float, end: float) -> list[SpeechSlice]:
    if end < start:
        return []
    if end - start <= MAX_CHUNK_S:
        return [SpeechSlice(start, end, False)]
    slices: list[SpeechSlice] = []
    cursor = start
    while end - cursor > MAX_CHUNK_S:
        slices.append(SpeechSlice(cursor, cursor + MAX_CHUNK_S, True))
        cursor = cursor + MAX_CHUNK_S - OVERLAP_S
    if end - cursor > MIN_TAIL_S:
        slices.append(SpeechSlice(cursor, end, False))
    return slices


def build_chunks(regions: list[tuple[float, float]]) -> list[SpeechChunk]:
    slices: list[SpeechSlice] = []
    for start, end in regions:
        slices.extend(split_region(start, end))
    if not slices:
        return []
    groups: list[list[SpeechSlice]] = [[slices[0]]]
    for nxt in slices[1:]:
        current = groups[-1]
        last = current[-1]
        gap = nxt.start - last.end
        span = nxt.end - current[0].start
        if (not last.forced) and gap <= MAX_GAP_S and span <= MAX_CHUNK_S:
            current.append(nxt)
        else:
            groups.append([nxt])
    return [SpeechChunk(group[0].start, group[-1].end, tuple(group)) for group in groups]


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float
    end: float
    chunk_index: int


def keep_word(word: TimedWord, chunks: list[SpeechChunk]) -> bool:
    center = (word.start + word.end) / 2
    index = word.chunk_index
    if index > 0:
        previous = chunks[index - 1]
        current = chunks[index]
        if current.start < previous.end:
            boundary = (previous.end + current.start) / 2
            if center < boundary:
                return False
    if index + 1 < len(chunks):
        current = chunks[index]
        nxt = chunks[index + 1]
        if nxt.start < current.end:
            boundary = (current.end + nxt.start) / 2
            if center >= boundary:
                return False
    return True


def drop_overlapping_words(words: list[TimedWord], chunks: list[SpeechChunk]) -> list[TimedWord]:
    return [word for word in words if keep_word(word, chunks)]


def _covered(produced: list[dict], offset: float) -> list[tuple[float, float]]:
    spans: list[tuple[float, float]] = []
    for raw in produced:
        words = raw.get("words") or []
        if words:
            spans.extend((offset + float(word["start"]), offset + float(word["end"])) for word in words)
        elif "start" in raw and "end" in raw:
            spans.append((offset + float(raw["start"]), offset + float(raw["end"])))
    return sorted(spans)


def empty_spans(chunk: SpeechChunk, produced: list[dict]) -> list[tuple[float, float]]:
    """Phần của từng vùng VAD không có từ nào, dài từ MIN_EMPTY_S. Mốc tính bằng giây trong file."""
    covered = _covered(produced, chunk.start)
    spans: list[tuple[float, float]] = []
    for piece in chunk.slices:
        cursor = piece.start
        for start, end in covered:
            if end <= cursor or start >= piece.end:
                continue
            if start - cursor >= MIN_EMPTY_S:
                spans.append((cursor, start))
            cursor = max(cursor, end)
        if piece.end - cursor >= MIN_EMPTY_S:
            spans.append((cursor, piece.end))
    # Khoảng trống phủ cả chunk thì nhận dạng lại cũng là cùng một audio.
    return [
        (start, end)
        for start, end in spans
        if start > chunk.start + EDGE_TOLERANCE_S or end < chunk.end - EDGE_TOLERANCE_S
    ]


def _first_start(raw: dict) -> float:
    words = raw.get("words") or []
    return float(words[0]["start"]) if words else float(raw.get("start", 0))


def _shifted(raw: dict, shift: float) -> dict:
    moved = dict(raw)
    for key in ("start", "end"):
        if key in moved:
            moved[key] = float(moved[key]) + shift
    moved["words"] = [
        {**word, "start": float(word["start"]) + shift, "end": float(word["end"]) + shift}
        for word in raw.get("words") or []
    ]
    return moved


def fill_empty_spans(chunk: SpeechChunk, produced: list[dict], transcribe, retry=None) -> list[dict]:
    """Nhận dạng riêng từng khoảng trống của chunk rồi xếp chung theo thời gian, mốc tương đối trong chunk.

    Khoảng nhận dạng riêng vẫn rỗng thì chạy `retry` nếu có. Trên audio có tiếng, beam search của turbo có lúc
    ra lời mời đăng ký kênh thay cho lời nói thật, bộ lọc bỏ câu đó và khoảng thành trống. Giải mã greedy
    lấy lại được chữ ở những chỗ như vậy, xem kiến trúc mục 2.3.
    """
    merged = list(produced)
    for start, end in empty_spans(chunk, produced):
        piece = SpeechChunk(start, end, (SpeechSlice(start, end, False),))
        found = transcribe(piece)
        if not found and retry is not None:
            found = retry(piece)
        merged.extend(_shifted(raw, start - chunk.start) for raw in found)
    return sorted(merged, key=_first_start)
