"""Quy tắc gộp đoạn Whisper cắt giữa câu."""

import unittest

from app.services.sentence_merge import MAX_GAP_MS, MAX_SENTENCE_MS, should_merge


def merge(prev: str, next_text: str, gap: int = 0, length: int = 8000, labels=("A", "A")) -> bool:
    return should_merge(prev, 0, 4000, labels[0], next_text, 4000 + gap, length, labels[1])


class SentenceMergeTests(unittest.TestCase):
    def test_lowercase_continues_the_sentence(self) -> None:
        self.assertTrue(merge("Trọng", "tâm trước mắt của Indonesia"))
        self.assertTrue(merge("thảo luận về khung pháp lý", "trong Hiệp hội các quốc gia."))

    def test_digit_continues_the_sentence(self) -> None:
        self.assertTrue(merge("sản lượng giảm khoảng", "15% so với tháng trước."))

    def test_comma_continues_even_before_a_name(self) -> None:
        self.assertTrue(merge("Malaysia đề xuất,", "Indonesia đồng ý thảo luận."))

    def test_capital_after_open_sentence_stays_apart(self) -> None:
        self.assertFalse(merge("cơ chế hợp tác khu vực", "Trọng"))

    def test_finished_sentence_stays_apart(self) -> None:
        self.assertFalse(merge("Đã chốt lịch.", "và việc tiếp theo"))
        self.assertFalse(merge("Có đúng không?", "dạ đúng"))
        self.assertFalse(merge('Anh nói "xong."', "rồi đi về"))

    def test_other_speaker_stays_apart(self) -> None:
        self.assertFalse(merge("mình chốt", "lịch nhé", labels=("A", "B")))
        self.assertTrue(merge("mình chốt", "lịch nhé", labels=(None, None)))

    def test_long_pause_stays_apart(self) -> None:
        self.assertTrue(merge("mình chốt", "lịch nhé", gap=MAX_GAP_MS))
        self.assertFalse(merge("mình chốt", "lịch nhé", gap=MAX_GAP_MS + 1))

    def test_too_long_stays_apart(self) -> None:
        self.assertFalse(merge("mình chốt", "lịch nhé", length=MAX_SENTENCE_MS + 1))
