"""Cắt vùng có tiếng thành các chunk 20–30 giây."""

from dataclasses import dataclass


MIN_CHUNK_S = 20
MAX_CHUNK_S = 30
OVERLAP_S = 1
MAX_GAP_S = 2
MIN_TAIL_S = 0.3


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
