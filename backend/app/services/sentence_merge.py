"""Gộp các đoạn Whisper cắt giữa câu. Whisper ngắt theo độ dài, không theo ý câu."""

MAX_GAP_MS = 1500
MAX_SENTENCE_MS = 30_000
_SENTENCE_END = (".", "?", "!", "…")
_CLOSERS = "\"'”’)]"
_CONTINUES = (",", ";", ":")


def should_merge(
    prev_text: str,
    prev_start_ms: int,
    prev_end_ms: int,
    prev_label: str | None,
    next_text: str,
    next_start_ms: int,
    next_end_ms: int,
    next_label: str | None,
) -> bool:
    """Câu đầu chưa kết thúc, và câu sau là phần tiếp của cùng một người."""
    if prev_label != next_label:
        return False
    if next_start_ms - prev_end_ms > MAX_GAP_MS or next_end_ms - prev_start_ms > MAX_SENTENCE_MS:
        return False
    tail = prev_text.rstrip().rstrip(_CLOSERS)
    if not tail or tail.endswith(_SENTENCE_END):
        return False
    if tail.endswith(_CONTINUES):
        return True
    # Whisper viết hoa đầu câu mới, nên chữ thường hoặc chữ số là phần tiếp của câu trước.
    head = next_text.lstrip()
    return bool(head) and not head[0].isupper()
