"""Gán nhãn người nói cho từ và khớp hồ sơ giọng."""

import math
import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerTurn:
    start_ms: int
    end_ms: int
    label: str


@dataclass(frozen=True)
class WordSpan:
    start_ms: int
    end_ms: int
    speaker_label: str | None = None


def _overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> int:
    return max(0, min(end_a, end_b) - max(start_a, start_b))


def label_for_word(start_ms: int, end_ms: int, turns: list[SpeakerTurn]) -> str | None:
    duration = end_ms - start_ms
    if duration <= 0:
        return None
    best_label: str | None = None
    best_overlap = 0
    for turn in turns:
        overlap = _overlap(start_ms, end_ms, turn.start_ms, turn.end_ms)
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = turn.label
    if best_label is None or best_overlap * 2 < duration:
        return None
    return best_label


def label_for_segment(words: list[WordSpan]) -> str | None:
    totals: dict[str, int] = {}
    for word in words:
        if word.speaker_label is None:
            continue
        totals[word.speaker_label] = totals.get(word.speaker_label, 0) + (word.end_ms - word.start_ms)
    if not totals:
        return None
    return max(totals.items(), key=lambda item: item[1])[0]


# Lượt ngắn hơn cả hai mức này coi là nhiễu ở biên lượt nói của pyannote, không tách câu.
MIN_RUN_WORDS = 2
MIN_RUN_MS = 800


def _resolve_null_labels(words: list[WordSpan]) -> list[str | None]:
    """Từ chưa có nhãn theo từ có nhãn gần nhất trong câu, đo bằng khoảng cách thời gian."""
    labels = [word.speaker_label for word in words]
    known = [index for index, label in enumerate(labels) if label is not None]
    if not known:
        return labels
    resolved = list(labels)
    for index, label in enumerate(labels):
        if label is not None:
            continue
        before = max((k for k in known if k < index), default=None)
        after = min((k for k in known if k > index), default=None)
        if before is None:
            resolved[index] = labels[after]
        elif after is None:
            resolved[index] = labels[before]
        else:
            gap_before = words[index].start_ms - words[before].end_ms
            gap_after = words[after].start_ms - words[index].end_ms
            resolved[index] = labels[before] if gap_before <= gap_after else labels[after]
    return resolved


def split_by_speaker(words: list[WordSpan]) -> list[tuple[int, int, str | None]]:
    """Chia một câu tại chỗ đổi người nói. Trả các khoảng [đầu, cuối) theo chỉ số từ, kèm nhãn.

    Từ null đi theo lượt gần nhất. Lượt dưới MIN_RUN_WORDS từ và ngắn hơn MIN_RUN_MS nhập vào
    lượt bên cạnh, nên một từ lệch biên không cắt câu thành mảnh.
    """
    if not words:
        return []
    resolved = _resolve_null_labels(words)
    runs: list[list[int]] = []
    for index, label in enumerate(resolved):
        if runs and resolved[runs[-1][0]] == label:
            runs[-1][1] = index + 1
        else:
            runs.append([index, index + 1])

    def is_short(run: list[int]) -> bool:
        count = run[1] - run[0]
        duration = words[run[1] - 1].end_ms - words[run[0]].start_ms
        return count < MIN_RUN_WORDS and duration < MIN_RUN_MS

    while len(runs) > 1:
        short = [position for position, run in enumerate(runs) if is_short(run)]
        if not short:
            break
        position = short[0]
        if position == 0:
            target = 1
        elif position == len(runs) - 1:
            target = position - 1
        else:
            left, right = runs[position - 1], runs[position + 1]
            target = position - 1 if left[1] - left[0] >= right[1] - right[0] else position + 1
        low, high = sorted((position, target))
        runs[low] = [runs[low][0], runs[high][1]]
        del runs[high]
        # Hai lượt cùng người hai bên một lượt vừa nhập thì gộp luôn.
        merged: list[list[int]] = []
        for run in runs:
            if merged and label_for_segment(words[merged[-1][0] : merged[-1][1]]) == label_for_segment(
                words[run[0] : run[1]]
            ):
                merged[-1][1] = run[1]
            else:
                merged.append(run)
        runs = merged
    return [(start, end, label_for_segment(words[start:end])) for start, end in runs]


def pack_embedding(values: list[float]) -> bytes:
    return struct.pack("<" + "f" * len(values), *[float(value) for value in values])


def unpack_embedding(blob: bytes) -> list[float]:
    size = len(blob) // 4
    if size == 0:
        return []
    return list(struct.unpack("<" + "f" * size, bytes(blob)[: size * 4]))


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


@dataclass(frozen=True)
class VoiceProfileVector:
    profile_id: str
    embedding: list[float]
    model: str


def match_speakers(
    cluster_vectors: dict[str, list[float]],
    profiles: list[VoiceProfileVector],
    *,
    current_model: str,
    threshold: float = 0.75,
    margin: float = 0.05,
) -> dict[str, str]:
    """Trả map nhãn buổi sang profile_id. Hồ sơ khác pipeline bị bỏ."""
    usable = [profile for profile in profiles if profile.model == current_model]
    normalized_profiles = [
        VoiceProfileVector(profile.profile_id, l2_normalize(profile.embedding), profile.model)
        for profile in usable
    ]
    scores: list[tuple[str, str, float]] = []
    for label, vector in cluster_vectors.items():
        normalized = l2_normalize(vector)
        for profile in normalized_profiles:
            score = dot(normalized, profile.embedding)
            if score >= threshold:
                scores.append((label, profile.profile_id, score))

    changed = True
    while changed:
        changed = False
        by_label: dict[str, list[tuple[str, float]]] = {}
        by_profile: dict[str, list[tuple[str, float]]] = {}
        for label, profile_id, score in scores:
            by_label.setdefault(label, []).append((profile_id, score))
            by_profile.setdefault(profile_id, []).append((label, score))
        drop: set[tuple[str, str]] = set()
        for label, pairs in by_label.items():
            if len(pairs) < 2:
                continue
            ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
            if ordered[0][1] - ordered[1][1] >= margin:
                drop.update((label, profile_id) for profile_id, _score in ordered[1:])
            else:
                drop.update((label, profile_id) for profile_id, _score in ordered)
        for profile_id, pairs in by_profile.items():
            if len(pairs) < 2:
                continue
            ordered = sorted(pairs, key=lambda item: item[1], reverse=True)
            if ordered[0][1] - ordered[1][1] >= margin:
                drop.update((label, profile_id) for label, _score in ordered[1:])
            else:
                drop.update((label, profile_id) for label, _score in ordered)
        if drop:
            scores = [item for item in scores if (item[0], item[1]) not in drop]
            changed = True
    return {label: profile_id for label, profile_id, _score in scores}
