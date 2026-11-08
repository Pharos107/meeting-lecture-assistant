"""Gán nhãn từ và khớp hồ sơ giọng."""

import unittest

from app.services.speaker_align import (
    SpeakerTurn,
    VoiceProfileVector,
    WordSpan,
    label_for_word,
    match_speakers,
    split_by_speaker,
)


def spans(*items: tuple[int, int, str | None]) -> list[WordSpan]:
    return [WordSpan(start, end, label) for start, end, label in items]


class SplitBySpeakerTests(unittest.TestCase):
    A, B = "SPEAKER_00", "SPEAKER_01"

    def test_one_speaker_stays_one_sentence(self) -> None:
        words = spans((0, 300, self.A), (300, 600, None), (600, 900, self.A))
        self.assertEqual(split_by_speaker(words), [(0, 3, self.A)])

    def test_splits_where_label_changes(self) -> None:
        words = spans((0, 300, self.A), (300, 600, self.A), (700, 1000, self.B), (1000, 1400, self.B))
        self.assertEqual(split_by_speaker(words), [(0, 2, self.A), (2, 4, self.B)])

    def test_null_word_follows_the_nearest_turn(self) -> None:
        words = spans(
            (0, 300, self.A), (300, 600, self.A), (650, 900, None), (1500, 1800, self.B), (1800, 2100, self.B)
        )
        self.assertEqual(split_by_speaker(words), [(0, 3, self.A), (3, 5, self.B)])

    def test_one_stray_word_does_not_cut_the_sentence(self) -> None:
        words = spans((0, 300, self.A), (300, 600, self.A), (600, 800, self.B), (800, 1100, self.A))
        self.assertEqual(split_by_speaker(words), [(0, 4, self.A)])

    def test_short_reply_of_one_long_word_is_kept(self) -> None:
        # "Vâng" kéo dài gần 1 giây là một lượt thật, không phải lệch biên.
        words = spans((0, 300, self.A), (300, 600, self.A), (700, 1600, self.B))
        self.assertEqual(split_by_speaker(words), [(0, 2, self.A), (2, 3, self.B)])

    def test_all_null_is_one_sentence_without_label(self) -> None:
        self.assertEqual(split_by_speaker(spans((0, 300, None), (300, 600, None))), [(0, 2, None)])
        self.assertEqual(split_by_speaker([]), [])


class SpeakerTests(unittest.TestCase):
    def test_half_overlap_counts_and_less_does_not(self) -> None:
        turns = [SpeakerTurn(0, 500, "SPEAKER_00")]
        self.assertEqual(label_for_word(0, 1000, turns), "SPEAKER_00")
        self.assertIsNone(label_for_word(0, 1001, turns))

    def test_margin_drops_a_contested_cluster(self) -> None:
        profiles = [
            VoiceProfileVector("a", [1.0, 0.0], "pyannote/speaker-diarization-3.1"),
            VoiceProfileVector("b", [0.99, 0.1410673598], "pyannote/speaker-diarization-3.1"),
            VoiceProfileVector("old", [1.0, 0.0], "pipeline-cũ"),
        ]
        mapping = match_speakers(
            {"SPEAKER_00": [1.0, 0.0]},
            profiles,
            current_model="pyannote/speaker-diarization-3.1",
        )
        self.assertEqual(mapping, {})

    def test_clear_score_keeps_one_profile(self) -> None:
        profiles = [
            VoiceProfileVector("lan", [1.0, 0.0], "pyannote/speaker-diarization-3.1"),
            VoiceProfileVector("binh", [0.0, 1.0], "pyannote/speaker-diarization-3.1"),
        ]
        mapping = match_speakers(
            {"SPEAKER_00": [1.0, 0.0], "SPEAKER_01": [0.0, 1.0]},
            profiles,
            current_model="pyannote/speaker-diarization-3.1",
        )
        self.assertEqual(mapping, {"SPEAKER_00": "lan", "SPEAKER_01": "binh"})
